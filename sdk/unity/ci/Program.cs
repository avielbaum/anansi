// Linux/macOS/Windows counterpart of test_sdk.ps1. Needs a gateway on 127.0.0.1:8080 backed by the mock nodes
// (the CI workflow starts them). Run: dotnet run --project sdk/unity/ci
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Anansi;

static class Program
{
    static int failures;
    static void Check(bool ok, string msg) { Console.WriteLine((ok ? "PASS " : "FAIL ") + msg); if (!ok) failures++; }

    static int Main()
    {
        var msgs = new List<Message> { new Message { role = "user", content = "hello" } };
        Func<string> ticket = () => "dev:76561198000000001";
        Func<List<Message>, Task<string>> fb = m => Task.FromResult("(local line)");
        var got = new List<string>();
        Action<string> on = s => { lock (got) got.Add(s); };
        var url = "http://127.0.0.1:8080";

        var c = new Client(url, "demo", "change-me", ticket, fb, 3);
        var r = c.ChatAsync(msgs, "smith", false).GetAwaiter().GetResult();
        Check(r.Source == "gateway" && r.Say.EndsWith("hello"), "gateway reply (" + r.Say + ")");

        var bad = new Client(url, "demo", "WRONG", ticket, fb, 3);
        r = bad.ChatAsync(msgs, "smith", false).GetAwaiter().GetResult();
        Check(r.Source == "fallback" && r.Say == "(local line)", "bad key falls back");

        r = c.StreamAsync(msgs, on, "smith").GetAwaiter().GetResult();
        Check(r.Source == "gateway" && got.Count >= 1 && string.Join("", got).EndsWith("hello") && r.Say == string.Join("", got), "stream delivers sentences");
        got.Clear();
        r = bad.StreamAsync(msgs, on, "smith").GetAwaiter().GetResult();
        Check(r.Source == "fallback" && got.Count == 1 && got[0] == "(local line)", "stream falls back once on bad key");

        var w = new World();
        w.npcs.Add(new Entity { id = "brom", name = "Brom", role = "blacksmith" });
        w.locations.Add(new Entity { id = "mill", name = "Old Mill" });
        w.items.Add(new Entity { id = "ore", name = "Iron ore" });
        var q = c.QuestAsync(w, 2, "mining").GetAwaiter().GetResult();
        Check(q.Source == "gateway" && q.Quest.steps.Count >= 1 && q.Quest.steps[0].target_id == "brom", "quest from gateway uses a world id");
        var arc = c.StorylineAsync(w, 3).GetAwaiter().GetResult();
        Check(arc.Source == "gateway" && arc.Storyline.beats.Count >= 1, "storyline from gateway");
        q = bad.QuestAsync(w, 2).GetAwaiter().GetResult();
        Check(q.Source == "fallback" && q.Quest == null, "quest with bad key: no quest");
        bad.QuestFallback = x => Task.FromResult(new Quest { title = "Authored", steps = new List<QuestStep>() });
        q = bad.QuestAsync(w, 2).GetAwaiter().GetResult();
        Check(q.Source == "fallback" && q.Quest.title == "Authored", "quest fallback supplies an authored quest");

        var none = new Client(url, "demo", "change-me", ticket, null, 1);
        got.Clear();
        r = new Client("http://127.0.0.1:9", "demo", "change-me", ticket, fb, 1).StreamAsync(msgs, on).GetAwaiter().GetResult();
        Check(r.Source == "fallback" && got.Count == 1, "stream with gateway unreachable falls back");
        r = new Client("http://127.0.0.1:9", "demo", "change-me", ticket, null, 1).ChatAsync(msgs).GetAwaiter().GetResult();
        Check(r.Source == "fallback" && r.Say == "...", "default fallback line");
        return failures == 0 ? 0 : 1;
    }
}
