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

By default the agent pauses while the machine is busy: CPU above 60 percent (measured over half a second from the system's CPU counters)
or any GPU above 60 percent. GPU load comes from `nvidia-smi` for NVIDIA anywhere; on Windows, from the system's GPU engine
counters (the ones Task Manager shows), which cover every vendor; on Linux, from the amdgpu driver for AMD; on Macs, from
`ioreg`. The highest reading wins. While paused it does not register or poll, so no job reaches it; the gateway
forgets it within about `pull_ttl_s` seconds and it registers again (and passes the entry check again) when the machine is
idle. Change the limits with `--cpu-limit` and `--gpu-limit`, or serve regardless with `--ignore-load`. Load in the 5 seconds
after the agent's own job is ignored, and a job queued just before a pause waits for the gateway's timeout and is retried on
another node. Not measured: Intel GPUs on Linux (only the CPU counts there). Tested: the Windows counters on a PC with an Intel and an
NVIDIA GPU (the Intel one rose under a WebGL load); the Mac readers on a Mac mini (Apple M6, 16 GB, macOS 27): `ioreg` gives the GPU's "Device Utilization %" without root (0 at idle), and the CPU check reads 1.0 with all 12 cores
busy and 0.0 five seconds after the agent's own work ends. (It used to read the 1-minute load average on Linux and macOS, which still
showed 0.87 five seconds after 90 s of CPU jobs, so a CPU-only node paused itself for its own work.) the Linux NVIDIA reader on a real A10; the AMD reader only against sample output.

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

### Anonymous network statistics (telemetry)

A public page of statistics about the volunteer network: which hardware serves how many tokens and how busy its owners keep it.
`GET /leaderboard` (a small web page; `?period=day|week|all`) and `GET /v1/leaderboard` (JSON), cached for 30 seconds. It is anonymous by
design: **no names, no accounts, no machine ids, no per-machine rows**. What is collected, what is published and how anonymous that
really is are in [privacy.md](privacy.md); what a volunteer agrees to is in [volunteer-terms.md](volunteer-terms.md) (both are drafts
for counsel).

- **A machine takes part** only with `python node/agent.py ... --telemetry` (or the same flag on `join`). It then reports its CPU model,
  GPU models with video memory, a coarse operating system name ("Windows 10", "Linux", "macOS") and the GPU load sampled every
  30 seconds while none of this agent's own jobs run, sent every 5 minutes. There is **no name option**, and nothing else is read: no
  hostname, user name, address, serial number, driver version or thread count. **At every start the agent says exactly what it sends
  and to which gateway**; `--telemetry-show` prints the exact report and sends nothing; `--telemetry-off` deletes what it reported. It
  **refuses a plain `http://` gateway on another machine** (the report would cross the network unencrypted).
- **What is published.** Machines are grouped by graphics card (model and memory), processor model and operating system, with the
  machines, tokens served and typical idle GPU load of each group, most tokens first, plus totals for the network. **A group is shown only
  if it has at least `min_group` machines** (default 5); smaller groups are folded into "Other" when together they reach `min_group`
  and are otherwise left out. **Until `min_group` machines report, nothing is published, not even a count.** A machine is counted once,
  under its graphics card with the most memory.
- **The idle GPU figure is a slow average**, not a live reading: the gateway keeps 97 percent of the old value and 3 percent of each
  report (hours at one report per 5 minutes), and a group shows the mean of its machines as a whole percent, so the page cannot reveal
  when anyone is playing.
- **What is stored.** Only the latest report of each machine, under its random agent id, for 2 days at most (`--telemetry-off` deletes
  it at once). That is pseudonymous, not anonymous, inside the operator's database: see [privacy.md](privacy.md).
- **What is trusted.** Tokens are measured by the gateway (real jobs only, probes excluded, a claim is capped by the size of the
  text), so they cannot be inflated. Hardware and idle load are **reported by the machine and not verified**; the page says so. A
  machine can only report if it has registered or served a job, at most once per 20 seconds, 16 KB each, and a banned machine is not counted.
- **Hostile text.** Hardware names come from outside and appear on a public page: control, zero-width and right-to-left override
  characters are removed, lengths capped (CPU and GPU 80, at most 8 GPUs), a group needs `min_group` machines reporting the very same text,
  and the page escapes everything. The operator can hide hardware by pattern (`leaderboard.hidden_hardware`).
- **What the page tells browsers.** No scripts (`default-src 'none'`), no framing (`frame-ancestors 'none'`), `noindex, nofollow` (header
  and meta tag), a privacy link when `leaderboard.privacy_url` is set. If you show the JSON in your own UI, escape the names.
- **The operator's settings** (config block `leaderboard`, see [gateway.md](gateway.md#leaderboard)): `enabled: false` removes the page
  and refuses reports; `min_group` (a larger number is more anonymous; 1 publishes single machines and is for testing only);
  `hidden_hardware`; `privacy_url`.
- **Tested.** The hardware readers have run on a real Windows PC (CPU, an Intel and an NVIDIA GPU, idle GPU load) and the whole flow
  (real agent, real gateway, real local model, the page in a browser, the opt-out, and a database left by an earlier design losing its
  name tables) on that PC. The Linux NVIDIA reader uses `nvidia-smi`, the same command the busy check has run on a real A10; the AMD (sysfs)
  reader follows the documented format and is tested on sample output only; the macOS reader ran on a Mac mini (Apple M6, 16 GB, macOS 27) and reported
  "Apple M6" with no separate video memory (Apple GPUs share the system memory), so its statistics label has no GB. Each privacy control (the
  minimum group, the "Other" rule, hidden hardware, the report limits, the https refusal, the slow average, the 2-day retention, the
  headers) has a self-check that fails when the control is removed. Not built: a verified hardware check (compare reported GPU against
  measured tokens per second), history over time, and a stored report that cannot be linked to the ledger.

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
GB budget applies to RAM. An 8 GB Mac should run only the 1.7B model. See DESIGN.md section 19.1. On a Mac mini (Apple M6, 16 GB, macOS 27) the gateway self-checks and the hardware readers pass; Ollama and a real model have not been run on a Mac yet.

## Windows

Ollama or `llama-server` with the official Windows builds; no WSL needed. All development and measurement so far was
done on Windows with the CPU.
 