# SDKs

All clients follow one contract: ask the gateway, and on a timeout, a `429`, an auth error or any failure, answer from
a local fallback so the NPC never goes silent. The default fallback is a neutral line (`"..."`).

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

- Targets Unity 2019.1+ (needs `System.Net.Http`, so Unity 2021+ or the .NET Standard 2.1 API level) and plain .NET.
- `StreamAsync` runs your callback on the caller's synchronization context, which is the main thread in Unity.
- Uses `/v1/npc` for `ChatAsync` and `/v1/chat/completions` for `StreamAsync`.

## Quests and storylines

Both clients can ask the gateway for a quest or story arc built only from the world your game supplies (see
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
real Godot 4.3 engine against a live gateway (`sdk/godot/test/checks.gd`, 18 checks: replies, streaming, quests, credits, statistics,
every fallback path), both from the editor binary and in an exported Linux release build. A web export (WebGL 2, no threads) of the
same test project passed all 18 checks in Chrome once, run by hand, streaming included (the page's origin must be in the gateway's
`cors_origins`); CI does not run it, and whether streamed sentences arrive one at a time in a browser was not measured. The Unreal plugin is an **untested draft**: it follows the same contract and JSON shapes but has
never been compiled or run, and CI does not build it. Other engines can call the HTTP API directly; it is plain JSON and SSE.
