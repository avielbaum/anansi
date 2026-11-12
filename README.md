<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="assets/logo/anansi-logo-light.svg">
    <img src="assets/logo/anansi-logo.svg" alt="Anansi: story and quest engine" width="260">
  </picture>
</h1>

<p align="center"><b>One endpoint for living game worlds: NPC dialogue, quests and storylines, powered by idle GPUs.</b></p>

<p align="center">
  <a href="https://github.com/avielbaum/anansi/actions/workflows/ci.yml"><img src="https://github.com/avielbaum/anansi/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/status-phase%201%20prototype-orange" alt="Status: Phase 1 prototype">
  <img src="https://img.shields.io/badge/licence-PolyForm%20Noncommercial-blue" alt="Licence: PolyForm Noncommercial 1.0.0">
</p>

<p align="center">
  <a href="docs/quickstart.md"><b>Quick start</b></a> ·
  <a href="docs/gateway.md"><b>Gateway</b></a> ·
  <a href="docs/nodes.md"><b>Nodes</b></a> ·
  <a href="docs/sdk.md"><b>SDKs</b></a> ·
  <a href="docs/status.md"><b>Status</b></a> ·
  <a href="DESIGN.md"><b>Design</b></a>
</p>

**Generative game content without the token bill.** Anansi is an "LLM@home" service that works with any game platform. A game calls one
OpenAI-compatible gateway; behind it sits a pool of small language models running on a paid cloud floor and,
later, on the idle GPUs of players who volunteer, in the spirit of Folding@home. The gateway is built for games:
dialogue, quests and storylines built only from the characters, places and items your game supplies, whitelisted NPC actions the model cannot get wrong, per-player daily budgets, sentence-by-sentence streaming,
output filtering and a local fallback so the game always gets an answer.

```
$ curl -s localhost:8080/v1/npc -H "X-Anansi-Title: demo" -H "X-Anansi-Key: change-me" \
       -H "X-Player-Token: dev:player-1" \
       -d '{"messages":[{"role":"user","content":"Could I have a discount? I am buying five potions."}],
            "npc_id":"shopkeeper","structured":true}'
{"say":"Five potions? Fine, I can knock a little off.","action":"give_discount","filtered":false,"node":"http://127.0.0.1:11434"}
```

<sub>Illustrative output: the wording varies by model, and a 1.7B model picks the right action about 4 times in 5 on my small test set.</sub>

`action` is always one of the actions your game allows (or `none`): the model's output is constrained to that list,
and the gateway checks it again before the reply leaves.

## Why Anansi

In the folklore of the Akan people of Ghana, Anansi is the spider, a trickster and the keeper of stories and wisdom.
The tale goes that all the stories once belonged to Nyame, the sky god. Anansi, small and without any strength to
speak of, won them by cleverness, by completing tasks that seemed impossible, and carried them down to people.

This project borrows the shape of that myth:

- **Stories are the product.** Dialogue, quests and storylines for game worlds, generated on demand.
- **Cleverness over strength.** Instead of one giant, expensive model, many small models do the work, on hardware that
  is otherwise idle.
- **The web.** A spider's web is many threads that hold together even when one breaks. Anansi's mesh of cloud and
  volunteer nodes is built the same way: nodes come and go, the scheduler routes around the ones that fail, and
  the game sees one thread, a single endpoint.

## How it works

```
 game (Unity / Unreal / Godot / any HTTP client)
        |  one request: messages, npc_id, structured
        v
 +------------------------ gateway -----------------------+
 | auth (title key + player token) -> daily budget         |
 | -> system prefix, field whitelist, constrained actions  |
 | -> scheduler: affinity, power-of-two, failover          |
 | -> output filter, leak guard, optional safety judge     |
 +---------+------------------+----------------------+-----+
           |                  |                      |
      cloud floor        volunteer PC            volunteer Mac
      (vLLM, Ollama)     (node/agent.py,         (node/agent.py,
                          connects OUT)           Ollama on Metal)
```

Volunteer machines never open a port: the agent connects out to the gateway and polls for work, so it runs behind
home routers. A new node must answer a known-answer probe before it receives real traffic, and live nodes are
spot-checked afterwards.

## What works today

Measured on one Windows PC with no GPU, running Qwen3-1.7B and 4B through Ollama on the CPU. See
[docs/status.md](docs/status.md) for numbers and caveats.

