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

To the scheduler a registered worker is an ordinary node, so routing, failover, ejection and the retry budget apply.
A worker that stops polling is forgotten after `pull_ttl_s`. A streamed request is answered correctly but relayed
whole after the node finishes.

### Verification

- **Entry probe:** a new worker joins the pool only after answering a known-answer question correctly (temperature 0,
  answer matched by regex). Built-in questions are used unless `canaries` (list of `{"user", "expect"}`) is set.
- **Spot checks:** after real jobs, with probability `canary_rate` (default 0.05), the same node is probed again.
- **Bans:** a failed entry probe, or two failed spot checks, bans the agent id. Each agent keeps a random id in
  `~/.anansi-agent-id`. Timeouts and error replies are not strikes; the scheduler's ejection handles those.
- `GET /admin/stats` shows `pull.probes`, `probe_failures`, `banned`.

### What this does not give you

- **No real identity:** the ban is by a self-chosen id, so a banned operator can mint a new one. Real identity needs the
  Steam-bound certificates of DESIGN.md section 9.
- **Probes can be recognised:** a node that spots the probe (no system prompt, a few fixed questions) can pass them
  and still cheat on real jobs.
- **No answer quorum:** free text differs between machines, so two nodes cannot simply be compared.
- **Shared token:** one secret per pool. Use only with machines you trust.
- **Not built:** credits, model signing and download, hardware checks, more than one gateway.

## Linux

Gateway and agent are plain Python. Docker, compose, vLLM and systemd files are in `deploy/` and `config.vllm.json`;
they have not been run. To serve from vLLM: `vllm serve Qwen/Qwen3-1.7B` and point a node at it.

## macOS (Apple Silicon)

Install Ollama (uses Metal), `ollama pull qwen3:1.7b`, run the agent. Unified memory means no separate VRAM; the 1 to 2
GB budget applies to RAM. An 8 GB Mac should run only the 1.7B model. See DESIGN.md section 19.1. Untested on a real
Mac.

## Windows

Ollama or `llama-server` with the official Windows builds; no WSL needed. All development and measurement so far was
done on Windows with the CPU.
 