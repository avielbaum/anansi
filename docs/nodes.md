# Nodes

A node is anything that serves an OpenAI-compatible `/v1/chat/completions`: vLLM (Linux), `llama-server`, or Ollama
(Windows, Linux, macOS).

## Cloud (floor) nodes

List them in the gateway config under `nodes`. The gateway calls them directly.

```json
{"url": "http://127.0.0.1:11434", "models": ["npc-small"], "upstream_model": "qwen3:1.7b",
 "extra": {"reasoning_effort": "none"}}
```

`config.ollama.json` (Ollama), `config.vllm.json` (vLLM) and `config.example.json` (mock nodes) are examples.

## Volunteer nodes

`node/agent.py` runs on a volunteer PC and connects **out** to the gateway, so it needs no open port and works behind
a home router. It polls for jobs, runs them on a local OpenAI-compatible server, and posts the answers back. It only
ever forwards `/v1/chat/completions`. Each `--slots` entry registers as a separate worker.

Gateway config (`config.pull.example.json`): a token maps to the models and settings the gateway sends that worker.

```json
"pull_tokens": {"change-me-node-token": {"models": ["npc-small"], "region": "volunteer",
                "upstream_model": "qwen3:1.7b", "extra": {"reasoning_effort": "none"}}}
```

On the volunteer machine:

```bash
python node/agent.py --gateway https://gateway.example --token change-me-node-token --local http://127.0.0.1:11434 --slots 2
```

**A volunteer sees every prompt it is sent, including the NPC's secret system prompt and the player's text, and nothing here stops it logging them.** So a title only uses volunteers if you set `"allow_volunteers": true` on it; without that flag it is served by your own nodes (and the paid overflow, if allowed) and the volunteers sit idle. Safety-judge calls, which carry the secret prompt, never go to volunteers.

To the scheduler a registered worker is an ordinary node, so routing, failover, ejection and the retry budget apply.
A worker that stops polling is forgotten after `pull_ttl_s`. A streamed request is answered correctly but relayed
whole after the node finishes.

### Staying out of the owner's way

By default the agent pauses while the machine is busy: CPU above 60 percent (sampled on Windows, load per core on Linux and macOS)
or any GPU above 60 percent. GPU load comes from `nvidia-smi` for NVIDIA anywhere; on Windows, from the system's GPU engine
counters (the ones Task Manager shows), which cover every vendor; on Linux, from the amdgpu driver for AMD; on Macs, from
`ioreg`. The highest reading wins. While paused it does not register or poll, so no job reaches it; the gateway
forgets it within about `pull_ttl_s` seconds and it registers again (and passes the entry check again) when the machine is
idle. Change the limits with `--cpu-limit` and `--gpu-limit`, or serve regardless with `--ignore-load`. Load in the 15 seconds
after the agent's own job is ignored, and a job queued just before a pause waits for the gateway's timeout and is retried on
another node. Not measured: Intel GPUs on Linux (only the CPU counts there). Tested: the Windows counters on a PC with an Intel and an
NVIDIA GPU (the Intel one rose under a WebGL load); the Linux and Mac readers only against sample output, not on real machines.

### One-step setup

`node/join.py` checks the machine, picks a model that fits, makes sure Ollama has it and starts the agent:

```bash
./node/join.sh --gateway https://gateway.example --token POOL_TOKEN          # Linux, macOS
node\join.bat --gateway https://gateway.example --token POOL_TOKEN           # Windows
python node/join.py --gateway ... --token ... --dry-run                     # show the plan, change nothing
```

- **Model choice by RAM** (DESIGN.md section 21): under 6 GB it declines; 6 to 15 GB gets `qwen3:1.7b` (about 1.4 GB);
  16 GB and up gets `qwen3:4b-instruct` (about 2.5 GB). `--model` overrides it. Not the `qwen3:4b` tag: in Ollama it is now a
  thinking-only model whose reasoning cannot be switched off, so it failed the known-answer probe and leaked reasoning into replies.
- **Thinking off for the pool.** Set the token's `extra` for the volunteers' runtime: `{"reasoning_effort": "none"}` for Ollama
  (what `join.sh` installs), `{"chat_template_kwargs": {"enable_thinking": false}}` for llama-server or vLLM. A probe reply that is
  only unfinished reasoning drops the node without a ban; it registers again after a back-off.
- **It installs nothing by itself.** If Ollama is missing or not running it says where to get it. It pulls one model, after
  checking free disk, and uses a private Python environment (`~/.anansi-venv`, httpx only) for the agent.
- **Model names:** the gateway asks for the pool's model name; the agent runs whichever model this machine has (`--model`
  on `agent.py`, set automatically by `join.py`). Quality across machines then varies with the model, which is what the
  entry probe and spot checks are for.
