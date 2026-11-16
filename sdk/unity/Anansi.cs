// Anansi game SDK for Unity (2019.1+) and plain .NET. Contract matches sdk/anansi_client.py:
// ask the gateway, and on timeout, 429 or any failure answer from your local fallback so the game never stalls.
// Needs "System.Net.Http" (Unity 2021+ or .NET Standard 2.1 API level). Keep C# 5-compatible so the test harness compiles it.
using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
#if UNITY_2019_1_OR_NEWER
using UnityEngine;
#else
using System.Runtime.Serialization.Json;
#endif

namespace Anansi
{
    [Serializable] public class Message { public string role; public string content; }
    [Serializable] public class NpcRequest { public string npc_id; public bool structured; public List<Message> messages; }
    [Serializable] public class NpcResponse { public string say; public string action; public bool filtered; public string node; }

    // Streaming request and chunk shapes (OpenAI-style SSE from /v1/chat/completions with stream: true).
    [Serializable] public class Meta { public string npc_id; }
    [Serializable] public class StreamRequest { public bool stream; public Meta anansi; public List<Message> messages; }
    // [OptionalField]: the .NET serializer treats fields of [Serializable] types as required, and chunks omit some of them.
    [Serializable] public class Delta { [System.Runtime.Serialization.OptionalField] public string content; }
    [Serializable] public class Choice { [System.Runtime.Serialization.OptionalField] public Delta delta; }
    [Serializable] public class ChunkMeta { [System.Runtime.Serialization.OptionalField] public bool filtered; }
    [Serializable] public class Chunk
    {
        [System.Runtime.Serialization.OptionalField] public List<Choice> choices;
        [System.Runtime.Serialization.OptionalField] public ChunkMeta anansi; // in the first or last chunk: did the gateway replace unsafe text
    }

    // Quest and storyline generation (POST /v1/quest, /v1/storyline). Send the world your game already has.
    [Serializable] public class Entity { public string id; public string name; public string role; }
    [Serializable] public class World { public List<Entity> npcs = new List<Entity>(); public List<Entity> locations = new List<Entity>(); public List<Entity> items = new List<Entity>(); }
    [Serializable] public class QuestStep { public string objective; public string target_id; public string description; }
    [Serializable] public class Quest { public string title; public string summary; public List<QuestStep> steps; public string reward_tier; public string story_summary; }
    [Serializable] public class Beat { public string title; public string summary; public string npc_id; public string location_id; }
    [Serializable] public class Storyline { public string logline; public List<Beat> beats; }
    [Serializable] public class GenRequest { public World world; public int steps; public string theme; public string difficulty; public string story_so_far; public string player; }
    [Serializable] public class QuestEnvelope { public Quest quest; }
    [Serializable] public class StoryEnvelope { public Storyline storyline; }
    public class QuestResult { public Quest Quest; public string Source; }      // Source: "gateway" or "fallback"; Quest is null on fallback unless you set QuestFallback
    public class StorylineResult { public Storyline Storyline; public string Source; }

    // Volunteer credits (GET /v1/credits, POST /v1/credits/link). Spending is not here: only your game server may spend.
    [Serializable] public class Credits { public double balance; public double pending; public int nodes; }
    [Serializable] public class LinkRequest { public string code; }
    public class LinkResult
    {
        public bool Linked;
        public string Reason;    // when not linked: "bad_code" (unknown, used or expired) or "unavailable"
        public Credits Credits;  // the player's credits after linking
    }

    // The anonymous volunteer-network statistics (GET /v1/leaderboard). Hardware names come from outside: escape them in markup.
    [Serializable] public class BoardRow { public string name; public int machines; public long tokens; public double? idle_gpu_pct; }
    [Serializable] public class BoardReporting { public int machines; public long tokens; public double? idle_gpu_pct; }
    [Serializable] public class Leaderboard { public string period; public bool published; public int min_group; public BoardReporting reporting; public long network_tokens; public List<BoardRow> gpus; public List<BoardRow> cpus; public List<BoardRow> systems; }  // published is false, and the rest empty, until min_group machines report

    public class Reply
    {
        public string Say;
        public string Action;    // one of the title's whitelisted actions, or "none"
        public bool Filtered;    // the gateway replaced unsafe text
        public string Source;    // "gateway", "direct" (the public LLM below) or "fallback"
    }

