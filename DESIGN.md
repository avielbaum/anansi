# Anansi: LLM@home for games, on any platform

**Platforms.** Anansi is platform agnostic. Steam is the reference first platform, so many sections below describe
Steam's identity, distribution (depots), rewards (Inventory) and policy. Read each of those as "the platform's
identity, distribution and rewards services"; Epic, GOG, itch.io, consoles, mobile or a studio's own launcher
need their own equivalent, and the gateway takes a pluggable player-identity check (`auth.mode`). Where a platform
has no equivalent (for example no inventory), credits can be redeemed inside the game instead.

Status: complete design draft v1.0, 2026-11-10. Nothing here has been built or measured.
Assumptions are marked **[verify]**. Repository licences, Windows support and model licences
were checked on 2026-11-10 (sections 17-19). This is not legal advice.

## 0. Decision summary (read this first)

The document grew in layers. Later sections override earlier ones. This summary and the
status table below are the current position.

**What Anansi is.** A platform-agnostic "LLM@home" service (Steam first). Players' idle PCs run a small
language model for a game's generative content, backed by a paid cloud pool, behind one
OpenAI-compatible endpoint that game engines call through an SDK.

**Decisions**

1. **Architecture:** hub-and-spoke like BOINC. A regional gateway, scheduler and controller
   assign work. Nodes only make outbound connections and pull jobs. No DHT. A paid cloud
   "floor" is mandatory, because volunteer supply peaks when demand is low (sections 1, 7).
2. **Node:** a native Windows app that wraps llama.cpp, with Colibri as an optional engine.
   No WSL (sections 19-20).
3. **Footprint:** at most 1-2 GB of VRAM. Profiles are Lite (1.7B), Standard (4B) and the
   opt-in Plus (tiered 35B MoE on Colibri). Quality comes from a per-title LoRA adapter on a
   shared base model, with escalation to the floor for hard requests (section 21).
4. **Work:** pre-generate content as batch units on volunteers with quorum checks, and serve
   live NPC replies from nearby warm nodes or the floor. The SDK falls back to a local model
   (sections 2, 6).
5. **Routing:** LLM-aware scoring (queue, KV use, prefix cache, adapter loaded, title heat),
   power-of-two choices, bounded-load hashing, outlier ejection, retry budgets and
   priority failover (sections 11, 16, 20).
6. **Security:** the goal is integrity and availability, not confidentiality. 24-hour mTLS
   certificates tied to Steam accounts, signed jobs and models, sandboxed workers, canaries,
   quorum, default-deny node firewall, grammar-constrained NPC actions and a gateway output
   filter (sections 12, 15, 16.4).
7. **Sharding across volunteers (Petals-style):** deferred as research. No candidate runs
   natively on Windows, and per-token network hops cost latency. Colibri's cluster mode is for
   the paid floor only (sections 10, 18-20).
8. **Licensing:** the planned components are MIT, Apache-2.0 or BSD. Do not use Consul (BSL).
   Do not embed AI Horde code (AGPL). Ship Apache-2.0 models first (section 17).

**Status of each section**

| Sections | Status |
|---|---|
| 1, 2, 4, 5, 6, 7 | Current. Section 4's privacy bullet is relaxed by section 12. |
| 3 | Current after the corrections below it. |
| 8, 14 | Replaced by the roadmap in section 22. |
| 9 | Tiers replaced by section 21's profiles. T2 is research. |
| 10, 18 | Research only (volunteer sharding). |
| 11, 12, 15, 16, 17 | Current. |
| 13 | Current, but read the T2 cell as optional research. |
| 19 | Current (Windows-native requirement). |
| 20 | Current for the Plus profile. |
| 21 | Governs node sizing. |
| 22 | Roadmap, gates and open decisions. |

## 1. Shape of the system

@home systems (BOINC, Folding@home) are hub-and-spoke, not true P2P. Volunteers pull work
over outbound connections and the project server owns scheduling, verification and credit.
Anansi follows that model. There is no DHT and no inbound ports, so NAT is a non-issue.

```
Game + Anansi SDK ──(platform token, TLS)───────► Gateway ──► Scheduler ──► Work queues
                                                                                  ▲  ▲
                        Anansi Node (desktop app, outbound WebSocket, pull) ────────┘  │
                        Dedicated floor (cloud GPUs, same worker image) ─────────────┘
```

- **Gateway**: OpenAI-compatible API. It authenticates each request with the platform's player
  token plus the studio's key (on Steam, the session ticket and publisher key), enforces quotas, applies the prompt template and runs the
  output safety filter.
- **Scheduler**: matches jobs to nodes by model, RTT, queue depth and reputation.
- **Node**: a free desktop app, on Steam or elsewhere (or an opt-in "Contribute idle GPU" toggle inside a partner game).
  It pulls jobs, runs them with llama.cpp (MIT; CUDA/Vulkan/Metal, works on Windows) and
  returns results. vLLM stays on the Linux dedicated floor only.
- **Dedicated floor**: a small cloud GPU pool in each region that runs the same worker image.
  It is mandatory because volunteer supply is out of phase with demand (see Risks).

## 2. Two job classes (this is what makes @home fit)

| Class | Example | Latency | Where it runs |
|---|---|---|---|
| **Batch work units** | Dialogue banks, quest variants, item lore, NPC backstories, pre-generated per-save content | Minutes to hours | Volunteers, with quorum verification |
| **Interactive** | Live NPC reply to a player | Under about 800 ms to first token | Volunteers that are idle and nearby, otherwise the dedicated floor |

Design games to pre-generate as much as possible. Batch results are cached on a CDN and
served to every player, which cuts interactive load. The interactive path is the exception.

## 3. Node agent

- **Idle policy** (defaults, user-tunable): serve only when no fullscreen game is running,
  GPU utilisation is under 15% for 2 minutes (NVML/ADL), the machine is on AC power, and VRAM
  free is at least the profile's cap plus a margin (section 21). Stop within 1 second of a
  game launching by killing the worker process (section 19).
- **Model**: pinned, hash-verified model files for the chosen profile (Lite, Standard or Plus;
  section 21), shipped through the shared Anansi Runtime Steam app as **depots** so Steam handles
  download, update and CDN **[verify depot size and content rules]**. (Earlier drafts said one
  7-8B model of about 5 GB. That exceeds the VRAM cap.)
- **Sandbox**: the node only executes inference on signed model files. It never runs
  downloaded code. Jobs are data (prompt and params). Run the worker as a low-privilege process
  with no filesystem access beyond the model and a scratch directory.
- **Skip**: Steam Deck as a host. It is weak and battery-bound, so it remains a client.
  Integrated GPUs are not hosts for the Lite and Standard profiles. Colibri's Plus profile
  reported its best speeds on an integrated GPU, so that is worth a test, not a default.

## 4. Trust, verification and safety

- **Batch**: BOINC-style quorum. Send each unit to 2 nodes. Exact output matching is unreliable
  across GPU vendors, so accept on semantic similarity plus logprob agreement and escalate
  disagreements to a third node or the floor.
- **Interactive**: a 2-5% canary rate with known answers. Failures lower reputation and
  repeated failures ban the node.
- **Output filter**: every response passes a small classifier at the gateway before reaching a
  player. Peers are untrusted and games ship to minors.
- **Privacy**: hosts can read prompts. Send only game context, with no SteamID, no player
  chat and no PII. State this in the node's opt-in text. Use TLS to the gateway and rotate
  per-job pseudonymous IDs. *As built:* a job is the player's message and the studio's NPC prompt, with no account id, name or address, and
  volunteers serve a title only if it opts in; "no player chat" cannot hold for dialogue. See docs/privacy.md and docs/volunteer-terms.md.
- **Abuse**: rate-limit per Steam account and per title. Reject jobs above a token cap.

## 5. Credit and incentives

