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
| `tests/test_gateway.py` | 17 self-checks, no GPU or network needed |

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
- Tested with a real model only on CPU through Ollama (qwen3:1.7b). No GPU, vLLM or llama-server run yet.
- Nodes are the paid floor only. No volunteer node, no verification or credits.

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE). Free for personal use, research, study, hobby projects and other
noncommercial purposes. **Commercial use, including shipping it inside a paid or monetised game or running
it as a paid service, needs a separate commercial licence from the licensor.** This is source-available,
not open source by the OSI definition.