| | |
|---|---|
| Gateway: auth, budgets, constrained actions, filter, leak guard, failover, streaming | working, 40 self-checks |
| Quest and storyline generation (`/v1/quest`, `/v1/storyline`) with Python and C# SDK methods | working: constrained to your game's own ids; 6 of 6 structurally valid with Qwen3-1.7B (33 s) and Qwen3-4B (65 s, more varied rewards and richer text) on CPU; writing quality unrated |
| Real model end to end (Ollama, Qwen3-1.7B on CPU) | working: 21 of 21 requests, action accuracy 83% on 18 self-written cases |
| Safety judge (second model call) | working with Qwen3-4B: blocked 3 of 8 leak attacks, no false positives; doubles latency |
| Volunteer node agent, entry probe, spot checks, bans; one-step `join` setup | working in tests and with Ollama; no idle detection yet |
| Layered output safety: overlap guard, Llama Guard classifier, judge model | working; on 23 self-written pairs the combination caught all violations with no false positives, about 7.5 s extra on CPU |
| Python and C# SDKs with sentence streaming and local fallback | working (C# as plain .NET; Unity untested) |
| JavaScript / TypeScript SDK (browsers, Node, Electron, Deno, Bun) | working: 11 checks against a live gateway in CI; for browsers on another origin list them in `cors_origins` |
| Red-team set for gate G5 (759 prompts, dev/test split, runner) | built; first dev run: 5 of 216 automatic failures after fixes; **G5 not passed** |
| Unreal Engine 5 plugin (C++, Blueprint-callable) and Godot 4 addon (GDScript) | **written, never compiled or run: no Unreal or Godot install was available** |
| Linux | gateway and C# SDK tested in CI on Ubuntu; Docker, vLLM and systemd files written but never run |
| macOS Apple Silicon | gateway tests pass on a CI arm64 runner; no real Mac, no real model |
| **GPU nodes** (vLLM, llama-server) | **not tested, no GPU available** |
| **Live platform identity check** (Steam is the only one written) | **not tested, needs a Steam publisher key** |
| Persistence (budgets, bans) and a volunteer work ledger in SQLite | working, tested across a restart; credit value and redemption not decided |
| Model signing, per-user node identity, answer quorum | not built |

## Quick start

Needs Python 3.10 or newer. For a real model, install [Ollama](https://ollama.com) as well.

```bash
git clone https://github.com/avielbaum/anansi
cd anansi
pip install -r requirements.txt
python tests/test_gateway.py          # 40 self-checks, no GPU or network needed
```

Run the gateway against a local model:

```bash
ollama pull qwen3:1.7b
ANANSI_CONFIG=config.ollama.json python -m uvicorn gateway.app:make_app --factory --port 8080
python tools/eval.py --key change-me --cases evals/shopkeeper.jsonl     # in a second terminal
```

No model installed? Use the mock nodes: [docs/quickstart.md](docs/quickstart.md).

## Documentation

| | |
|---|---|
| [Quick start](docs/quickstart.md) | Mock nodes, Ollama, Linux, macOS, running the tests |
| [Gateway](docs/gateway.md) | Config reference, endpoints, streaming, filter, leak guard, safety judge, production switches |
| [Nodes](docs/nodes.md) | Cloud nodes, volunteer agent, verification, Linux and macOS notes |
| [SDKs](docs/sdk.md) | Python, C# (Unity), JavaScript/TypeScript, Unreal and Godot clients and their fallback behaviour |
| [Status](docs/status.md) | Measured results, known limits, what is untested |
| [DESIGN.md](DESIGN.md) | Architecture, security model, roadmap and go/no-go gates |

## Repository layout

| Path | What |
|---|---|
| `gateway/` | The gateway (`app.py`), node scheduler (`scheduler.py`), pull-node hub (`pull.py`) |
| `node/agent.py` | Volunteer node agent |
| `sdk/` | Python client; C# client for Unity and .NET, with a cross-platform CI test; JavaScript/TypeScript client (`sdk/js`); Unreal plugin (`sdk/unreal`); Godot addon (`sdk/godot`) |
| `tools/` | Mock node, load test, action-accuracy eval, prompt-leak eval |
| `evals/` | Labelled test prompts |
| `tests/` | Self-checks |
| `deploy/`, `config.*.json` | Dockerfile, compose file, systemd unit, example configs |

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE). Free for personal use, research, study, hobby projects and other
noncommercial purposes. **Commercial use, including shipping it inside a paid or monetised game or running it as a
paid service, needs a separate commercial licence from the licensor.** This is source-available, not open source by
the OSI definition.
