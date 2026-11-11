# Gateway

`gateway/app.py`: an OpenAI-compatible `POST /v1/chat/completions` plus a flat `POST /v1/npc` for game SDKs.

## Requests

Headers on every request: `X-Anansi-Title`, `X-Anansi-Key` (the studio's key) and `X-Steam-Ticket`.

| Route | Use |
|---|---|
| `POST /v1/chat/completions` | OpenAI shape. Extras go in an `anansi` object: `npc_id` (keeps one NPC on one node), `structured` (constrained actions). `"stream": true` for sentence streaming (plain replies only). |
| `POST /v1/npc` | Flat shape for Unity's `JsonUtility`: send `messages`, `npc_id`, `structured`; get `say`, `action`, `filtered`, `node`. No streaming. |
| `GET /healthz` | Liveness. |
| `GET /admin/nodes`, `GET /admin/stats` | Node load and ejection state; status counts, retries, filter hits, p50/p95/p99, pull-node probe counts. Header `X-Admin-Token`; 404 unless `ANANSI_ADMIN_TOKEN` is set. |

Only `model`, `messages`, `temperature` and `top_p` are forwarded to nodes. `max_tokens` is clamped to the title's
limit. Everything else (`guided_regex`, `logit_bias`, ...) is dropped.

## Config reference

JSON file named by `ANANSI_CONFIG`.

| Key | Meaning |
|---|---|
| `default_model` | Logical model name when a request names none |
| `upstream_timeout_s` | Per-attempt timeout to a node (default 20) |
| `steam.mode` | `"dev"` accepts tickets like `dev:<steamid>` (never in production); `"web"` checks the Steam Web API with `STEAM_PUBLISHER_KEY` |
| `nodes[]` | Static nodes: `url`, `models` (logical names), `region`, `upstream_model` (the server's own name), `extra` (merged into every request, e.g. to switch thinking off) |
| `titles.<id>` | One entry per game, see below |
| `pull_tokens` | Enables volunteer agents; see [nodes.md](nodes.md) |
| `pull_poll_s`, `pull_ttl_s`, `canaries`, `canary_rate` | Pull-node tuning and verification; see [nodes.md](nodes.md) |

Per title: `key`, `appid`, `system_prefix` (prepended to every request), `actions` (the allowed NPC actions),
`blocklist` (regexes), `fallback_line`, `max_tokens`, `max_prompt_chars`, `max_reply_chars`, `daily_token_budget`
(per Steam account, per UTC day; exceeded gives `429` with `Retry-After`), `leak_ngram` (default 5), `judge`.

Qwen3 thinks by default and can return an empty reply. Turn thinking off in the node's `extra` (Ollama:
`{"reasoning_effort": "none"}`; vLLM: `{"chat_template_kwargs": {"enable_thinking": false}}`, unverified). An empty
reply counts as a node failure and the gateway retries elsewhere.

## Constrained actions

With `"structured": true`, the node is asked for JSON `{"say", "action"}` under a JSON schema whose `action` is one of
the title's `actions` or `none`. The gateway re-validates: an unlisted action becomes `none`, malformed JSON becomes
the fallback line.

## Streaming

`"stream": true` returns Server-Sent Events, one finished sentence per chunk, each checked before it is sent.
Failover happens only before the first sentence. A bad sentence mid-reply ends the stream there (sent sentences cannot
be recalled). A stream that cannot start carries `{"error": ...}` so the SDK can fall back. Structured requests are
not streamed (400). The safety judge does not run on streams. For streams, recorded latency is time to first sentence.

## Output safety

1. **Blocklist and length cap:** per-title regexes and `max_reply_chars`. A hit replaces the reply with `fallback_line`.
2. **Leak guard:** a reply that repeats `leak_ngram` (default 5) or more consecutive words of the system prompt gets
   the fallback line. It catches near-verbatim leaks, not paraphrases.
3. **Safety judge (optional):** `"judge": {"model": "...", "prompt": "..."}`. A second model call, shown the secret
   prompt, must answer `SAFE` for a non-streamed reply to go out. `UNSAFE`, a garbled answer or no answer gives the
   fallback line. The verdict is constrained to two values by JSON schema. Use a model of 4B or more; 1.7B caught nothing.
   `config.ollama.judge.json` shows a separate logical model (`judge`) served by `qwen3:4b`.

None of these is the safety classifier that gate G5 in DESIGN.md requires.

## Routing

Same NPC goes to the same node (bounded-load rendezvous hashing); otherwise power-of-two choices on load and
peak-EWMA latency. Three consecutive failures eject a node with doubling back-off (30 s to 5 min); if every node is
ejected the gateway still tries them (panic mode). Retries are capped near 10% of recent traffic, three attempts per
request.

## Production switches

- Set `steam.mode` to `"web"` and export `STEAM_PUBLISHER_KEY`.
- Change every `titles.*.key`; set `ANANSI_ADMIN_TOKEN`.
- Put the gateway behind TLS (reverse proxy or load balancer).
- Caches and budgets live in process memory. Move them to Redis before running two gateways.
