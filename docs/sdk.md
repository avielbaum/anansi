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

`playerToken` can be a string or a function (sync or async) if your platform's token expires. **Browsers:** the gateway
sends no CORS headers yet, so a page on another origin cannot call it directly; use a same-origin proxy, and do not
ship a title key to browsers you do not control. Tested against a live gateway (`node sdk/js/test.mjs`, also in CI).

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

## Status

The C# SDK is tested as plain .NET against a live gateway (Windows PowerShell test and a `dotnet` test run in CI on
Ubuntu). The Unity `JsonUtility` branch and a real Unity project have not been run. The Unreal plugin and the Godot addon are
**untested drafts**: they follow the same contract and the same JSON shapes, but have never been compiled or run in
their engines, and CI does not build them. Other engines can call the HTTP API directly; it is plain JSON and SSE.
