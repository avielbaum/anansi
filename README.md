# Anansi: Phase 1 floor MVP

Anansi is a Steam-first, "LLM@home" service: one OpenAI-compatible gateway that gives game studios generative NPC
dialogue and actions without per-token costs, served by a paid cloud floor now and volunteer GPUs later.

Design and roadmap: [DESIGN.md](DESIGN.md). **Status: Phase 1 prototype.** The gateway runs end to end against a real
model (Qwen3-1.7B via Ollama on CPU). There are no GPU nodes, volunteer nodes or live Steam checks yet; see Known limits.

| Path | What |
|---|---|
| `gateway/app.py` | OpenAI-compatible `/v1/chat/completions`: title-key and Steam-ticket auth, daily token budget per account, field whitelist, system prefix, constrained NPC actions, output filter, leak guard, sentence-by-sentence streaming, failover |
| `gateway/scheduler.py` | Bounded-load rendezvous affinity, power-of-two choices, peak-EWMA, ejection, panic mode |
| `tools/mock_node.py` | Fake GPU node for development |
| `sdk/anansi_client.py` | Python reference SDK: `chat()` and sentence-by-sentence `chat_stream()`, both with local fallback (the Unreal plugin would follow this contract) |
| `sdk/unity/Anansi.cs` | C# SDK for Unity and plain .NET: `Client.ChatAsync(...)` and `StreamAsync(messages, onSentence)` with local fallback. Test: `powershell -File sdk\unity\test_sdk.ps1` |
| `POST /v1/npc` | Flat request and reply shape for game SDKs (`say`, `action`, `filtered`, `node`), next to the OpenAI-style route |
| `tools/loadtest.py` | Closed-loop load test: client-side p50/p95/p99 latency, status counts, per-node spread |
| `tools/eval.py`, `evals/shopkeeper.jsonl` | Quality check (gate G1): labelled prompts through `/v1/npc`, scores the chosen action. 18 starter cases |
| `tools/leak_eval.py`, `evals/leak.jsonl` | Prompt-extraction attacks through the gateway; shows which leaks the guard blocks and which get through |
| `tests/test_gateway.py` | 19 self-checks, no GPU or network needed |

## Run

```bash
pip install fastapi uvicorn httpx
python tests/test_gateway.py
```

Local demo, three terminals:

```bash
python tools/mock_node.py 9001 node-a
python tools/mock_node.py 9002 node-b
ANANSI_CONFIG=config.example.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

Real nodes: point `nodes[].url` at any OpenAI-compatible server (vLLM on Linux, `llama-server` or Ollama on
Windows). Per node, `upstream_model` maps our logical model name to the server's name and `extra` is merged
into every request. **Qwen3 models think by default and can spend the whole token budget on reasoning, which
returns an empty reply**: switch thinking off in `extra` (Ollama: `{"reasoning_effort": "none"}`; vLLM:
`{"chat_template_kwargs": {"enable_thinking": false}}` [verify]). The gateway treats an empty reply as a node
failure and retries elsewhere. Try it with Ollama and `config.ollama.json`:

```bash
ollama pull qwen3:1.7b
ANANSI_CONFIG=config.ollama.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

## Volunteer (pull) nodes

`node/agent.py` runs on a volunteer PC and connects **out** to the gateway (no open port, works behind NAT). It polls for jobs and runs them on a local OpenAI-compatible server (Ollama, llama-server, vLLM). The gateway treats each registered worker as a normal node, so routing, failover and ejection apply. Enable it with `pull_tokens` in the gateway config (`config.pull.example.json`: a token maps to the models, `upstream_model` and `extra` the gateway sends that worker) and run:

```bash
python node/agent.py --gateway http://127.0.0.1:8080 --token change-me-node-token --local http://127.0.0.1:11434 --slots 2
```

Verification: a new worker only joins the pool after answering a known-answer probe correctly (`canaries` in the config, a few built-in questions by default). Live workers are spot-checked after real jobs (`canary_rate`, default 5%). A failed entry probe, or two failed spot checks, bans the agent id (`/admin/stats` shows `pull.probes`, `probe_failures`, `banned`). Each agent keeps a random id in `~/.anansi-agent-id`.

