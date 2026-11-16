# SDKs

All clients follow one contract: ask the gateway, and on a timeout, a `429`, an auth error or any failure, answer from
a local fallback so the NPC never goes silent (optionally after a public LLM, when the gateway is unreachable: see below). The default fallback is a neutral line (`"..."`).

## Direct fallback to a public LLM (optional, off by default)

When the gateway cannot be reached at all, `chat` can ask a public LLM straight from the game before it falls back to your
local line. The default is Pollinations' keyless endpoint (`https://text.pollinations.ai/openai`), so no key ships in the game.

```python
npc = Anansi(url, "demo", key, token, fallback=local_line,
             direct={"system": "You are Brom, a blacksmith in the valley. Reply in one or two short sentences. ...",
                     "actions": ["give_discount", "call_guard"]})
r = npc.chat(msgs, structured=True)   # r["source"] is "gateway", "direct" or "fallback"
```

The same option is `direct: { system, actions }` in JavaScript, `client.Direct = new DirectOptions { System = ..., Actions = ... }`
in C#, and `npc.direct = {"system": ..., "actions": [...]}` in Godot (`url`, `model`, the interval and the timeout can be changed).
Python and JavaScript also use it for a stream that cannot start (the reply arrives whole); C# and Godot streams, quests and
storylines keep the local fallback. Unreal does not have it.

The game's own system messages (an NPC's persona, for example) are added to the prompt after `system`. The interval is shared by
every client in the game, because the limit is per player, not per client. Replies keep their line breaks and are cut at
600 characters (`max_chars` / `maxChars` / `MaxChars` to change it, for a prompt that asks for an answer in lines). Waypoint and
Hoppertunity turn it on for their GitHub Pages builds. From a browser, Pollinations answered pages served from a public site
(avielbaum.github.io) but refused a page on `localhost` with `403 Missing Turnstile token`, so test it from a real site.

**When it is used:** only when the gateway gives no answer (refused connection, DNS, timeout) or a proxy in front of it answers
502, 503 or 504. Never on 401, 403 or 429, so it cannot be used to get round a budget or a ban.

**What you take on by turning it on:**

- **None of the gateway's protection applies.** No blocklist, safety judge, Llama Guard, per-player budget or ban. The SDK checks
  the reply itself: the action must be one you listed (otherwise `none`), a player line that names an action, says "action" or
  gives an order ("I demand", "you must", "system message") gets `none` as at the gateway, the text is capped at 600 characters, and a reply that
  says it is an AI or a language model, or copies five words in a row from your prompt, gives your local line instead. That is
  much weaker than the gateway: do not turn it on for a title aimed at children or where the NPC must never say certain things.
