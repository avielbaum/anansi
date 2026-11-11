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
                               () => GetSteamWebTicketHex(), localFallback, timeoutSeconds: 3);
var reply = await client.ChatAsync(messages, "shopkeeper", structured: true);   // reply.Say, reply.Action
await client.StreamAsync(messages, sentence => ui.Append(sentence), "shopkeeper");
```

- Targets Unity 2019.1+ (needs `System.Net.Http`, so Unity 2021+ or the .NET Standard 2.1 API level) and plain .NET.
- `StreamAsync` runs your callback on the caller's synchronization context, which is the main thread in Unity.
- Uses `/v1/npc` for `ChatAsync` and `/v1/chat/completions` for `StreamAsync`.

## Status

The C# SDK is tested as plain .NET against a live gateway (Windows PowerShell test and a `dotnet` test run in CI on
Ubuntu). The Unity `JsonUtility` branch and a real Unity project have not been run. There is no Unreal SDK; it would
follow the same contract over HTTP.