Tested: in the self-checks (register, serve, stream, auth, expiry of silent workers, a lying node refused at entry, an honest node banned after going bad) and end to end with Ollama on this PC. **Limits**: the ban is by a self-chosen id, so someone can mint a new one (real identity needs the Steam-bound certificates of DESIGN.md section 9); a node that recognises probes (no system prompt, a few fixed questions) can pass them and cheat on real jobs; there is no quorum on real answers because free text differs between machines; no credits, model signing or hardware checks. The token is still a shared secret, so use it only with machines you trust. Streams from pull nodes are correct but relayed whole after the node finishes.

## macOS (Apple Silicon)

Nothing in the gateway or `node/agent.py` is platform specific. On an M1/M2 or later Mac, install Ollama (it uses Metal), `ollama pull qwen3:1.7b`, and run the agent as above. The self-checks run on a macOS arm64 runner in CI. **Not tested on a real Mac**: model speed, memory pressure beside a game, thermals. Memory guidance (unified memory, 8 GB machines get the Lite model only) is in DESIGN.md section 19.1.

## Linux

The gateway is plain Python, so it runs the same on Linux. **Verified by CI on Ubuntu** (`.github/workflows/ci.yml`): the 19 self-checks and the C# SDK against a live gateway (`dotnet run --project sdk/unity/ci`) pass there.

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
ANANSI_CONFIG=config.example.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

Deployment files, **written without a Linux or GPU machine and not run**: `deploy/Dockerfile` (gateway image), `deploy/docker-compose.yml` (gateway plus a vLLM node, needs an NVIDIA GPU and the container toolkit), `config.vllm.json` (node settings for vLLM, including turning Qwen3 thinking off [verify]) and `deploy/anansi-gateway.service` (systemd unit, gateway on localhost behind a TLS proxy). Expect to adjust image tags and vLLM flags.

## Production switches

- `steam.mode`: set `"web"` and export `STEAM_PUBLISHER_KEY`. `"dev"` accepts `dev:<id>` tickets and must never be used in production.
- `ANANSI_ADMIN_TOKEN` enables `GET /admin/nodes` (node load and ejection state) and `GET /admin/stats`
  (status counts, retries, filter hits, gateway p50/p95/p99), sent as `X-Admin-Token`. Unset means both return 404.
- Change every `titles.*.key`. Put the gateway behind TLS (a reverse proxy or load balancer).

## Known limits (deliberate, see `shortcut:` notes in code)

- Streaming (`"stream": true`) is for plain replies only, one finished sentence per SSE chunk, each checked before it is sent. Failover happens only before the first sentence goes out; a bad sentence mid-reply cuts the stream off (sent sentences cannot be recalled). Structured actions and `/v1/npc` are returned whole. Both SDKs stream: Python `chat_stream()` (tested against simulated streams) and C# `StreamAsync` (plain .NET against a live gateway; Unity untested).
- Leak guard: a reply repeating 5 or more consecutive words of the system prompt (`leak_ngram` per title) gets the fallback line. It does not catch paraphrases (`tools/leak_eval.py`, `evals/leak.jsonl`).
- Safety judge (optional, `"judge": {"model": ..., "prompt": ...}` per title): a second model call must answer SAFE before a non-streamed reply goes out; anything else gives the fallback line. Not applied to streams. The verdict is constrained to SAFE/UNSAFE by JSON schema (the 4B model rambled without it). On this CPU: Qwen3-1.7B as judge caught 0 of 8 leak attacks; Qwen3-4B caught 3 (plus 1 by the word-overlap guard) with 0 false positives on the 18 shopkeeper cases, but roughly doubled latency (p50 8.6 s). Example: `config.ollama.judge.json`.
- Filter is a per-title regex blocklist plus a length cap. It is **not** the safety classifier gate G5 requires.
- Caches and budgets are in process memory. Use Redis before running two gateways.
- Retries are capped near 10% of traffic (3 attempts max per request). No hedging yet.
- Live Steam ticket verification is untested (needs a publisher key). The `Steam Web API` call follows its documented shape [verify].
- The C# SDK is compiled and tested as plain .NET (Windows PowerShell's C# 5 compiler) against a live gateway. The
  `#if UNITY` JsonUtility branch, a Unity project and the structured-action path from C# have not been run. No Unreal SDK.
- Tested with a real model only on CPU through Ollama (qwen3:1.7b). No GPU, vLLM or llama-server run yet (the vLLM compose file is unrun).
- Volunteer nodes exist in basic form (see above) with no verification or credits.

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE). Free for personal use, research, study, hobby projects and other
noncommercial purposes. **Commercial use, including shipping it inside a paid or monetised game or running
it as a paid service, needs a separate commercial licence from the licensor.** This is source-available,
not open source by the OSI definition.