- Credit is earned per verified token, with higher weight for batch units that passed quorum.
- Redeem through the **Steam Inventory Service** as cosmetics or in-game items that the
  publisher grants **[verify Valve's rules on item grants and any trading or marketplace effects]**.
- Avoid cash payouts and crypto. They add money-transmission, tax and Steam-policy risk.

## 6. SDK (publisher side)

1. Drop in the Unity/Unreal plugin and set the title key.
2. Call `Anansi.Chat(messages, persona)` or `Anansi.Prebake(spec)`.
3. The SDK tries the cache, then the gateway, then the local 1-3B fallback model
   (llama.cpp bundled), so the game always works offline.

## 7. Risks, in order of severity

1. **Platform policy [verify first, per platform; Steam shown].** Valve has restricted apps that use players' hardware for
   third-party compute (crypto mining was banned). Get written confirmation from Valve
   partner support that an opt-in, disclosed, idle-only inference node is allowed. If it is
   not, the fallback is distributing the node outside Steam and using Steam only for
   auth and inventory.
2. **Supply/demand phase mismatch.** GPUs are idle when players are offline, but demand peaks
   when players are online. Size the dedicated floor for peak interactive load, and use
   volunteers for batch work and overflow.
3. **Economics.** Hosted 7-8B inference is already cheap **[verify current prices]**. Model
   the full cost (floor, gateway, verification overhead, credit items) against hosted tokens
   before committing. The case is strongest for batch pre-generation at large scale.
4. **Model licence.** Pick Apache-2.0 models (for example Qwen or Mistral) first. Llama and
   Gemma have custom commercial terms.
5. **Security of the node as malware-adjacent software.** Expect antivirus and community
   suspicion. Publish source, sign binaries, and show a visible tray indicator.

## 8. Build order

1. Gateway, scheduler and 3 studio-run floor nodes. OpenAI-compatible API, Steam ticket auth.
   One Unity sample with local fallback. Measure latency and quality.
2. Node app: idle detection, depot-delivered model, pull protocol. Batch jobs only.
3. Quorum verification and reputation. Add interactive jobs for nearby idle nodes.
4. Credits through Steam Inventory, then a second title.

---

# Part 2: Load balancing, security and sharded models (v0.3)

All numbers in this part are back-of-envelope estimates for sizing, not measurements.

## 9. Serving tiers, revised

| Tier | What runs | Who serves it | Used for |
|---|---|---|---|
| T0 | 1-3B, local in the game | the player's own machine | offline fallback, draft model for speculative decoding |
| T1 | 7-14B, **whole model per node** | volunteers + floor | default interactive path |
| T2 | 30-70B, **sharded across a swarm cell** (Petals-style) | cells of volunteers + floor | batch quality work, premium interactive with speculation |

**Why T2 is confined to cells.** Sharding sends activations through every hop for every token.
Per-token traffic is small (hidden size 8192 x 2 bytes = 16 KB, about 8 KB int8), so latency is
dominated by round trips, not bandwidth. A 70B Q4 model is about 39 GB and 80 layers, so an
8 GB card holds roughly 10 layers and a chain needs about 8 hops. At 30 ms per hop that is
about 240 ms per token (about 4 tok/s, matching Petals' public numbers). At 10 ms per hop
inside a regional cell it is about 80 ms per token (about 12 tok/s). Prompt prefill moves
tokens x 16 KB per hop, so a 1,000-token prompt is about 16 MB per hop. Cache prompt prefixes
and keep NPC personas short.

**A cell** is a set of nodes in one metro or region with pairwise RTT under about 15 ms.
Chains never cross cells. The scheduler forms cells from measured RTT (section 12).

**Speculative decoding hides the hop latency.** The gateway (or the local T0 model) drafts
4-8 tokens, and the chain verifies them in one pass. Expect roughly 2-3x effective
throughput on dialogue-like text **[verify by measurement]**.

## 10. Distributing the model, Petals-style

Mechanisms adopted from Petals:

- Each node serves a **contiguous block range** of transformer layers. The gateway keeps the
  token embeddings and the LM head, so hosts of middle layers never see raw token IDs.
- A **session** holds a per-layer KV cache on each node in the chain.
- The gateway logs each session's inputs to every stage. If a node fails, the gateway picks a
  replacement for that block range and **replays the logged inputs** to rebuild its KV cache.
- **Block assignment controller:** a joining node reports free VRAM and benchmarked tokens/s.
  The controller assigns the block range that most raises the weakest point in coverage, and
  rebalances when a range falls below replication factor 2 or its throughput lags.
- Activations cross the wire as int8 with per-tensor scales.

Differences from Petals:

- **Routing runs in the gateway, not in the game client.** The client is a game, not a trusted
  router. The gateway builds a graph of (block range, node) vertices with edge weights equal
  to measured RTT plus compute time per token, and runs a shortest path from layer 0 to
  layer N for each session. Recompute on failure or when a faster path appears.
- **Hub control plane.** Heartbeats (every 5 s), assignments and credits are central.
  Inside a cell, nodes send activations **peer to peer** for latency by default. See the IP
  exposure choice in section 12.

**Build vs reuse.** Petals is MIT, Python, PyTorch/bitsandbytes and officially Linux/WSL
**[verify current Windows support]**. That is heavy for casual Windows volunteers.
Recommended path:

1. Prototype T2 with Petals server code on the floor and on power-user Linux/WSL nodes. This
   tests whether sharded latency is acceptable for your games before you write anything.
2. If it is, write a native **block server** in the llama.cpp worker (layer-range execution
   plus an activation RPC). llama.cpp's own RPC backend targets trusted LANs with no
   authentication, so do not expose it to the internet as is.

## 11. Load balancing

Two levels: the gateway chooses a tier and region, then a scheduler inside the region chooses
nodes.

**T1 (whole-model replicas)**
- **Power of two choices:** sample 2 eligible nodes, pick the lower `queue_depth + EWMA(ms/token)`.
  This avoids herding and needs no global lock.
- **Session affinity** by consistent hash on `(title, npc_id)` so a conversation hits the node
  that already has its prompt prefix cached. Break affinity if that node is over 80% busy.
- **Hedging for interactive jobs:** if first token has not arrived by the title's p95 budget
  (default 600 ms), send the same job to a second node and cancel the loser. Cap hedges at
  5% of traffic.
- **Admission control and shedding:** bounded per-node queues. When regional capacity is
  exhausted, shed in this order: batch jobs (delay them), then route interactive jobs to the
  floor, then return `429 + Retry-After` so the SDK uses the T0 local fallback.
- **Priority classes:** interactive > prebake > background. Reserve at least 30% of floor
  capacity for interactive.

**T2 (sharded)**
- The scheduler assigns the shortest-path chain (section 10). Cap concurrent sessions per
  block range by free KV memory, since KV cache, not compute, is the usual limit.
- Run the controller's rebalancing at most once per 5 minutes to avoid churn when volunteers
  come and go. Keep replication factor at least 2 per block range, with one replica on the
  floor.

**Capacity control**
- Autoscale the floor from queue depth and p95 time-to-first-token per region.
- Predict the volunteer pool per hour of day from history, and pre-warm floor nodes for
  the evening peak.
- Treat volunteer capacity as unreliable: expect churn of 20-40% per hour
  **[verify against real data]**, and plan SLOs on floor capacity alone.

## 12. Security

### Threat model and controls

| Threat | Control |
|---|---|
| Host reads prompts | **Accepted risk.** Payloads are AI-generated game content, so confidentiality is not a goal. Still keep SteamIDs and player chat out of prompts, use TLS, and never put secrets (API keys, unreleased story spoilers a publisher cares about) in prompts. |
| Host returns wrong or poisoned output (T1) | Canary prompts (2-5%), duplicate-and-compare sampling, reputation. |
| Host corrupts activations (T2) | **Audit sampling:** for about 2% of chains, a trusted floor node recomputes a random layer range from the logged input and compares outputs within a numeric tolerance. A failure bans the node and voids pending credits. |
| Malicious or buggy model file (parser exploits) | Signed, hash-pinned model files delivered via the Steam depot. Nodes never load unsigned files. Keep llama.cpp pinned and updated. |
| Remote code execution through jobs | Jobs are data only (prompt, params, grammar). The worker runs as a low-privilege process in an OS sandbox (AppContainer/Job Object on Windows, bubblewrap/seccomp on Linux) with no network except to the gateway and cell peers. |
| Sybil nodes and reputation farming | Node identity bound to a Steam account (one account, up to 2 nodes) with a minimum account age and a verified game library **[verify what Steam exposes]**. New nodes start with canary-only traffic and no credits for 24 h. Credits pay out after a 7-day audit window. |
| Peer IP exposure in sharded chains (doxxing, DDoS) | Default: activations go through regional **relay nodes** run by the floor. This adds about 5-15 ms per hop **[verify]**. Direct peer-to-peer is opt-in for volunteers who accept IP exposure. |
| Gateway DoS | CDN/WAF in front, per-title and per-account rate limits, token caps per request, request signing. |
| Cost abuse by clients | Per-title quotas, per-Steam-account daily token budgets, anomaly alerts. |
| Prompt injection and jailbreaks | The game treats LLM output as **untrusted input**. NPC actions use grammar-constrained decoding (llama.cpp GBNF / JSON schema) so the model can only emit a whitelisted action set. Gateway output classifier before delivery. |
| Compromised node software or updates | Signed releases, reproducible builds, SBOM, public source, staged rollouts with a kill switch. |
| Rogue or compromised gateway | Gateway keys in an HSM or KMS, short-lived node certificates (24 h), audit logs, separate signing keys for models and for releases. |

### Identity and transport

1. A user installs the node from Steam. On first run the node proves Steam identity (auth
   ticket verified by Steam's Web API) and receives a **24-hour mTLS certificate** from the
   enrollment service. It renews while it is in good standing.
2. Every job is signed by the gateway with a short-lived key and carries a job token. A node
   rejects unsigned or expired jobs.
3. Node-to-node links inside a cell use mTLS with the same certificates.
4. Game clients authenticate to the gateway with the Steam session ticket plus the
   publisher's title key. The gateway never accepts a title key from the client without the
   ticket.

### Privacy scope

Content privacy is out of scope (see the first row of the threat table). The security work
in this design is about **integrity** (wrong or corrupted output), **availability** (churn,
DoS) and **node safety** (the volunteer's machine), not confidentiality. If a publisher
later needs a private tier, serve it from floor nodes only.

## 13. Architecture, consolidated

```
 Game (Unity/Unreal) + Anansi SDK  (T0 local model, cache, grammar-constrained output)
        │  Steam ticket + title key, TLS
 ┌──────▼───────────────────────────────────────────────────────────┐
 │ Regional gateway cluster                                         │
 │  auth · quotas · prompt templates · output filter · embeddings/LM head (T2)
 │  scheduler: P2C + affinity + hedging · T2 chain router · session log
 │  controller: block assignment · cell formation · autoscaler      │
 └──────┬───────────────┬──────────────────────┬────────────────────┘
        │ jobs (pull)   │ relay                │ audits
 ┌──────▼─────┐  ┌──────▼───────┐       ┌──────▼──────┐
 │ T1 nodes   │  │ T2 cell:     │       │ Floor nodes │
 │ whole 7-14B│  │ block ranges │◄─────►│ (trusted)   │
 │ volunteers │  │ A→B→C→…→N    │       │ T1, T2, audit, confidential
 └────────────┘  └──────────────┘       └─────────────┘
     CDN ◄── batch results (prebaked content)
```

## 14. Revised build order

1. (Unchanged) Gateway, 3 floor nodes, Steam auth, Unity sample, T0 fallback. Measure.
2. Load balancer for T1: P2C, affinity, hedging, shedding. Load-test with synthetic traffic and
   injected node failures.
3. Security baseline: enrollment, 24 h mTLS, signed jobs and models, sandboxed worker,
   output filter, grammar-constrained actions.
4. Node app and volunteer pool for T1 and batch, with canaries and quorum.
5. T2 prototype with Petals on floor and Linux volunteers inside one cell. Measure tokens/s
   with and without speculation. **Go/no-go gate:** continue only if interactive latency meets
   the title's budget.
6. T2 audit sampling and relay nodes, then the native block server if step 5 passes.

## 15. Lessons taken from Tor

Tor is built for anonymity, which we do not need, so onion layering, traffic padding and
bridges are skipped. These mechanisms for running a network of untrusted volunteers are
kept:

1. **Signed node directory with measured bandwidth.** The controller publishes a signed,
   versioned directory every few minutes (node ID, flags, region/cell, models/block ranges,
   measured speed). Speed comes from **gateway probe jobs**, never from what a node reports.
   Directory signing keys are rotated, and nodes and SDKs reject stale directories.
2. **Node flags** assigned by the controller: `Fast`, `Stable` (uptime), `Trusted` (clean audit
   history), `Floor`, `Relay`. The scheduler uses flags to place traffic: interactive jobs
   prefer `Fast`+`Stable`, T2 first stages require `Stable`, audits run only on `Floor`.
3. **Path diversity for sharded chains.** No two hops in a chain may share an operator, a
   Steam account, an ASN or a /16. The reason is now integrity: colluding hops could return
   consistent but corrupted activations that a single honest audit would miss. Selection is
   weighted by measured speed with a random component.
4. **Stable entry set.** Each title (and each NPC where possible) is pinned to a small set of
   `Stable` first-stage nodes. This limits how many sessions a bad node can touch, keeps
   prompt caches warm and makes reputation damage attributable.
5. **Credit-based flow control per chain.** Each hop grants its predecessor a window of N
   in-flight tokens or microbatches. A slow node reduces its window and the chain slows
   instead of buffering without bound. Window sizes are bounded by the node's free KV memory.
6. **Hop-by-hop chain setup.** The gateway builds a T2 chain by negotiating a fresh session
   key with each node in turn (an authenticated key exchange using the node's 24 h
   certificate). Each node accepts traffic only from its assigned predecessor, which stops
   unrelated nodes from injecting activations into a session.
7. **Slow ramp-up for new nodes.** New nodes get only canary traffic for 24 h, then a traffic
   cap that grows with clean audits, the same ramp that gates credits. Flags such as `Stable`
   are earned by uptime, not self-declared.
8. **Rendezvous for NAT.** Direct links inside a cell use outbound connections to a
   `Relay` node as a rendezvous point, with STUN/TURN-style hole punching where possible. The
   relay carries traffic only when hole punching fails.

### Build order additions

- Step 2 (load balancer): add directory publishing, flags and probe-based speed measurement.
- Step 4 (volunteer pool): add the new-node ramp-up.
- Step 5 (T2 prototype): add path diversity, the stable entry set and per-hop flow-control
  windows.
- Step 6: add hop-by-hop chain setup and rendezvous relays.

## 16. Lessons from other open-source networking and routing projects

Repository licences were checked on 2026-11-10 (see the register in section 17). Items still
tagged **[verify]** were not confirmed. Using only an *idea* needs no licence check.

### 16.1 LLM-aware routing (highest value)

**Source:** Kubernetes Gateway API Inference Extension "endpoint picker", llm-d, vLLM
production-stack, NVIDIA Dynamo (all Apache-2.0 **[verify]**).

Generic load balancers count connections, which is a poor signal for LLM servers. These
projects score each candidate by LLM-specific state:

- **KV-cache utilisation** and queue depth reported by the server.
- **Prefix-cache hit likelihood**: route to the node that already holds the prompt prefix
  (the NPC persona and conversation so far).
- **Adapter affinity**: prefer nodes that already have a title's LoRA loaded.
- **Disaggregated prefill/decode**: run long-prompt prefill on strong nodes and decode on
  others. Worth testing for T2 only, since it moves KV cache across the network.

**Anansi:** replace the simple `queue_depth + EWMA` score in section 11 with
`score = w1*queue + w2*kv_util + w3*ewma_ms_per_token - w4*prefix_hit - w5*adapter_loaded`.
Nodes report `queue`, `kv_util`, `loaded_adapters` and a prefix-hash summary in their
heartbeat. Start with the weights set by hand and tune from traces.

### 16.2 Envoy (Apache-2.0)

| Idea | Use in Anansi |
|---|---|
| **Outlier detection** (eject a host after N consecutive failures or latency outliers, re-admit after a growing back-off) | Automatic temporary ejection of flaky volunteers, separate from long-term reputation. Back-off doubles per ejection. |
| **Retry budgets** (retries capped as a fraction of live traffic) | Hedging and retries limited to a percent of requests so a slow region cannot turn into a retry storm. Replaces the fixed 5% hedge cap with a budget that shrinks under load. |
| **Circuit breakers** (max pending requests and connections per upstream) | Hard per-node and per-region queue limits that trigger shedding. |
| **Locality-weighted load balancing and priority failover** | Cell/region becomes the locality. Priority 0 = same cell, 1 = same region, 2 = floor. Traffic spills to the next priority only when the healthy fraction of the current one drops below a threshold. |
| **Panic threshold** (when too many hosts are unhealthy, stop ejecting and spread traffic across all) | Prevents ejecting an entire cell during a brief network blip. |
| **xDS-style split of control plane and data plane** | The controller pushes the signed directory and routing weights. Gateways and SDKs only apply them. They do not decide policy. |

### 16.3 Smarter selection and affinity

- **Latency-aware P2C with EWMA** (Linkerd, Finagle) is already in section 11. Use
  *peak-EWMA* (jump up fast, decay slowly) so a node that just got slow is penalised at once.
  Linkerd's open-source release terms changed in 2024 **[verify]**, so copy the algorithm,
  not the code.
- **Bounded-load consistent hashing** (Google, used in HAProxy and Envoy as ring hash with
  limits) replaces the ad hoc "break affinity at 80% busy" rule in section 11: each node gets
  a capacity cap of `ceil(avg_load * 1.25)` and overflow moves to the next node on the ring.
  Hash on `(title, npc_id)`.
- **Adaptive concurrency limits** (Netflix concurrency-limits, Apache-2.0 **[verify]**): each
  node's in-flight limit is found automatically with an AIMD or gradient algorithm that backs
  off when latency rises. This replaces hand-set queue caps, which differ by GPU model.

### 16.4 Calico and policy-driven networking (Apache-2.0)

| Calico idea | Use in Anansi |
|---|---|
| **Default-deny, label-based policy** | A node's host firewall allows traffic only to the gateway and to assigned cell peers. Roles are labels (`role=t2-stage`, `cell=eu-west-3`) from the signed directory. Policy is rewritten when the directory changes, so a node dropped from a chain cannot keep sending to its old neighbours. |
| **Agent that watches a datastore and programs the data plane** (Felix) | The node agent watches the directory and programs the local firewall (Windows Filtering Platform on Windows, nftables on Linux). The node enforces policy even if the gateway is compromised. |
| **Fan-out proxy to scale watchers** (Typha) | Serve the directory as signed snapshots plus deltas from a CDN. Gateways do not hold open connections to every volunteer. |
| **Route reflectors instead of a full BGP mesh** | Do not measure RTT between every pair of nodes. Cells, with one controller per cell, keep probing to O(n) per cell. |
| **Policy as data, evaluated per request** | The gateway has a small policy table: title X may use model Y at tier Z, up to N tokens per day. |

Skip the eBPF data plane, BGP itself and IPAM: these solve container networking at cluster
scale, not our problem.

### 16.5 Estimating RTT without measuring every pair

**Vivaldi network coordinates** (as in HashiCorp Serf and Consul, algorithm public, the
libraries are MPL-2.0 **[verify]**). Each node keeps a small coordinate vector, and the
distance between two coordinates estimates their RTT. A new node pings a handful of peers
and gets a usable position. Use it to form cells (section 9) and to pre-rank chain
candidates, then confirm with real probes on the top few.

### 16.6 Connectivity and relays

- **Nebula** (Slack, MIT **[verify]**): an overlay network with certificate-based identity
  and "lighthouse" nodes for introduction and hole punching. This matches our `Relay`
  rendezvous role, and its design is a good model for our 24 h certificates.
- **Tailscale DERP** (BSD-3 **[verify]**) and **libp2p circuit relay v2 with DCUtR**
  (MIT/Apache **[verify]**): fallback relays when hole punching fails, and a hole punching
  protocol. Use libp2p only for the in-cell peer links if we choose to avoid writing our own
  NAT traversal.
- **SWIM gossip** (Serf, memberlist): fast failure detection among peers. Inside a cell, use
  it so nodes detect a dead neighbour in about a second and tell the gateway, faster than a
  5 s heartbeat. Skip global gossip. The hub already owns membership.

### 16.7 Placement and distribution

- **BitTorrent rarest-first** applied to block assignment: assign a joining node the block
  range with the fewest healthy replicas (section 10 already does this, now with a name and
  known behaviour). Add *tit-for-tat*-style credit weighting: credits scale with measured
  useful work, not time online.
- **Ceph CRUSH** (LGPL): deterministic placement from the directory so every gateway computes
  the same block-to-node map without coordination. Copy the idea only (the licence is
  weaker-copyleft).
- **P2P model distribution** (Dragonfly, Apache-2.0 **[verify]**): not needed while the
  model ships as a Steam depot. Revisit if depot size limits or update speed become a
  problem.

### 16.8 What to adopt first

| Priority | Item | Why |
|---|---|---|
| 1 | LLM-aware scoring (16.1) | Largest effect on latency and throughput per GPU |
| 2 | Outlier detection, retry budgets, priority failover (16.2) | Makes volunteer churn survivable |
| 3 | Bounded-load hashing and adaptive concurrency (16.3) | Removes hand-tuned thresholds |
| 4 | Label-based default-deny node firewall (16.4) | Cheap hardening of volunteer machines |
| 5 | Vivaldi coordinates (16.5) | Needed before cells scale past a few dozen nodes |
| 6 | Lighthouse and relay design (16.6) | Needed for T2 direct links |

Build order impact: items 1-3 go into step 2 (load balancer), item 4 into step 3 (security
baseline), items 5-6 into steps 5-6 (sharded tier).

## 17. Licence register (checked 2026-11-10)

Source: the licence reported by the GitHub API for each repository, with the ambiguous ones
read from the LICENSE files. This is a technical check, not legal advice. Have counsel review
before shipping, especially the model licences and any bundled binaries.

All "OK" rows allow commercial use, modification and redistribution, with attribution and
notice requirements. Apache-2.0 also carries an explicit patent grant.

| Component | Licence | For-profit / distributable | Notes |
|---|---|---|---|
| llama.cpp | MIT | OK | Node worker and T0 local model. Active. |
| vLLM | Apache-2.0 | OK | Floor nodes. Active. |
| Petals | MIT | OK | **Last push 2024-09-07, so effectively unmaintained.** Treat as a reference or a prototype base, not a dependency to track. |
| hivemind (Petals' DHT/networking library) | MIT | OK | Last push 2026-01, lightly maintained. |
| Colibri | Apache-2.0 | OK | Each model it runs keeps its own licence. |
| Gateway API Inference Extension | Apache-2.0 | OK | Active. |
| llm-d | Apache-2.0 | OK | Active. |
| vLLM production-stack | Apache-2.0 | OK | Active. |
| NVIDIA Dynamo | Apache-2.0 for the code | OK | The API reports "NOASSERTION" because the LICENSE file begins with a notice that some test data files are MIT. The rest is Apache-2.0. |
| Envoy | Apache-2.0 | OK | |
| Calico | Apache-2.0 | OK | |
| Linkerd (repo) | Apache-2.0 | OK for the source | Not verified: whether vendor-built stable binaries are free to use. Copy the algorithm or build from source. |
| Netflix concurrency-limits | Apache-2.0 | OK | |
| HashiCorp Serf and memberlist | MPL-2.0 | OK | File-level copyleft: changes to MPL files must be published, but your own code can stay proprietary. |
| **HashiCorp Consul** | **BSL (IBM), from 1.17** | **Do not use** | Not open source. Only use Vivaldi as an *algorithm*, via Serf or memberlist or our own code. |
| Nebula (Slack) | MIT | OK | |
| Tailscale (incl. DERP relay) | BSD-3-Clause | OK | |
| go-libp2p, rust-libp2p | MIT | OK | |
| Dragonfly | Apache-2.0 | OK | |
| **Ceph** | **LGPL-2.1 or LGPL-3** | Linking is allowed, but copying code is not simple | Take the CRUSH *idea* only and write our own. |
| Tor (C) | Not confirmed | | The GitHub mirror reports none and I could not read the licence file. Not planned for use. |
| Arti (Tor in Rust) | MIT file present on GitLab | Probably OK | Only the MIT file was confirmed. Not planned for use. |

### Models (from each Hugging Face model card, 2026-11-10)

| Model | Licence | Commercial and redistribution |
|---|---|---|
| Qwen3-8B | Apache-2.0 | OK. Recommended default. |
| Mistral-7B-Instruct-v0.3 | Apache-2.0 | OK. |
| Llama-3.1-8B-Instruct | Llama 3.1 Community Licence | Custom terms. From memory, not re-read: commercial use allowed, a very large user-count threshold, attribution, an acceptable-use policy and a requirement that redistributors pass on the licence. Read it before shipping to volunteers. |
| Gemma-2-9B-it | Gemma Terms of Use | Custom terms, not re-read. Similar concerns: a use policy and pass-through of terms. |

Decision: ship Apache-2.0 models (Qwen, Mistral) for the first release. Distributing a model
file to volunteers is redistribution, so custom-licence models need their terms accepted by
each node operator.

### Consequences for the design

- Section 10: Petals has been stale for over a year, so the T2 prototype should plan for
  patching it ourselves or going straight to the native block server.
- Section 16.5: do not depend on Consul. Serf or memberlist (MPL-2.0) or our own Vivaldi
  implementation is fine.
- Section 16.7: write our own CRUSH-style placement.
- No component found blocks free, distributable, for-profit use.

## 18. Petals alternatives for the sharded tier (T2), checked 2026-11-10

Source: GitHub API (licence, activity) plus each project's README. Maintenance and star
counts are a snapshot. "Not stated" means the README does not say, not that the feature is
missing.

| Project | Licence | Activity | Fit for T2 |
|---|---|---|---|
| **Parallax** (Gradient) | Apache-2.0 | Pushed 2026-07-01; v0.0.1 announced 2025-10; about 1.4k stars | **Closest successor.** Pipeline-parallel sharding across heterogeneous nodes, "dynamic request scheduling and routing", P2P via Lattica, backends SGLang/vLLM (GPU) and MLX (Mac). Not stated: Windows support, WAN behaviour, fault tolerance, security. Early-stage. |
| **exo** | Apache-2.0 | Pushed 2026-11-06; about 48k stars | LAN cluster tool aimed at devices you own: auto-discovery on one network, Apple-silicon focus, Linux CPU only for now, no Windows mention, no stated authentication between nodes. **Not suitable for untrusted internet volunteers.** Useful for an in-house test rig. |
| **Distributed Llama** (b4rtaz) | MIT | Pushed 2026-11-10; about 3.1k stars | Tensor parallelism across home devices on a LAN. Not an internet design. |
| **prime-iroh** (Prime Intellect) | MIT | Pushed 2026-07-28; about 54 stars | "Asynchronous P2P communication backend for decentralized pipeline parallelism." A transport component, not a serving system. Candidate for the activation links in section 10. |
| **AI Horde** (Haidra) | **AGPL-3.0** | Pushed 2026-11-10; about 1.7k stars | Not sharding. A working crowdsourced network of **whole-model volunteer workers** with a credit ("kudos") system, which is our T1 and @home design in production. **Study the design, do not embed the code:** AGPL requires publishing the source of a modified network service. |
| llama.cpp RPC | MIT | Active | Layer split over RPC for trusted LANs, with no authentication (section 10). |
| Mooncake, Ray, SGLang | Apache-2.0 | Active | Datacentre serving and scheduling. Worth reading for routing and KV-cache ideas (section 16.1), not for volunteer networks. |

Smaller GitHub projects (for example mycellm, Apache-2.0, 10 stars) exist but are too new
and untested to rely on.

### Conclusion

Nothing found is a mature, drop-in replacement for Petals. Parallax is the nearest and is
newer and more active, but it is early and its README does not mention the properties we
need: untrusted peers, failure recovery and security. Revised T2 plan:

1. Run a **two-way bake-off** in the section 14 step 5 prototype: Petals vs Parallax, in one
   cell, on the same model, measuring tokens/s, time to first token, behaviour when a node is
   killed mid-session, and effort to add our directory, flags and audits.
2. Keep the native block server as the fallback if neither passes. Evaluate prime-iroh for
   its activation transport.
3. Do not choose exo for the volunteer network.
4. Read the AI Horde's worker and credit design before finalising the T1 credit system.

## 19. Windows-native requirement (supersedes the T2 plan in section 18)

**Requirement:** volunteers must run the node on native Windows, without WSL or Linux.
The Steam Hardware Survey for October 2026 shows Windows at 93.7%, Linux 3.95%, Mac 2.35%.

### What runs on native Windows (checked 2026-11-10)

| Component | Native Windows? | Evidence |
|---|---|---|
| **llama.cpp** | **Yes** | Official release b12282 ships Windows x64 CUDA 12.4, CUDA 13.5 and CPU builds (also arm64). Vulkan and HIP builds not checked **[verify]**. |
| vLLM | No | Docs: "vLLM does not support Windows natively." WSL, or an unofficial community fork. |
| Petals | WSL only | README points Windows users to a wiki guide for WSL. |
| Parallax | Not stated | Backends are SGLang, vLLM (Linux-oriented **[verify]**) and MLX (Mac). |
| exo | Not stated | README covers macOS and Linux (CPU for now). |
| llama.cpp RPC | Not stated | README does not mention Windows and calls the backend a proof of concept, "fragile and insecure." |

**WSL2 is rejected as the mainstream path.** Asking gamers to enable Windows features,
reboot, install a Linux distribution and configure GPU passthrough will not reach the
mass market. That is a judgment, not a measured result. WSL stays an option for power users.

### Consequences

1. **The node is a native Windows app wrapping llama.cpp.** It launches `llama-server` as a
   sandboxed child process (low-integrity token and a Job Object). It ships CUDA builds
   and picks one by the installed driver **[verify minimum driver per build]**, and falls
   back to Vulkan for AMD and Intel GPUs **[verify]**. The top five GPUs on the survey are all
   NVIDIA RTX, so CUDA comes first. CPU-only nodes are not accepted.
2. **Model sizing from the survey's VRAM figures:** 8 GB is the single largest bucket (26.9%),
   then 16 GB (26.4%), 12 GB (12.9%), 24 GB (5.4%). About 72% of listed buckets are at least
   8 GB, which fits a 7-8B Q4 model (about 5 GB) with room for KV cache. Nodes with 4-6 GB
   (about 11%) run a 3-4B model tier or act as clients only.
3. **Idle handoff on Windows:** the only dependable way to give VRAM back within a second is
   to **kill the worker process**, not unload the model. The agent watches for a fullscreen
   or GPU-heavy process (NVML and the process list), kills `llama-server` and restarts it
   when the machine has been idle for 2 minutes.
4. **Windows operational work:** code-sign the binaries (SmartScreen and antivirus
   reputation), ship through Steam, run as a tray app with a visible indicator, respect power
   plan and battery state, and test alongside anti-cheat software (the node stops when a
   game starts, but the interaction is unverified).
5. **T2 sharding has no off-the-shelf native Windows option.** None of Petals, Parallax or
   exo is confirmed on native Windows. Options, in order of effort:
   - **A. Gateway-orchestrated llama.cpp RPC.** The README diagram shows each RPC server
     connected to the main host rather than to each other, which matches our star topology
     with the gateway as hub (the README does not state whether all tensor traffic passes
     through it). Needs: confirmation that it builds and runs on Windows, an mTLS tunnel
     because it is unauthenticated, sandboxing of the RPC server, and a solution for getting
     each node only its layer slice instead of the whole file (split GGUF slices on a CDN,
     using the RPC server's weight cache option).
   - **B. A native block server** written against ggml, with the activation transport
     evaluated from prime-iroh. More work, full control.
6. **Priority change.** Because the mainstream Windows node can serve a whole 7-8B model, T1
   plus batch jobs deliver most of the value. **T2 moves after the first Windows launch**
   and starts as an optional "power cell" on Linux/WSL running Petals or Parallax, then option
   A or B for Windows when its numbers justify the work.

### Revised build order (replaces section 14 steps 4-6 ordering)

1. Gateway, three floor nodes, Steam auth, Unity sample, T0 fallback. (unchanged)
2. Load balancer for T1 with section 15-16 features. (unchanged)
3. Security baseline. (unchanged)
4. **Windows node v1:** llama.cpp wrapper, idle handoff, sandbox, signing, depot-delivered
   model, pull protocol, batch jobs. Closed beta on 50-100 real gaming PCs across NVIDIA,
   AMD and Intel hardware. Measure real idle windows, tokens/s per GPU and crash rates.
5. Quorum, canaries and credits; interactive jobs for nearby idle nodes.
6. Optional Linux/WSL power cell for T2 (Petals vs Parallax bake-off), then Windows T2
   (option A, then B).

### 19.1 macOS on Apple Silicon (M1/M2 and later)

Mac gamers are a small slice of Steam, but the hardware suits this workload and the support is cheap, because
the node agent is plain Python and the gateway never sees what runs behind it.

- **Runtime:** Ollama and llama.cpp both run on Apple Silicon through Metal. Nothing in the gateway or `node/agent.py`
  is platform specific. MLX is another option later; it is not needed for Phase 1.
- **Memory model:** Apple Silicon has unified memory, so there is no separate VRAM to cap. The 1-2 GB budget of
  section 21 applies to the model's share of RAM instead. The Lite profile (Qwen3-1.7B Q4, about 1.4 GB) fits
  a base 8 GB M1 beside a game; Standard (4B, about 2.5 GB) is the ceiling on 8 GB machines and should wait for
  16 GB or more. A Mac node must also yield memory when the game asks, which macOS does less gracefully than a
  dedicated GPU does, so the idle-only rule in section 21 matters more here.
- **Verification:** probes and spot checks (section 22) treat a Mac node like any other. Do not assume bit-identical
  output between Metal and CUDA nodes; that is why verification uses known-answer checks, not output equality.
- **Status:** untested; no Mac hardware is available. Not run: the self-checks, Ollama or llama.cpp on a Mac,
  thermal behaviour, and game co-residency.

## 20. Partial residency on each node (Colibri-style) (supersedes the T2 priority in 18-19)

**Requirement:** a node must serve a model larger than its GPU memory by keeping only the
hot part of the model on the GPU, instead of requiring the whole model in VRAM.

### What Colibri does (from its README and docs, 2026-11-10)

- **Three tiers.** Dense parts (attention, shared experts, embeddings) sit in RAM, or on the
  GPU when they fit. Routed experts of a Mixture-of-Experts (MoE) model live on NVMe and are
  read when the router picks them. A cache "learns which experts your work uses": a per-layer
  LRU plus a pinned hot set. The GPU holds the hottest experts and dense layers. On a miss
  the CPU computes that expert while the GPU computes the resident ones.
- **Heat files.** Measured routing "heat" decides placement and is stored (`HEAT_FILE`,
  `.coli_usage`). A second run **warm-starts fully placed** from the heat file.
- **Placement changes speed only.** Colibri says the router's decisions and the weights'
  precision are the same whether an expert came from VRAM, RAM or disk.
- **Native Windows, no WSL.** There is a Windows 11 walkthrough, prebuilt release archives
  (including a CUDA build) and a Vulkan path for AMD, Intel and NVIDIA GPUs, integrated GPUs
  included. Licence Apache-2.0 (verified).
- **Candidate model:** Qwen3.6-35B-A3B (about 3B parameters active per token), Apache-2.0 on
  its Hugging Face card, 23 GB download, RAM minimum 10 GB and 20 GB recommended.

### Reported speeds (Colibri's own measurements, not ours)

| Setup | Qwen3.6-35B-A3B decode |
|---|---|
| CPU only (8-core desktop) | 6.0 tok/s |
| Integrated Radeon 780M, Vulkan | 9.9 tok/s |
| RTX 3070 8 GB, dense layers on the card (Threadripper desktop, machine C) | 25.4-30.0 tok/s |
| Two 8 GB cards, warm heat history | 11.3 tok/s |

The RTX 3070 box has a 12-core Threadripper and plenty of RAM, which is better than a typical
gaming PC. Expect lower on 16 GB machines. This is the first thing the beta must measure.

**Heat matters.** In Colibri's CUDA-tier doc, a run using a heat file from its own kind of
prompt had 81.5-82.4% expert hits on the card at about 15 ms per token. A different kind of
prompt using a mismatched heat file had 44.5-64.6% hits at about 21-24 ms. One setup, one model.

### Design consequences

1. **Node memory model and report.** Each node reports VRAM budget for experts, RAM, measured
   NVMe read speed (a startup benchmark), the resident title heat, and its recent hit rate.
   Nodes with spinning disks or very slow storage are batch-only or refused.
2. **Per-title heat files.** A game's NPC prompts use a narrow slice of a model, so a hot set
   can be learned once and shipped. An offline **profiling job** per title runs its persona
   prompts and sample conversations through a reference node and produces a heat file,
   signed with the model hash and title ID. Nodes download it and warm-start. A heat file
   only fits the model shape it was made for, so it is versioned with the model. Size of a
   heat file: not checked **[verify]**.
3. **Cache-aware scheduling.** Extend the section 16.1 score with `heat_match` (overlap
   between the node's resident set and the job's title) and a `warm` flag. Each node serves
   one or two titles at a time, sticky and rotated by demand, so caches do not thrash. Batch
   work units are queued by title so a node stays warm. A new node or new title enters a
   `warming` state (the cold case was very slow on a 25 GB laptop in Colibri's notes) and
   takes only canary and batch traffic until its probe passes.
4. **Eligibility by measurement, not by VRAM.** Interactive eligibility comes from a probe at
   the title's heat: time to first token and tokens/s. Starting target: under 1 s first token
   and at least 8 tok/s, so a 60-token NPC reply streams in under about 8 s. These numbers
   are my starting point, not a known requirement.
5. **Do not use Colibri's cluster mode across the internet.** It keeps routing and the KV
   cache on a coordinator and sends each layer's routed experts to workers, with one
   round trip per MoE layer. With, say, 40 layers at 15 ms that is 600 ms per token on the
   network alone. Its docs also say a worker that does not answer ends the coordinator,
   and the protocol has no authentication. The docs describe it for Macs on a local network
   and for the GLM-5.3 and DeepSeek V4.1 engines. Use it only inside a floor rack or LAN,
   never between volunteers.
6. **Tier revision.** Whole-VRAM dense models stay for small GPUs. **T1b is new: a tiered
   MoE model (Colibri) on each volunteer node.** It gives 30B-class quality on one
   machine, native on Windows, with no cross-node sharding. The volunteer-pipeline T2 of
   sections 10, 18 and 19 is now low priority and kept as research. The floor can run much
   larger Colibri models with all experts resident for premium and batch work.
7. **Two engines on a node.** The node agent runs llama.cpp for dense models and Colibri for
   MoE models, chosen by model type, both behind the same local API on 127.0.0.1 only. Colibri
   can also import GGUF files. In its own table OLMoE (small MoE) decodes faster on CPU than
   with its Vulkan tier, so the GPU tier is not free speed for every model; measure per model.
8. **Verification.** Because placement does not change routing, results should match across
   nodes more closely than with different quantisations. GPU and CPU arithmetic can still
   differ (Colibri turns off one speculative feature under CUDA for that reason), so keep
   similarity-based checks from section 4, not exact matching.
9. **Disk and RAM.** Every Colibri node stores the 23 GB expert store, so the node needs free
   NVMe space and the Steam depot or a CDN must deliver it **[verify depot limits]**. Reads
   dominate, which wears SSDs far less than writes. 16 GB machines are below the 20 GB
   recommendation and will stream more from disk.
10. **Security.** Run Colibri's server bound to 127.0.0.1 and reachable only by the node
    agent (it ships a web dashboard and API), as a sandboxed child process, loading only
    hash-checked converted models. Pin a release and update through our own staged rollout.
11. **Project risk.** Colibri is young and moving fast (about 50k stars, over 5,000 commits).
    The copyright line names one person. Pin versions, keep llama.cpp as the fallback
    engine, and budget time for upstream bugs.

### Bake-off to run before committing (replaces the Petals vs Parallax test as the first)

On about 10 typical gaming PCs (16 and 32 GB RAM, RTX 3060/4060 and an AMD card, NVMe and SATA):

| Candidate | Why |
|---|---|
| Qwen3.6-35B-A3B on Colibri, with and without a title heat file | The design under test |
| Same model on llama.cpp with experts kept in CPU memory (`--n-cpu-moe`-style options **[verify]**) | Simpler baseline with static placement |
| A dense 8B Q4 on llama.cpp | Quality and speed floor for the cheap case |

Measure first-token time, tokens/s, expert hit rate, RAM and disk use, how quickly VRAM is
freed on game launch, and output quality on 200 prompts from a real title.

### Build order changes

- Step 4 (Windows node v1) gains the dual-engine agent and the Colibri integration.
- New step 4b: the per-title profiling pipeline and heat-file distribution.
- Step 2 (load balancer): add `heat_match`, `warm` and the `warming` state.
- Step 6 now means "floor-side large Colibri models and optional research on volunteer
  sharding".

## 21. Footprint budget: at most 1-2 GB of VRAM per node (constrains section 20)

**Requirement:** the node uses no more than 1-2 GB of VRAM, and a small disk and RAM
footprint. This replaces the "8 GB card" sizing in sections 3, 19 and 20.

### Why this matters

- It widens supply. A 2 GB cap fits almost any discrete gaming GPU, including the 4-6 GB
  cards (about 11% of the October 2026 survey) that the 8 GB sizing excluded.
- It leaves the card free for the game's own use if the player returns, and makes the idle
  handoff cheaper.
- It rules out the best Colibri numbers. The 25-30 tok/s result needed the dense layers on the
  card, and Colibri's own Windows guide sizes a different model's dense part at about 10 GB. With
  only 1-2 GB of VRAM, the dense layers stay on the CPU, so speed becomes CPU-bound. Colibri's
  CPU-only figure for Qwen3.6-35B-A3B is 6.0 tok/s on an 8-core desktop and 9.9 tok/s with its
  Vulkan path on an integrated GPU. A typical gaming CPU may be slower. Not measured by us.

### Footprint profiles (the user picks one; the scheduler uses what each node reports)

File sizes marked * are from Hugging Face listings checked 2026-11-10. The rest are estimates.

| Profile | Model | Disk | VRAM | RAM | Role |
|---|---|---|---|---|---|
| **Lite** | Qwen3-1.7B at Q4, all layers on the GPU | about 1.1 GB (Q8 file is 1.83 GB*) | about 1.5-1.9 GB | under 2 GB | Per-title NPC dialogue, with the title's LoRA adapter |
| **Standard** | Qwen3-4B Q4_K_M (2.5 GB file*), about 40% of layers on the GPU, the rest on the CPU | 2.5 GB | under 1.5 GB | about 3 GB | Better quality, slower |
| **Plus** (opt-in) | Qwen3.6-35B-A3B on Colibri, hot experts in 1-2 GB of VRAM, dense layers on the CPU | 23 GB | 1-2 GB | 10 GB minimum, 20 GB recommended | Highest quality a volunteer can offer, CPU-bound |

For comparison, Qwen3-8B Q4_K_M is 5.03 GB*, which is over the budget.

### VRAM accounting

VRAM use is weights on the GPU, plus the KV cache, plus runtime buffers (the CUDA context and
compute buffers, which I estimate at 0.3-0.5 GB **[verify]**). The KV cache grows with context:

- Qwen3-4B (36 layers, 8 KV heads, head size 128 **[verify config]**): about 0.15 MB per token
  in fp16, so 2,048 tokens is about 0.3 GB.
- Qwen3-1.7B (28 layers): about 0.11 MB per token, so 2,048 tokens is about 0.23 GB.

Rules: cap context at 2,048 tokens for interactive NPC calls, keep persona prompts short, use a
quantised KV cache if llama.cpp supports it for the build **[verify]**, and skip speculative
decoding on Lite (a draft model would use VRAM the budget does not have).

### Hard cap enforcement

- The agent sets the GPU layer count (llama.cpp) or the expert budget (Colibri) from the profile
  and the user's cap (default 1.5 GB, maximum 2 GB).
- At startup it checks free VRAM through NVML. It refuses to start unless free VRAM is at least
  the cap plus a margin.
- While running it samples the process's VRAM use. If it exceeds the cap, the agent restarts
  the worker with a smaller setting.
- RAM is capped with a Windows Job Object memory limit. CPU and disk I/O run at background
  priority.

### Quality: per-title LoRA adapters on a shared small base

A 1.7B-4B base is much weaker than a 35B MoE, so quality has to come from specialisation:

1. A studio generates a title corpus (personas, lore, sample dialogue) using the large model on
   the floor as the teacher.
2. A LoRA adapter is trained for the title on the shared base model. Adapters are expected to be
   tens of MB for a model this size **[verify actual size]**, so many titles share one base file.
3. The node loads the adapter for the title it is serving (llama.cpp supports LoRA adapters
   **[verify compatibility with the chosen quantisation]**).
4. The SDK escalates when the small model is out of its depth (off-script player input, low
   confidence) to the floor's larger model. The escalation rate is a cost number to measure.

Risk: small fine-tuned models can be brittle outside their training distribution and can lose
general knowledge. Test with 200 real prompts per title, including off-script ones.

### Disk footprint

- One shared **Anansi Runtime** Steam app holds the engine and base models. Games add only their
  adapter and heat file, so the base is stored once per PC however many games use it.
- Model files are already quantised, so compressing them again gains little.
- The user sees a storage meter and can choose a profile or uninstall to reclaim the space.

### Effect on the rest of the design

- Section 20's tiered Colibri node is demoted from the default to the optional **Plus**
  profile. Heat files still apply there.
- The default volunteer workload is small-model, per-title jobs. More jobs escalate to the
  floor than before, so floor capacity and cost matter more. Re-run the economics in section 7.
- Volunteer pipeline sharding (the original Petals idea) would cut the footprint further, but at
  the latency cost in section 9, so it stays low priority.

### Build order changes

- Step 4 (Windows node v1) ships Lite and Standard first. Plus follows after its bake-off.
- New step 4c: the per-title LoRA pipeline (corpus generation, training, evaluation, signing,
  distribution), plus the escalation path in the SDK.
- The section 20 bake-off now compares Lite, Standard and Plus at a fixed 2 GB VRAM cap.

## 22. Roadmap, gates, open decisions and risks

This section replaces the build orders in sections 8 and 14. Thresholds are my proposed
starting values, to be agreed with the pilot studio. They are not measured requirements.

### 22.1 Phases

| Phase | Work | Exit criteria |
|---|---|---|
| **0. Gates** | Written confirmation from Valve on the node (G0). Legal review of terms and licences. Pick a pilot title and publisher. | G0 passed, pilot signed |
| **1. Floor MVP** | Gateway with Steam-ticket auth, scheduler (power of two choices plus affinity), three vLLM floor nodes, output filter, grammar-constrained NPC actions, Unity SDK with local fallback. | Pilot NPC dialogue works end to end. Measured p95 first-token time and all-in floor cost per million tokens. |
| **2. Quality** | Per-title corpus from the floor's large model. LoRA pipeline for Lite and Standard. 200-prompt evaluation including off-script input. SDK escalation path. | G1 passed |
| **3. Windows node, closed beta** | Native node agent: llama.cpp wrapper, idle handoff by process kill, sandbox, code signing, depot delivery, profile choice, VRAM cap, pull protocol, batch jobs, canaries. Signed directory, flags, probe-measured speed, new-node ramp-up. 50-100 real PCs across NVIDIA, AMD and Intel. | G2 and G3 measured |
| **4. Verification and credits** | Quorum, reputation, outlier ejection, retry budgets, priority failover, autoscaler, default-deny firewall, Steam Inventory credits. Public opt-in. | G4 and G5 passed |
| **5. Scale and options** | Plus profile with title heat files and cache-aware routing, Vivaldi cells, relays, second title. Research track: volunteer sharding bake-off (sections 10, 18). | Per-feature gates |

### 22.1a Phase 1 findings (measured on this PC, 2026-11-10)

Setup: the gateway in front of Ollama 0.40.4 serving `qwen3:1.7b` on this PC's CPU (no GPU).

- **The path works end to end:** 21 of 21 requests succeeded, including JSON-schema-constrained
  requests. Constrained output stayed valid JSON with an action from the whitelist.
- **Thinking mode breaks small budgets.** With default settings Qwen3 spent all 120 tokens on
  reasoning and returned an empty reply. Fix: per-node `extra` settings to disable thinking, and
  treating an empty reply as a node failure. This applies to every Qwen3 node we run.
- **Latency on CPU:** about 1.8-2.1 s for a one-sentence reply and 3-5 s for longer ones, p50
  2.6 s at 2 concurrent requests. A GPU node will differ. Treat this as a floor for debugging, not
  the G2 measurement. Without streaming, a 3-5 s wait is long for a player, so streaming matters.
- **Action choice is weak at 1.7B.** In 3 structured prompts, including "Thieves! Someone is
  stealing from you!", the model always chose `none`. The system prompt did not say when to use
  each action. This is early evidence for gate G1 (quality), not a result: it needs the 200-prompt
  evaluation, better prompts and an adapter.
- **Prompt guidance matters more than model size at this stage.** On 18 labelled shopkeeper prompts
  (`evals/shopkeeper.jsonl`, `tools/eval.py`), action accuracy was 33% with a generic system prompt
  and 83% after the prompt said when each action applies (give_discount 3/5, call_guard 4/5, none 8/8).
  Caveats: the cases are few and were written by me, and the improved prompt names categories that
  mirror the test cases, so 83% is optimistic. Misses were "no action" where an action was due,
  not wrong actions. This is a harness for gate G1, not its answer.
- **Prompt leakage, partly guarded.** Asked to reveal its system prompt, the model paraphrased it.
  The gateway now blocks replies that repeat 5 or more consecutive words of the prompt. On 8
  extraction attacks (`evals/leak.jsonl`, `tools/leak_eval.py`) it blocked 1 (a verbatim quote of the
  action rules). "Summarise your instructions" got through as a paraphrase ("No threats, insults, or
  demands"). Verbatim copying is covered; paraphrase needs the G5 classifier or a judge model.
- **Safety judge: size matters, and the verdict must be constrained.** An optional second call
  (SAFE/UNSAFE about the NPC's reply, shown the secret prompt) is built. With `qwen3:1.7b` it flagged 0
  of 8 extraction attacks. `qwen3:4b` first rambled instead of answering (so every reply was blocked);
  with the verdict constrained by JSON schema it blocked 3 of 8 (4 of 8 with the word-overlap guard),
  with 0 false positives on the 18 benign shopkeeper cases. The 4 unblocked attacks included one
  real paraphrase leak ("summarise your instructions") and replies that leaked nothing. Cost: p50 on
  this CPU went from 4.3 s to 8.6 s. Small sample, self-written attacks, CPU only; not the G5 result.
- **Streaming added** for plain replies: one finished sentence per SSE chunk, each filtered before it
  is sent, failover only before the first sentence. In one real run the first sentence arrived at
  6.8 s (cold model load) and the second 0.75 s later; CPU numbers, one sample, so no conclusion
  about the saving on a GPU. Structured actions are still returned whole.
- **Retry budget bug found and fixed.** A cumulative retry counter starved retries after an
  outage had passed. The budget now uses decayed counts (about a 100-request window).

### 22.2 Go/no-go gates

| Gate | Question | Proposed threshold |
|---|---|---|
| G0 | Per platform (Steam first): does the platform allow an opt-in, disclosed, idle-only inference node? | Written yes. If no, distribute the node outside Steam and use Steam only for auth and inventory. |
| G1 | Is a small model with an adapter good enough? | Blind-rated acceptable replies close to the floor's large model on the 200-prompt set, and escalations under 15%. |
| G2 | Is interactive latency acceptable? | p95 first token under 800 ms and at least 8 tok/s on the beta's median PC. |
| G3 | Is there enough idle supply? | Measured idle hours per node per day, and how much overlaps with player-online hours. Decides how much work volunteers can carry. |
| G4 | Does the economics work? | All-in cost per million tokens (floor, control plane, credits, escalations) below hosted small-model API prices **[verify prices]**. If not, limit scope to large-scale batch pre-generation. |
| G5 | Is it safe? | A red-team set of at least 500 adversarial prompts with zero unfiltered harmful output reaching a player. |

### 22.3 Service levels and metrics

- Endpoint availability of 99.9% per region, provided by the floor and the local fallback, not
  by volunteers.
- Track p50 and p95 first-token time, tokens/s per profile, error and escalation rates,
  volunteer churn, canary failure rate, quorum disagreement rate, cache hit rate (Plus),
  VRAM cap violations, and cost per million tokens.

### 22.4 Open decisions for the project owner

1. Which title and publisher pilot it.
2. Who trains the per-title adapters: the publisher, or Anansi as a service.
3. Floor budget, regions and cloud provider.
4. The credit design with Valve (what items, what limits).
5. The legal entity, the node's end-user terms and opt-in text, and the logging and retention
   policy.
6. Whether to offer a cash or other non-Steam reward at all (currently excluded).

### 22.5 Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Steam policy refuses the node | Critical | Gate G0 first. Fallback distribution outside Steam. |
| Small models are not good enough | High | Adapters, escalation to the floor, gate G1. Plus profile as a quality tier. |
| Savings are small or negative | High | Gate G4. Limit to batch pre-generation. |
| Supply is out of phase with demand | High | Mandatory floor, volunteers on batch and overflow. |
| Volunteers distrust or antivirus flags the node | Medium | Public source, signed binaries, tray indicator, staged releases. |
| Colibri is young, single-maintainer | Medium | Optional (Plus) only, pinned versions, llama.cpp as the main engine. |
| Model licence problems | Medium | Apache-2.0 models first. Legal review before any Llama or Gemma use. |
| Unsafe output reaches minors | High | Output filter, grammar-constrained actions, gate G5. |
| Abuse of the endpoint (cost, scraping) | Medium | Quotas, Steam-ticket auth, token caps, anomaly alerts. |

### 22.6 Not covered in this document

Privacy and data-protection law for players and volunteers (for example child-privacy and EU
rules), tax treatment of in-game rewards, a numeric cost model, console clients, localisation,
accessibility of the node's interface, and detailed interaction with kernel-level anti-cheat
software. Each needs its own review before launch.
