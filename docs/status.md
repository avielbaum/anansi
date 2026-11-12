# Status

Phase 1 prototype. All numbers below are from one Windows PC with no GPU, running Qwen3 models through Ollama on the
CPU. They show the system works; they are not performance claims.

## Measured

| Result | Detail |
|---|---|
| End to end with a real model | 21 of 21 requests succeeded, including JSON-schema-constrained ones; constrained output always valid |
| CPU latency (Qwen3-1.7B) | about 2 s for a one-sentence reply, 3 to 5 s for longer ones. A GPU will differ |
| Action accuracy | 33% with a generic prompt, 83% once the prompt said when each action applies (18 self-written cases, so optimistic) |
| Prompt leaks | The word-overlap guard blocked 1 of 8 extraction attacks (verbatim quote). Paraphrases pass |
| Safety judge, Qwen3-1.7B | blocked 0 of 8 leak attacks |
| Safety judge, Qwen3-4B | blocked 3 of 8 (4 of 8 with the overlap guard), 0 false positives on 18 benign cases; median latency 4.3 s to 8.6 s |
| Quest generation, Qwen3-1.7B (CPU) | 6 of 6 structurally valid, every target an id from the supplied world, p50 33 s. All 6 rewards were `medium`; no repeated steps; step text named its target in 18 of 18 steps. Earlier samples showed text drifting from the step's target, which that check cannot see |
| Quest generation, Qwen3-4B (CPU) | 6 of 6 valid, p50 65 s (twice as slow). Rewards varied (2 small, 4 medium); step text named its target in 16 of 17 steps; the writing reads more vividly, with in-character dialogue. Nobody has rated either model's writing |
| Output safety on 23 self-written pairs | Llama Guard 3 1B: 9 of 9 content violations, 0 of 10 false positives, 3.0 s, misses prompt leaks and AI mentions. Qwen3-4B judge: 10 of 13, 0 false positives, 4.4 s. Overlap guard: both leaks. Combined: 13 of 13 |
| Streaming | first sentence arrived before the second in a real run; one CPU sample, no conclusion about GPUs |

Findings that changed the code: the dialogue length cap silently cut quest JSON in half (every quest failed until quests got their own cap); Qwen3 thinking mode returned empty replies (now turned off per node and empty replies
count as failures); a cumulative retry counter starved retries after an outage (now decayed); a 4B judge rambled
instead of answering until its verdict was constrained by JSON schema.

## Tested where

| Area | Windows (this PC) | Ubuntu (CI) | macOS arm64 (CI) |
|---|---|---|---|
| Gateway and agent self-checks (37) | yes | yes | yes |
| C# SDK against a live gateway | yes | yes | no |
| JavaScript SDK against a live gateway (`node sdk/js/test.mjs`) | yes | yes (CI) | no |
| Real model through Ollama | yes (CPU) | no | no |
| Docker, vLLM, systemd files | n/a | no | n/a |

## Known limits

- **No GPU runs.** vLLM, `llama-server` and Docker files are unrun; latency under GPU load is unknown.
- **Live platform identity checks are untested.** Only Steam is written (it needs a publisher key and follows the documented shape); other platforms need a check added.
- **Safety is partial.** Regex blocklist, word-overlap leak guard and an optional judge. No trained classifier, no
  red-team set; paraphrased leaks get through. The judge does not run on streams.
- **Streaming:** plain replies only; a bad sentence mid-stream cuts the stream off.
- **State:** budgets, bans and the work ledger persist in SQLite (`db_path`), tested across a simulated restart. The token cache and node registry are in memory, and SQLite means one gateway process.
- **Volunteer nodes:** shared token, ban by self-chosen id, probes can be recognised, no quorum, no credit value or redemption, no model
  signing. Trust only your own machines.
- **Unity:** the `JsonUtility` path, a real Unity project and structured actions from C# have not been run. The Unreal plugin (`sdk/unreal`) and the Godot addon (`sdk/godot`) are written to the same contract but have never been compiled or run; treat them as drafts until someone builds them in the engine.
- **Eval sets are small and self-written:** 18 action cases and 8 leak attacks. Gate G1 needs about 200 prompts.
- **Gates not passed:** the external gates in DESIGN.md section 22.2 (Valve's position on AI-generated content, studio
  interviews, legal review) are untouched.

## Next

Credits and accounting for volunteers; a GPU run once hardware is available; a real safety classifier and red-team set;
Redis-backed state; a live Steam token check with a publisher key, and checks for other platforms; a Unity project test.