    // Direct fallback (off unless Client.Direct is set): when the gateway cannot be reached, ChatAsync asks a public LLM
    // straight from the game. Default is Pollinations' keyless endpoint, which allows one reply per player IP every 45 s
    // (measured 2026-11-15; it changes); calls are spaced 60 s apart by default and its Retry-After is honoured (their terms
    // forbid evading limits). None of the gateway's checks run there, so CheckDirect checks the reply. The prompt ships in
    // your game and the player's text goes to that service: read docs/sdk.md before turning it on.
    public class DirectOptions
    {
        public const string PollinationsUrl = "https://text.pollinations.ai/openai";
        public string System;                                  // the NPC's prompt (required)
        public List<string> Actions = new List<string>();      // actions the reply may pick; anything else becomes "none"
        public string Url = PollinationsUrl;
        public string Model = "openai";
        public double MinIntervalSeconds = 60;
        public double TimeoutSeconds = 20;
        public int MaxTokens = 400;
        public int MaxChars = 600;                             // longest reply passed to the player
    }
    [Serializable] public class DirectRequest { public string model; public int max_tokens; public List<Message> messages; }
    [Serializable] public class DirectMessage { [System.Runtime.Serialization.OptionalField] public string content; }
    [Serializable] public class DirectChoice { [System.Runtime.Serialization.OptionalField] public DirectMessage message; }
    [Serializable] public class DirectResponse { [System.Runtime.Serialization.OptionalField] public List<DirectChoice> choices; }
    [Serializable] public class DirectSay { [System.Runtime.Serialization.OptionalField] public string say; [System.Runtime.Serialization.OptionalField] public string action; }

    public class Client
    {
        readonly HttpClient http, genHttp;
        /// <summary>Supplies an authored quest when the gateway cannot (optional). Without it QuestResult.Quest is null.</summary>
        public Func<World, Task<Quest>> QuestFallback;
        public Func<World, Task<Storyline>> StorylineFallback;
        readonly string url, chatUrl, baseUrlTrimmed, title, key;
        readonly Func<string> playerToken;
        readonly TimeSpan streamTimeout;
        readonly Func<List<Message>, Task<string>> fallback;

        // playerToken: return the player's proof of identity from your platform (on Steam, the hex web-API auth ticket).
        // fallback: answer locally, for example from a bundled llama.cpp server. Default is a neutral line.
        public Client(string baseUrl, string titleId, string titleKey, Func<string> playerToken,
                      Func<List<Message>, Task<string>> fallback = null, double timeoutSeconds = 3,
                      double generationTimeoutSeconds = 60, double streamTimeoutSeconds = 30)
        {
            streamTimeout = TimeSpan.FromSeconds(streamTimeoutSeconds); // a whole streamed reply once it has started
            http = new HttpClient { Timeout = TimeSpan.FromSeconds(timeoutSeconds) };
            genHttp = new HttpClient { Timeout = TimeSpan.FromSeconds(generationTimeoutSeconds) }; // generation is slow: tens of seconds on a small GPU
            url = baseUrl.TrimEnd('/') + "/v1/npc";
            chatUrl = baseUrl.TrimEnd('/') + "/v1/chat/completions";
            baseUrlTrimmed = baseUrl.TrimEnd('/');
            title = titleId; key = titleKey; this.playerToken = playerToken; this.fallback = fallback;
        }