- Tested: model choice, the plan, and the model override in the self-checks; a dry run and a real join on Windows; a real
  `join.sh` on Ubuntu 22.04 with an NVIDIA A10 (Ollama installed, model pulled, probes passed, requests served).
  **Not tested:** `join.bat` on other Windows machines, and Ollama installation by `join` itself (it never installs it). The agent it starts pauses while the
  machine is busy, with the same `--cpu-limit`, `--gpu-limit` and `--ignore-load` options as `agent.py`.

### Verification

- **Entry probe:** a new worker joins the pool only after answering a known-answer question correctly (temperature 0,
  answer matched by regex). Built-in questions are used unless `canaries` (list of `{"user", "expect"}`) is set.
- **Spot checks:** after real jobs, with probability `canary_rate` (default 0.05), the same node is probed again.
- **Bans:** a failed entry probe, or two failed spot checks, bans the agent id and the node token it used (the token is
  stored as a hash), and drops that token's other workers. Picking a new agent id does not get round it. Give each
  volunteer their own token. A token marked `"shared": true` (one pool token for everyone) is never banned, because that
  would lock out every volunteer; only the agent id is, and a new id gets round that. Each agent keeps a random id in
  `~/.anansi-agent-id`. Timeouts and error replies are not strikes; the scheduler's ejection handles those.
- **Worker cap:** one token may have at most `max_workers` workers registered at once (default 8); past it, `429`.
- `GET /admin/stats` shows `pull.probes`, `probe_failures`, `banned`.

### Work ledger

With `db_path` set, the gateway records for each agent and UTC day: real jobs served, tokens, and probes passed or failed
(probe traffic is not counted as work; streamed replies are estimated from their size). `GET /admin/usage` shows it. Bans
are stored too, so a restart does not forgive a banned agent. The ledger is raw usage; credits are kept separately (below).

### Credits

Volunteers earn credits that games can turn into in-game items. No cash and no crypto (DESIGN.md section 5).

1. **Link the machine to a player.** `python node/agent.py --gateway ... --token ... --link` prints a one-time code
   (`ABCD-EFGH`, valid 10 minutes). The player types it into any game on this gateway, and the game sends it to
   `POST /v1/credits/link` with the player's own token. A code works once; linking again with a new code moves later
   earnings to the new player. An unlinked machine still serves jobs but earns no credit.
2. **Earning.** Each real job earns `tokens x per_1k_tokens / 1000` for the model sent to the node (config `credits.per_1k_tokens`,
   e.g. `{"qwen3:4b": 2, "default": 1}`). Probes earn nothing, and the token count is capped by the size of the text, as for the
   ledger. Amounts are stored as whole milli-credits, so sums are exact.
3. **Hold.** Credit becomes spendable `hold_days` (default 7) UTC days after it was earned. A ban voids everything still in the
   hold; credit that already matured stays.
