# Anansi: Phase 1 floor MVP

Plans: [DESIGN.md](DESIGN.md), [BUSINESS_PLAN.md](BUSINESS_PLAN.md). This folder is the first code.

| Path | What |
|---|---|
| `gateway/app.py` | OpenAI-compatible `/v1/chat/completions`: title-key and Steam-ticket auth, daily token budget per account, field whitelist, system prefix, constrained NPC actions, output filter, failover |
| `gateway/scheduler.py` | Bounded-load rendezvous affinity, power-of-two choices, peak-EWMA, ejection, panic mode |
| `tools/mock_node.py` | Fake GPU node for development |
| `sdk/anansi_client.py` | Python reference SDK with local fallback (the Unity/Unreal plugins follow this contract) |
| `tests/test_gateway.py` | 8 self-checks, no GPU or network needed |

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

Real nodes: point `nodes[].url` in the config at any OpenAI-compatible server, for example vLLM on
Linux (`vllm serve Qwen/Qwen3-8B`) or `llama-server` on Windows. Set `model` names to match.

## Production switches

- `steam.mode`: set `"web"` and export `STEAM_PUBLISHER_KEY`. `"dev"` accepts `dev:<id>` tickets and must never be used in production.
- `ANANSI_ADMIN_TOKEN` enables `GET /admin/nodes` (node load and ejection state). Unset means the route returns 404.
- Change every `titles.*.key`. Put the gateway behind TLS (a reverse proxy or load balancer).

## Known limits (deliberate, see `shortcut:` notes in code)

- Non-streaming only. The output filter needs the full reply.
- Filter is a per-title regex blocklist plus a length cap. It is **not** the safety classifier gate G5 requires.
- Caches and budgets are in process memory. Use Redis before running two gateways.
- Two fixed attempts per request, no retry budget, no hedging.
- Live Steam ticket verification is untested (needs a publisher key). The `Steam Web API` call follows its documented shape [verify].
- No Unity or C# SDK yet (no .NET toolchain here). Nodes are the paid floor only. No volunteer node, no verification or credits.