        // Plain (unstructured) replies, one finished sentence at a time: onSentence runs for each sentence as it arrives.
        // If the gateway fails or times out before the first sentence, onSentence gets the fallback line once.
        // If it fails after text was shown, that text stands. No ConfigureAwait(false) in the read loop on purpose:
        // in Unity the callback then runs on the main thread. Structured actions use ChatAsync.
        public async Task<Reply> StreamAsync(List<Message> messages, Action<string> onSentence, string npcId = null)
        {
            var said = new StringBuilder();
            var filtered = false;
            var cts = new CancellationTokenSource();
            cts.CancelAfter(http.Timeout); // covers the wait for the first sentence; then streamTimeout covers the rest
            try
            {
                var body = new StreamRequest { stream = true, anansi = new Meta { npc_id = npcId }, messages = messages };
                var req = new HttpRequestMessage(HttpMethod.Post, chatUrl)
                {
                    Content = new StringContent(Json.To(body), Encoding.UTF8, "application/json")
                };
                req.Headers.Add("X-Anansi-Title", title);
                req.Headers.Add("X-Anansi-Key", key);
                req.Headers.Add("X-Player-Token", playerToken());
                using (var resp = await http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cts.Token))
                {
                    if (resp.IsSuccessStatusCode)
                    {
                        cts.Token.Register(() => { try { resp.Dispose(); } catch (Exception) { } }); // unblocks a stalled read
                        using (var reader = new StreamReader(await resp.Content.ReadAsStreamAsync()))
                        {
                            string line;
                            while ((line = await reader.ReadLineAsync()) != null)
                            {
                                if (!line.StartsWith("data: {")) continue;
                                if (line.StartsWith("data: {\"error\"")) break; // gateway could not serve the stream
                                var c = Json.From<Chunk>(line.Substring(6));
                                if (c.anansi != null && c.anansi.filtered) filtered = true;
                                if (c.choices == null || c.choices.Count == 0 || c.choices[0].delta == null) continue;
                                var text = c.choices[0].delta.content;
                                if (string.IsNullOrEmpty(text)) continue;
                                if (said.Length == 0) cts.CancelAfter(streamTimeout); // a dropped connection cannot hang the NPC
                                said.Append(text);
                                onSentence(text);
                            }
                        }
                    }
                }
            }
            catch (Exception) { } // timeout, dropped connection, bad JSON
            cts.Dispose();
            if (said.Length > 0) return new Reply { Say = said.ToString(), Action = "none", Filtered = filtered, Source = "gateway" };
            var say = fallback != null ? await fallback(messages) : "...";
            onSentence(say);
            return new Reply { Say = say, Action = "none", Filtered = false, Source = "fallback" };
        }

        // One quest that can only use the characters, places and items in `world`. The reward comes back as a tier
        // (small, medium, large): map it to your own loot. Feed quest.story_summary back as storySoFar to continue a story.
        public async Task<QuestResult> QuestAsync(World world, int steps = 3, string theme = null,
                                                  string difficulty = "normal", string storySoFar = null, string player = null)
        {
            var env = await Generate<QuestEnvelope>("quest", world, steps, theme, difficulty, storySoFar, player);
            if (env != null && env.quest != null) return new QuestResult { Quest = env.quest, Source = "gateway" };
            return new QuestResult { Quest = QuestFallback != null ? await QuestFallback(world) : null, Source = "fallback" };
        }

        public async Task<StorylineResult> StorylineAsync(World world, int beats = 4, string theme = null)
        {
            var env = await Generate<StoryEnvelope>("storyline", world, beats, theme, "normal", null, null);
            if (env != null && env.storyline != null) return new StorylineResult { Storyline = env.storyline, Source = "gateway" };
            return new StorylineResult { Storyline = StorylineFallback != null ? await StorylineFallback(world) : null, Source = "fallback" };
        }