4. **One wallet per player account** (the platform's player id, for example the Steam id), shared by every title on the
   gateway. `GET /v1/credits` shows `balance`, `pending` and linked `nodes`.
5. **Spending.** The game's **server** calls `POST /v1/credits/spend` with the title's `server_key` (never the client's key),
   the player's platform id, an amount and its own purchase id as `ref`, and grants the item only on `"result": "ok"`. A repeated
   `ref` is not charged twice. The check and the charge are one transaction, so gateways spending from one wallet at once cannot
   overdraw it (tested with 16 simultaneous spends on SQLite and Postgres).
6. **Daily cap.** `credits.max_per_day` (credits, unset by default) limits what one wallet earns per UTC day across all its
   linked machines, so linking a farm of machines to one player does not pay more than the cap. Work past it is still served
   and recorded in the ledger, but earns nothing. The check and the credit are one transaction, so gateways crediting one
   wallet at once cannot pass it (tested with 16 simultaneous credits).

Not built: what an item costs (each studio decides), Steam Inventory grants, an Unreal SDK method for credits (the other SDKs have
`credits` and `link_node`, see [sdk.md](sdk.md#volunteer-credits)) and the DESIGN.md rule that a brand-new node earns nothing for 24 hours (the 7-day hold covers the audit window).

### Leaderboard and telemetry

A public board of total tokens processed, per machine and per player, for today, the last 7 days and all time: `GET /leaderboard`
(a small web page; `?period=day|week|all`) and `GET /v1/leaderboard` (JSON, `period`, `limit` up to 100), cached for 30 seconds.
**Nothing is listed unless its owner chooses it, separately for the machine and for the player.** What is collected, shown and kept,
and the choices, are in [privacy.md](privacy.md); what a volunteer agrees to is in [volunteer-terms.md](volunteer-terms.md) (both are
drafts for counsel).

- **A machine** opts in with `python node/agent.py ... --telemetry [--name "My rig"]` (or the same flags on `join`). The agent then
  reports its CPU model, GPU models with video memory, a coarse operating system name ("Windows 10", "Linux", "macOS") and the GPU
  load sampled every 30 seconds while none of this agent's own jobs run, sent every 5 minutes. Nothing else is read: no hostname, user
  name, address, serial number or driver version. **At every start the agent says exactly what it sends, to which gateway, and that it
  is public**; `agent.py ... --telemetry-show` prints the exact report and sends nothing; `--telemetry-off` removes the machine and
  deletes what it reported. It **refuses a plain `http://` gateway on another machine** (the report would cross the network
  unencrypted). A machine silent for `retention_days` (35) drops off by itself. The page shows a short hash of the agent id, never the id.
- **The idle GPU figure is a slow average**, not a live reading: the gateway keeps 97 percent of the old value and 3 percent of each
  report (hours at one report per 5 minutes) and shows a whole percent and only the date of the last report, so the public page does not
  reveal when the owner is playing.
- **A player** opts in with `POST /v1/credits/name` `{"name": "Ada"}` (SDK: `set_leaderboard_name`); an empty name opts out and is always
  allowed. They are listed once they have a name and at least one linked machine; the board shows the name, the number of machines and
  the tokens those machines served from the day each was linked, never a Steam id or platform account. A refused name comes back with
  the reason (`bad_name`, for example "a name may not contain a link, an email address or a handle"); `not_allowed` means the
  operator switched names off or blocked the account.
- **Names are public text.** A link (`://`, `www.`), an `@` (email address or handle) or seven or more digits (a phone number) is refused,
  as is anything matching the operator's `leaderboard.blocked_names` (regular expressions). A machine whose name is refused is still
  listed under `node-<hash>` and the agent says why once. Control, zero-width and right-to-left override characters are removed and
  lengths capped (name 24, CPU and GPU 80, at most 8 GPUs).
- **What is trusted.** Tokens are measured by the gateway (real jobs only, probes excluded, a claim is capped by the size of the
  text), so they cannot be inflated. Hardware and idle load are **reported by the machine and not verified**; the page says so. A
  machine can only report if it has registered or served a job, at most once per 20 seconds, 16 KB each, and a banned machine is not ranked.
- **What the page tells browsers.** No scripts (`default-src 'none'`), no framing (`frame-ancestors 'none'`), `noindex, nofollow` (header
  and meta tag), every value escaped, a privacy link when `leaderboard.privacy_url` is set. If you show the JSON in your own UI, escape it too.
- **Moderation and switches** (config block `leaderboard`, see [gateway.md](gateway.md#leaderboard)): `enabled: false` removes the page and
  the reports, `players: false` leaves the player board empty and refuses names (for a title aimed at children). `POST /admin/leaderboard/block`
  with `{"node": "<hash shown>"}` or `{"user": "<name shown>"}` takes someone off at once and keeps them off (they still serve and play);
  add `"unblock": true` to lift it.
- **Tested.** The hardware readers have run on a real Windows PC (CPU, an Intel and an NVIDIA GPU, idle GPU load) and the whole flow
  (real agent, real gateway, real local model, the page in a browser, both opt-outs) on that PC. The Linux NVIDIA reader uses
  `nvidia-smi`, the same command the busy check has run on a real A10; the AMD (sysfs) and macOS (`system_profiler`) readers follow
  the documented formats and are tested on sample output only. The privacy controls (names, switches, blocks, the https refusal, the
  slow average, the headers, the purge) each have a self-check that fails when the control is removed. Not built: per-user history over
  time, a verified hardware check (compare reported GPU against measured tokens per second), and showing the board inside the Steam overlay.

### What this does not give you

- **No real identity:** a ban costs the volunteer their token, but whoever issues tokens can be asked for a new one, and on
  a shared token the ban is by self-chosen id only. Real identity needs the platform-bound certificates of DESIGN.md section 9.
- **Probes can be recognised:** a node that spots the probe (no system prompt, a few fixed questions) can pass them
  and still cheat on real jobs.
- **No answer quorum:** free text differs between machines, so two nodes cannot simply be compared.
- **Shared token:** one secret per pool. Use only with machines you trust.
- **Not built:** Steam Inventory grants, model signing and download, hardware checks. (Volunteers serve several gateway machines by listing them all in `--gateway`; see [gateway.md](gateway.md#running-more-than-one-gateway-process).)

## Linux

Gateway and agent are plain Python. Docker, compose, vLLM and systemd files are in `deploy/` and `config.vllm.json`; all
were run on Ubuntu 22.04 with an NVIDIA A10 (see [status.md](status.md)). To serve from vLLM: `vllm serve Qwen/Qwen3-1.7B` and
point a node at it, with `{"chat_template_kwargs": {"enable_thinking": false}}` in its `extra`. `llama-server` works the same
way (`ghcr.io/ggml-org/llama.cpp:server-cuda` with `--jinja`). The agent's busy check reads NVIDIA load with `nvidia-smi`.

## macOS (Apple Silicon)

Install Ollama (uses Metal), `ollama pull qwen3:1.7b`, run the agent. Unified memory means no separate VRAM; the 1 to 2
GB budget applies to RAM. An 8 GB Mac should run only the 1.7B model. See DESIGN.md section 19.1. Untested on a real
Mac.

## Windows

Ollama or `llama-server` with the official Windows builds; no WSL needed. All development and measurement so far was
done on Windows with the CPU.
 