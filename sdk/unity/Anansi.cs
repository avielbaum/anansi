// Anansi game SDK for Unity (2019.1+) and plain .NET. Contract matches sdk/anansi_client.py:
// ask the gateway, and on timeout, 429 or any failure answer from your local fallback so the game never stalls.
// Needs "System.Net.Http" (Unity 2021+ or .NET Standard 2.1 API level). Keep C# 5-compatible so the test harness compiles it.
using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
#if UNITY_2019_1_OR_NEWER
using UnityEngine;
#else
using System.IO;
using System.Runtime.Serialization.Json;
#endif

namespace Anansi
{
    [Serializable] public class Message { public string role; public string content; }
    [Serializable] public class NpcRequest { public string npc_id; public bool structured; public List<Message> messages; }
    [Serializable] public class NpcResponse { public string say; public string action; public bool filtered; public string node; }

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
        readonly string url, title, key;
        readonly Func<string> steamTicket;
        readonly Func<List<Message>, Task<string>> fallback;

        // steamTicket: return the hex auth ticket for the web API (Steamworks.NET: SteamUser.GetAuthTicketForWebApi).
        // fallback: answer locally, for example from a bundled llama.cpp server. Default is a neutral line.
        public Client(string baseUrl, string titleId, string titleKey, Func<string> steamTicket,
                      Func<List<Message>, Task<string>> fallback = null, double timeoutSeconds = 3)
        {
            http = new HttpClient { Timeout = TimeSpan.FromSeconds(timeoutSeconds) };
            url = baseUrl.TrimEnd('/') + "/v1/npc";
            title = titleId; key = titleKey; this.steamTicket = steamTicket; this.fallback = fallback;
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