        async Task<T> Generate<T>(string kind, World world, int steps, string theme, string difficulty, string story, string player) where T : class
        {
            try
            {
                var body = new GenRequest { world = world, steps = steps, theme = theme ?? "", difficulty = difficulty ?? "normal",
                                            story_so_far = story ?? "", player = player ?? "" };
                var req = new HttpRequestMessage(HttpMethod.Post, baseUrlTrimmed + "/v1/" + kind)
                {
                    Content = new StringContent(Json.To(body), Encoding.UTF8, "application/json")
                };
                req.Headers.Add("X-Anansi-Title", title);
                req.Headers.Add("X-Anansi-Key", key);
                req.Headers.Add("X-Player-Token", playerToken());
                using (var resp = await genHttp.SendAsync(req).ConfigureAwait(false))
                    if (resp.IsSuccessStatusCode)
                        return Json.From<T>(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
            }
            catch (Exception) { } // timeout, 502 (no valid quest), bad JSON: the caller falls back
            return null;
        }

        HttpRequestMessage Req(HttpMethod method, string path, string json)
        {
            var req = new HttpRequestMessage(method, baseUrlTrimmed + path);
            if (json != null) req.Content = new StringContent(json, Encoding.UTF8, "application/json");
            req.Headers.Add("X-Anansi-Title", title);
            req.Headers.Add("X-Anansi-Key", key);
            req.Headers.Add("X-Player-Token", playerToken());
            return req;
        }

        // The anonymous volunteer-network statistics ("day", "week" or "all"), or null when the gateway cannot be reached.
        public async Task<Leaderboard> LeaderboardAsync(string period = "week", int limit = 20)
        {
            try
            {
                using (var resp = await http.SendAsync(Req(HttpMethod.Get, "/v1/leaderboard?period=" + Uri.EscapeDataString(period) + "&limit=" + limit, null)).ConfigureAwait(false))
                    if (resp.IsSuccessStatusCode)
                        return Json.From<Leaderboard>(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
            }
            catch (Exception) { }
            return null;
        }

        // This player's volunteer credits, or null when the gateway cannot be reached.
        public async Task<Credits> CreditsAsync()
        {
            try
            {
                using (var resp = await http.SendAsync(Req(HttpMethod.Get, "/v1/credits", null)).ConfigureAwait(false))
                    if (resp.IsSuccessStatusCode)
                        return Json.From<Credits>(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
            }
            catch (Exception) { }
            return null;
        }

        // Link the machine that printed `code` (the node agent's --link, e.g. ABCD-EFGH) to this player.
        public async Task<LinkResult> LinkNodeAsync(string code)
        {
            try
            {
                var body = Json.To(new LinkRequest { code = code ?? "" });
                using (var resp = await http.SendAsync(Req(HttpMethod.Post, "/v1/credits/link", body)).ConfigureAwait(false))
                {
                    if (resp.IsSuccessStatusCode)
                        return new LinkResult { Linked = true, Credits = Json.From<Credits>(await resp.Content.ReadAsStringAsync().ConfigureAwait(false)) };
                    var s = (int)resp.StatusCode;
                    if (s == 400 || s == 404) return new LinkResult { Linked = false, Reason = "bad_code" };
                }
            }
            catch (Exception) { }
            return new LinkResult { Linked = false, Reason = "unavailable" };
        }

        public async Task<Reply> ChatAsync(List<Message> messages, string npcId = null, bool structured = false)
        {
            var gone = false; // no answer at all, or 502-504 from a proxy in front of it; 401, 403 and 429 are answers
            try
            {
                var body = new NpcRequest { npc_id = npcId, structured = structured, messages = messages };
                var req = new HttpRequestMessage(HttpMethod.Post, url)
                {
                    Content = new StringContent(Json.To(body), Encoding.UTF8, "application/json")
                };
                req.Headers.Add("X-Anansi-Title", title);
                req.Headers.Add("X-Anansi-Key", key);
                req.Headers.Add("X-Player-Token", playerToken());
                using (var resp = await http.SendAsync(req).ConfigureAwait(false))
                {
                    if (resp.IsSuccessStatusCode)
                    {
                        var r = Json.From<NpcResponse>(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
                        return new Reply { Say = r.say, Action = r.action ?? "none", Filtered = r.filtered, Source = "gateway" };
                    }
                    var code = (int)resp.StatusCode;
                    gone = code >= 502 && code <= 504;
                }
            }
            catch (HttpRequestException) { gone = true; }   // DNS, refused, TLS
            catch (TaskCanceledException) { gone = true; }  // timeout
            catch (Exception) { }                           // bad JSON: the gateway answered, so no direct call
            if (gone && Direct != null)
            {
                var d = await DirectAsync(messages, structured).ConfigureAwait(false);
                if (d != null) return d;
            }
            var say = fallback != null ? await fallback(messages).ConfigureAwait(false) : "...";
            return new Reply { Say = say, Action = "none", Filtered = false, Source = "fallback" };
        }

        /// <summary>Off unless set: the public LLM ChatAsync asks when the gateway cannot be reached (see DirectOptions).</summary>
        public DirectOptions Direct;
        static DateTime nextDirect = DateTime.MinValue; // shared by every client: the free limit is per player IP, not per client

        async Task<Reply> DirectAsync(List<Message> messages, bool structured)
        {
            var c = Direct;
            if (c == null || c.System == null || DateTime.UtcNow < nextDirect) return null;
            nextDirect = DateTime.UtcNow.AddSeconds(c.MinIntervalSeconds);
            var actions = c.Actions ?? new List<string>();
            var own = new List<string>(); // the game's NPC persona, after the base prompt
            foreach (var m in messages) if (m.role == "system") own.Add(m.content);
            var prompt = c.System + (own.Count > 0 ? "\n" + string.Join("\n", own.ToArray()) : "");
            var system = prompt;
            if (structured)
            {
                var opts = new List<string>();
                foreach (var a in actions) opts.Add("\"" + a + "\"");
                opts.Add("\"none\"");
                system += " Reply with only a JSON object, no other text, shaped like this: {\"say\": \"<what you say>\", \"action\": " + string.Join(" | ", opts.ToArray()) + "}";
            }
            var keep = messages.FindAll(m => m.role == "user" || m.role == "assistant");
            var msgs = new List<Message> { new Message { role = "system", content = system } };
            msgs.AddRange(keep.GetRange(Math.Max(0, keep.Count - 8), Math.Min(8, keep.Count)));
            try
            {
                var body = new DirectRequest { model = c.Model, max_tokens = c.MaxTokens, messages = msgs };
                using (var cts = new CancellationTokenSource(TimeSpan.FromSeconds(c.TimeoutSeconds)))
                using (var resp = await genHttp.PostAsync(c.Url, new StringContent(Json.To(body), Encoding.UTF8, "application/json"), cts.Token).ConfigureAwait(false))
                {
                    if ((int)resp.StatusCode == 402) // over the free limit: wait as long as the service says
                    {
                        var ra = resp.Headers.RetryAfter;
                        nextDirect = DateTime.UtcNow.AddSeconds(ra != null && ra.Delta.HasValue ? ra.Delta.Value.TotalSeconds : 60);
                    }
                    if (!resp.IsSuccessStatusCode) return null;
                    var r = Json.From<DirectResponse>(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
                    var ok = CheckDirect(r.choices[0].message.content, prompt, actions, structured, c.MaxChars);
                    if (ok == null) return null;
                    return new Reply { Say = ok[0], Action = ok[1], Filtered = false, Source = "direct" };
                }
            }
            catch (Exception) { return null; }
        }

        static readonly Regex AiTalk = new Regex(@"\b(i am|i'm|as) (just |only )?an? (ai|a\.i\.|llm|chatbot|language model|artificial intelligence|(computer )?program|software|bot)\b|\blanguage model\b", RegexOptions.IgnoreCase);
        static readonly Regex ActionLabel = new Regex(@"\s*action\s*[:=]\s*\w+\W*$", RegexOptions.IgnoreCase);

        /// <summary>{say, action} if a direct reply may reach the player, else null: no usable text, an AI or language-model
        /// statement, or five words in a row copied from the NPC's prompt. An action not in `actions` becomes "none".</summary>
        public static string[] CheckDirect(string text, string system, List<string> actions, bool structured, int maxChars = 600)
        {
            var act = "none";
            if (structured)
            {
                var m = Regex.Match(text ?? "", @"\{.*\}", RegexOptions.Singleline);
                if (!m.Success) return null;
                DirectSay d;
                try { d = Json.From<DirectSay>(m.Value); } catch (Exception) { return null; }
                if (d == null) return null;
                text = d.say ?? "";
                act = d.action != null && actions.Contains(d.action) ? d.action : "none";
            }
            var lines = new List<string>(); // line breaks kept: some prompts ask for an answer in lines
            foreach (var line in ActionLabel.Replace(text ?? "", "").Split('\n'))
            {
                var l = string.Join(" ", line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
                if (l.Length > 0) lines.Add(l);
            }
            var say = string.Join("\n", lines.ToArray());
            if (say.Length > maxChars) say = say.Substring(0, maxChars);
            say = say.Trim();
            if (say.Length == 0 || AiTalk.IsMatch(say) || CopiesPrompt(say, system)) return null;
            return new[] { say, act };
        }

        static bool CopiesPrompt(string say, string system)
        {
            var w = Words(system);
            var grams = new HashSet<string>();
            for (int i = 0; i + 5 <= w.Count; i++) grams.Add(string.Join(" ", w.GetRange(i, 5).ToArray()));
            var s = Words(say);
            for (int i = 0; i + 5 <= s.Count; i++)
                if (grams.Contains(string.Join(" ", s.GetRange(i, 5).ToArray()))) return true;
            return false;
        }

        static List<string> Words(string t)
        {
            var r = new List<string>();
            foreach (Match m in Regex.Matches((t ?? "").ToLowerInvariant(), @"\w+")) r.Add(m.Value);
            return r;
        }
    }

    static class Json
    {
#if UNITY_2019_1_OR_NEWER
        public static string To<T>(T v) { return JsonUtility.ToJson(v); }
        public static T From<T>(string s) { return JsonUtility.FromJson<T>(s); }
#else
        public static string To<T>(T v)
        {
            using (var m = new MemoryStream())
            {
                new DataContractJsonSerializer(typeof(T)).WriteObject(m, v);
                return Encoding.UTF8.GetString(m.ToArray());
            }
        }
        public static T From<T>(string s)
        {
            using (var m = new MemoryStream(Encoding.UTF8.GetBytes(s)))
                return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(m);
        }
#endif
    }
}
