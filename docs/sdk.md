# SDKs

Both clients follow one contract: ask the gateway, and on a timeout, a `429`, an auth error or any failure, answer from
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

## Status

The C# SDK is tested as plain .NET against a live gateway (Windows PowerShell test and a `dotnet` test run in CI on
Ubuntu). The Unity `JsonUtility` branch and a real Unity project have not been run. There is no Unreal SDK; it would
follow the same contract over HTTP.
