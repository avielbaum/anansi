// Anansi game SDK for Unity (2019.1+) and plain .NET. Contract matches sdk/anansi_client.py:
// ask the gateway, and on timeout, 429 or any failure answer from your local fallback so the game never stalls.
// Needs "System.Net.Http" (Unity 2021+ or .NET Standard 2.1 API level). Keep C# 5-compatible so the test harness compiles it.
using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
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
    [Serializable] public class Chunk { [System.Runtime.Serialization.OptionalField] public List<Choice> choices; }

    public class Reply
    {
        public string Say;
        public string Action;    // one of the title's whitelisted actions, or "none"
        public bool Filtered;    // the gateway replaced unsafe text
        public string Source;    // "gateway" or "fallback"
    }

    public class Client
    {
        readonly HttpClient http;
        readonly string url, chatUrl, title, key;
        readonly Func<string> steamTicket;
        readonly Func<List<Message>, Task<string>> fallback;

        // steamTicket: return the hex auth ticket for the web API (Steamworks.NET: SteamUser.GetAuthTicketForWebApi).
        // fallback: answer locally, for example from a bundled llama.cpp server. Default is a neutral line.
        public Client(string baseUrl, string titleId, string titleKey, Func<string> steamTicket,
                      Func<List<Message>, Task<string>> fallback = null, double timeoutSeconds = 3)
        {
            http = new HttpClient { Timeout = TimeSpan.FromSeconds(timeoutSeconds) };
            url = baseUrl.TrimEnd('/') + "/v1/npc";
            chatUrl = baseUrl.TrimEnd('/') + "/v1/chat/completions";
            title = titleId; key = titleKey; this.steamTicket = steamTicket; this.fallback = fallback;
        }

        // Plain (unstructured) replies, one finished sentence at a time: onSentence runs for each sentence as it arrives.
        // If the gateway fails or times out before the first sentence, onSentence gets the fallback line once.
        // If it fails after text was shown, that text stands. No ConfigureAwait(false) in the read loop on purpose:
        // in Unity the callback then runs on the main thread. Structured actions use ChatAsync.
        public async Task<Reply> StreamAsync(List<Message> messages, Action<string> onSentence, string npcId = null)
        {
            var said = new StringBuilder();
            var cts = new CancellationTokenSource();
            cts.CancelAfter(http.Timeout); // covers the wait for the first sentence; lifted once one arrives
            try
            {
                var body = new StreamRequest { stream = true, anansi = new Meta { npc_id = npcId }, messages = messages };
                var req = new HttpRequestMessage(HttpMethod.Post, chatUrl)
                {
                    Content = new StringContent(Json.To(body), Encoding.UTF8, "application/json")
                };
                req.Headers.Add("X-Anansi-Title", title);
                req.Headers.Add("X-Anansi-Key", key);
                req.Headers.Add("X-Steam-Ticket", steamTicket());
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
                                if (c.choices == null || c.choices.Count == 0 || c.choices[0].delta == null) continue;
                                var text = c.choices[0].delta.content;
                                if (string.IsNullOrEmpty(text)) continue;
                                if (said.Length == 0) cts.CancelAfter(Timeout.InfiniteTimeSpan);
                                said.Append(text);
                                onSentence(text);
                            }
                        }
                    }
                }
            }
            catch (Exception) { } // timeout, dropped connection, bad JSON
            cts.Dispose();
            if (said.Length > 0) return new Reply { Say = said.ToString(), Action = "none", Filtered = false, Source = "gateway" };
            var say = fallback != null ? await fallback(messages) : "...";
            onSentence(say);
            return new Reply { Say = say, Action = "none", Filtered = false, Source = "fallback" };
        }

        public async Task<Reply> ChatAsync(List<Message> messages, string npcId = null, bool structured = false)
        {
            try
            {
                var body = new NpcRequest { npc_id = npcId, structured = structured, messages = messages };
                var req = new HttpRequestMessage(HttpMethod.Post, url)
                {
                    Content = new StringContent(Json.To(body), Encoding.UTF8, "application/json")
                };
                req.Headers.Add("X-Anansi-Title", title);
                req.Headers.Add("X-Anansi-Key", key);
                req.Headers.Add("X-Steam-Ticket", steamTicket());
                using (var resp = await http.SendAsync(req).ConfigureAwait(false))
                {
                    if (resp.IsSuccessStatusCode)
                    {
                        var r = Json.From<NpcResponse>(await resp.Content.ReadAsStringAsync().ConfigureAwait(false));
                        return new Reply { Say = r.say, Action = r.action ?? "none", Filtered = r.filtered, Source = "gateway" };
                    }
                }
            }
            catch (Exception) { } // timeout, DNS, TLS, bad JSON: every failure means "use the fallback"
            var say = fallback != null ? await fallback(messages).ConfigureAwait(false) : "...";
            return new Reply { Say = say, Action = "none", Filtered = false, Source = "fallback" };
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
