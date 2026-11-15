# Quick start

Python 3.10 or newer. Works the same on Windows, Linux and macOS.

```bash
pip install -r requirements.txt
python tests/test_gateway.py
```

## With mock nodes (no model needed)

Three terminals:

```bash
python tools/mock_node.py 9001 node-a
python tools/mock_node.py 9002 node-b
ANANSI_CONFIG=config.example.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

Then, in a fourth:

```bash
python tools/loadtest.py --help
```

## With a real model (Ollama)

```bash
ollama pull qwen3:1.7b
ollama pull qwen3:4b-instruct    # confirms each action the NPC picks; without it no action is ever taken
ANANSI_CONFIG=config.ollama.json python -m uvicorn gateway.app:make_app --factory --port 8080
python tools/eval.py --key change-me --cases evals/g1_shopkeeper.jsonl --split test   # 106 held-out action cases
python tools/leak_eval.py --key change-me
```

For gate G1's blind rating, save two models' replies with `--out`, then
`python tools/blind_pack.py pack small.jsonl large.jsonl --sheet rate.csv --key key.json`. Someone rates the sheet without
seeing the key, and `python tools/blind_pack.py score rate.csv key.json` gives each model's acceptable rate.

`config.ollama.json` turns Qwen3's thinking mode off for the node. Without that, Qwen3 can spend the whole token
budget on reasoning and return an empty reply. It also uses `qwen3:4b-instruct` as an `action_check`: a second model that confirms each
discount or guard call against the player's line, in any language (keyword `action_gates`, the no-extra-model option, missed most threats
phrased unlike the G1 cases). To add the optional safety judge as well, use `config.ollama.judge.json`. Not `qwen3:4b`: that Ollama tag is now a thinking-only model.

## Linux

The gateway is plain Python. CI runs the self-checks and the C# SDK against a live gateway on Ubuntu.

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
ANANSI_CONFIG=config.example.json python -m uvicorn gateway.app:make_app --factory --port 8080
```

Deployment files (`deploy/Dockerfile`, `deploy/docker-compose.yml`, `config.vllm.json`,
`deploy/anansi-gateway.service`) have been run on Ubuntu 22.04 with an NVIDIA A10 (Docker 29, vLLM 0.33, the NVIDIA
container toolkit). The compose file uses `vllm/vllm-openai:latest`: pin the version you tested in production. Set
`ANANSI_ENV=dev` to try it with the example key; production mode refuses it on purpose.

## macOS (Apple Silicon)

Nothing in the gateway or agent depends on the platform. Install Ollama (it uses Metal), pull a model and use the
Ollama steps above. Untested on macOS: no Mac hardware is available. Memory guidance is in [DESIGN.md section 19.1](../DESIGN.md).

## C# SDK test

```bash
dotnet run --project sdk/unity/ci          # any OS, needs a gateway on 127.0.0.1:8080 backed by the mock nodes
powershell -File sdk\unity\test_sdk.ps1    # Windows PowerShell: starts everything itself
```
 