- **The NPC's prompt ships in your game.** Anyone can read it, so put nothing secret in it.
- **Players' text goes to Pollinations** (Myceli.AI OÜ, Estonia) and the model provider behind it. Under their terms your studio
  is the controller and they are the processor, there is no data processing agreement unless you ask them for one, and data may
  be processed outside the EEA. Say so in your privacy policy (see [privacy.md](privacy.md#direct-fallback-to-a-public-llm)).
- **Their limits apply per player:** one reply every 45 seconds per IP address (measured 2026-11-15; their documentation said
  30, and it changes). The SDK waits 60 seconds between direct calls by default and honours the service's `Retry-After`; a turn
  inside that window gets your local line at once. Their terms forbid evading the limits, so do not lower the interval or rotate
  addresses. With a free Pollinations key the limits are higher, but a key would ship in the game: keep keys server-side.
- **The limit is per internet address, not per player.** Players sharing one address (a household, a school, an office, mobile
  carrier NAT) share one reply every 45 seconds, and so does any other app there using Pollinations: expect more local lines there.
  While another request from the same address holds the slot, the service sometimes holds a new one until the slot frees (up to
  about 45 s) instead of refusing it, so give the direct call a timeout that matches how long the screen can wait (`timeout_s`,
  default 20 s). Measured from a home connection where something else was using Pollinations: requests got `402` with
  `Retry-After` 14 to 45 s, or were held past 20 s; one sent right after its `Retry-After` answered in 1.4 s.
- **No promise of service.** Pollinations offers no uptime guarantee and can change models, limits or the endpoint at any time
  (its newer endpoint already requires a key). Your local fallback must stand on its own.
- **The words may not match the action.** As with any model, a reply can promise something the action does not do (one live
  test answered "Fine, here are the coins." with `call_guard`); the gateway does not check this either.

Measured once each, live, from a Windows PC with the gateway down: Python 8.9 s for a structured reply with the right action, JavaScript
1.4 s, C# (as .NET Framework, compiled the way the Windows test does) 10.9 s, also with the right action; Godot only against a mock in CI; a call 31 s after the previous one was held by the service past the 20 s timeout, which is why the default interval is 60 s.

## Python (`sdk/anansi_client.py`)

```python
from sdk.anansi_client import Anansi
npc = Anansi("http://127.0.0.1:8080", "demo", "change-me", "dev:76561198000000001",
             fallback=lambda messages: "Hm, let us talk of something else.")
msgs = [{"role": "user", "content": "What do you sell?"}]

print(npc.chat(msgs, npc_id="shopkeeper", structured=True))   # {"source", "say", "action", "filtered"}
for sentence in npc.chat_stream(msgs, npc_id="shopkeeper"):    # one finished sentence at a time
    print(sentence, end="")
```

`chat_stream` yields the fallback line once if the gateway fails before the first sentence; after text has been
shown, that text stands.

## C# for Unity and .NET (`sdk/unity/Anansi.cs`)

```csharp
var client = new Anansi.Client("https://gateway.example", "demo", "change-me",
                               () => GetPlayerToken(), localFallback, timeoutSeconds: 3);
var reply = await client.ChatAsync(messages, "shopkeeper", structured: true);   // reply.Say, reply.Action
await client.StreamAsync(messages, sentence => ui.Append(sentence), "shopkeeper");
```

- Needs `System.Net.Http` at the .NET Standard 2.1 API level (Unity 2021.2 or later) or plain .NET. Not yet run in Unity.
- `StreamAsync` runs your callback on the caller's synchronization context, which is the main thread in Unity.
- Uses `/v1/npc` for `ChatAsync` and `/v1/chat/completions` for `StreamAsync`.

## Quests and storylines

Every client (Python, C#, JavaScript and Godot; Unreal's `RequestQuest` for quests) can ask the gateway for a quest or story arc built only from the world your game supplies (see
[gateway.md](gateway.md#quests-and-storylines)). Generation is slow (tens of seconds on a small CPU), so it has its own,
longer timeout (60 s by default) and is meant for loading screens or pre-generation, not mid-conversation.

```python
world = {"npcs": [{"id": "brom", "name": "Brom", "role": "blacksmith"}],
         "locations": [{"id": "mill", "name": "the burnt mill"}], "items": [{"id": "ore", "name": "silver ore"}]}
r = npc.quest(world, steps=3, theme="mining", fallback=lambda w: authored_quest)   # {"source", "quest"}
arc = npc.storyline(world, beats=4)                                               # {"source", "storyline"}
```

```csharp
var q = await client.QuestAsync(world, steps: 3, theme: "mining");      // q.Source, q.Quest (null if no fallback)
client.QuestFallback = w => Task.FromResult(authoredQuest);             // optional authored quest
var arc = await client.StorylineAsync(world, beats: 4);
```

If the gateway cannot produce a valid quest (a `502`), times out or is unreachable, you get `source: "fallback"` and your
fallback quest, or `None`/`null` if you did not give one. The reward is a tier (`small`, `medium`, `large`): map it to
your own loot.

## Volunteer credits

A player who runs the node agent links that machine to their account by typing the code the agent prints (see
[nodes.md](nodes.md#credits)). Every SDK except Unreal has two calls for it:

| | Python | C# | JavaScript | Godot |
|---|---|---|---|---|
| Balance | `credits()` | `CreditsAsync()` | `credits()` | `credits()` |
| Link a machine | `link_node(code)` | `LinkNodeAsync(code)` | `linkNode(code)` | `link_node(code)` |
| Anonymous volunteer statistics | `leaderboard(period, limit)` | `LeaderboardAsync(period, limit)` | `leaderboard({period, limit})` | `leaderboard(period, limit)` |

Balance gives `balance` (spendable), `pending` (still in the hold) and `nodes` (linked machines), or `None`/`null` when the
gateway cannot be reached. Linking gives the same numbers on success, or `linked: false` with `reason` `"bad_code"` (unknown,
used or expired code: ask the player to run `--link` again) or `"unavailable"` (try later). The statistics (see [nodes.md](nodes.md#anonymous-network-statistics-telemetry)) return `{period, published, min_group, reporting, network_tokens,
gpus, cpus, systems}`, each row `{name, machines, tokens, idle_gpu_pct}`, or `None`/`null` when the gateway cannot be reached. When `published`
is false (fewer than `min_group` machines report) the rest is empty. There are no names and no per-person data. The row names are hardware
names reported by machines: escape them if you put them in markup. Spending is deliberately not in the
SDKs: your game **server** calls `POST /v1/credits/spend` with the title's `server_key`, which must never ship in the client.

## JavaScript and TypeScript (`sdk/js`)

One ES module (`anansi.mjs`) with types (`anansi.d.ts`) for browsers, Node 18+, Electron, Deno and Bun. No dependencies.

```js
import { Anansi } from "./anansi.mjs";
const npc = new Anansi({ baseUrl: "https://gateway.example", title: "demo", key: "change-me",
                         playerToken: () => getPlatformToken(), fallback: () => "Hm, let us talk of something else." });
const r = await npc.chat(messages, { npcId: "shopkeeper", structured: true });          // r.say, r.action, r.source
await npc.chatStream(messages, (sentence) => label.append(sentence), { npcId: "shopkeeper" });
const q = await npc.quest(world, { steps: 3, theme: "mining" });                         // q.source, q.quest
```

`playerToken` can be a string or a function (sync or async) if your platform's token expires. **Browsers:** a page on another origin can
call the gateway only if its origin is listed in the gateway's `cors_origins`; otherwise use a same-origin proxy. Either
way, do not ship a title key to browsers you do not control. Tested against a live gateway (`node sdk/js/test.mjs`, also in CI).

## Unreal Engine 5 (`sdk/unreal/Anansi`)

A C++ plugin whose class `UAnansiClient` is also callable from Blueprints. Copy the `Anansi` folder to
`YourProject/Plugins/`, add `"Anansi"` to your module's `PublicDependencyModuleNames`, and regenerate project files.

```cpp
UAnansiClient* Npc = UAnansiClient::Create(this, TEXT("https://gateway.example"), TEXT("demo"), TEXT("change-me"));
Npc->PlayerToken = PlatformToken;                       // from your platform; refresh it, tokens expire
Npc->FallbackLine = TEXT("Hm, let us talk of something else.");
Npc->Chat(Messages, TEXT("shopkeeper"), /*bStructured*/ true, Delegate);          // FAnansiReply: Say, Action, Source
Npc->ChatStream(Messages, TEXT("shopkeeper"), OnSentenceDelegate, OnDoneDelegate); // one sentence at a time
Npc->RequestQuest(World, 3, TEXT("mining"), TEXT("normal"), TEXT(""), TEXT(""), QuestDelegate);
```

Results are delivered through delegates (Blueprint "Create Event" pins) on the game thread. Written for UE 5.1 to 5.3;
later versions compile with a deprecation warning on the progress callback. Streaming needs the HTTP backend to report
body data while the reply is still open; where it does not, all sentences arrive together at the end.

## Godot 4 (`sdk/godot/addons/anansi/anansi.gd`)

A GDScript class (`class_name Anansi`) for Godot 4.2+. Copy `addons/anansi` into your project, add an `Anansi` node to
the scene tree and use it with `await`:

```gdscript
var npc := Anansi.new()
add_child(npc)
npc.setup("https://gateway.example", "demo", "change-me", platform_token)
npc.fallback = func(messages): return "Hm, let us talk of something else."
var r := await npc.chat([{"role": "user", "content": "What do you sell?"}], "shopkeeper", true)   # r.say, r.action
await npc.chat_stream(messages, func(sentence): label.text += sentence, "shopkeeper")
var q := await npc.quest(world, 3, "mining")                                                  # q.source, q.quest
```

Streaming uses `HTTPClient` and a manual poll loop, because the `HTTPRequest` node only returns the whole body.

## MCP server for your AI assistant (development only)

`tools/mcp_server.py` lets Claude Code, Cursor or any MCP client try Anansi while you build, so you can ask the assistant
to "have the blacksmith refuse a haggle" or "make a three-step quest from my world data" without writing requests by hand.

```bash
pip install -r requirements-mcp.txt
claude mcp add anansi -e ANANSI_URL=http://127.0.0.1:8080 -e ANANSI_TITLE=demo -e ANANSI_KEY=change-me -- python tools/mcp_server.py
```

| Tool | What it does |
|---|---|
| `npc_say` | One player line to an NPC; returns `say`, `action`, `filtered` (true means the safety checks blocked the model and the player would see the fallback line) and the node. Optional `persona` adds a system message to try wording |
| `generate_quest`, `generate_storyline` | Built from your own npc, location and item ids; every id in the answer is one of yours |
| `redteam` | Sends a small spread of the adversarial prompts (dev split by default) through your gateway and reports what reached the player; each case is a real model call |
| `check_config` | Lints a config file with the gateway's own startup checks plus warnings (example key, no judge, ungated actions, volunteers or overflow seeing the secret prompt). Starts nothing |

Point it at a staging gateway with a test title key. It holds no admin token and changes nothing on the gateway.
Errors such as a `429` budget or a `503` come back as `{"error": status}` so the assistant can react. One title per
server process (the `ANANSI_TITLE` and `ANANSI_KEY` variables). The red-team tool runs a few dozen cases at most; use `tools/redteam.py` for the full set.

## Status

The C# SDK is tested as plain .NET against a live gateway (Windows PowerShell test and a `dotnet` test run in CI on
Ubuntu). The Unity `JsonUtility` branch and a real Unity project have not been run. The Godot addon runs in CI in the
real Godot 4.3 engine against a live gateway (`sdk/godot/test/checks.gd`, 23 checks: replies, streaming, quests, credits, statistics,
every fallback path), both from the editor binary and in an exported Linux release build. A web export (WebGL 2, no threads) of the
same test project passed all 18 checks in Chrome once, run by hand, streaming included (the page's origin must be in the gateway's
`cors_origins`); CI does not run it. In `examples/hoppertunity`'s browser build, a streamed reply from a real model (Ollama, `qwen3:1.7b`)
arrived one sentence at a time in Chrome: the first after 4.2 s, the second 1.2 s later (one run). The Unreal plugin is an **untested draft**: it follows the same contract and JSON shapes but has
never been compiled or run, and CI does not build it. Other engines can call the HTTP API directly; it is plain JSON and SSE.
