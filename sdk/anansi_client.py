"""Reference SDK (Python). Same contract the Unity/Unreal plugins will follow (DESIGN.md section 6):
try the gateway, fall back locally on timeout, 429 or 5xx, so the game always answers."""
import json

import httpx


class Anansi:
    def __init__(self, base_url, title, key, ticket, fallback=None, timeout=3.0, transport=None):
        self.http = httpx.Client(transport=transport)
        self.url, self.timeout = base_url.rstrip("/") + "/v1/chat/completions", timeout
        self.headers = {"X-Anansi-Title": title, "X-Anansi-Key": key, "X-Steam-Ticket": ticket}
        # fallback(messages) -> str. Point it at a local llama-server in a real game; default is a canned line.
        self.fallback = fallback or (lambda messages: "...")

    def chat(self, messages, npc_id=None, structured=False, **params):
        body = {"messages": messages, "anansi": {"npc_id": npc_id, "structured": structured}, **params}
        try:
            r = self.http.post(self.url, json=body, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                d = r.json()
                text = d["choices"][0]["message"]["content"]
                out = {"source": "gateway", "filtered": d["anansi"]["filtered"]}
                if structured:
                    out.update(json.loads(text))
                else:
                    out["say"] = text
                return out
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return {"source": "fallback", "say": self.fallback(messages), "action": "none", "filtered": False}

    def chat_stream(self, messages, npc_id=None, **params):
        """Yield the reply one sentence at a time. If the gateway fails before the first sentence, yield the local
        fallback line instead; if it fails after, the sentences already shown stand (nothing is replayed).
        Plain replies only: structured actions use chat()."""
        body = {"messages": messages, "stream": True, "anansi": {"npc_id": npc_id}, **params}
        got = False
        try:
            with self.http.stream("POST", self.url, json=body, headers=self.headers, timeout=self.timeout) as r:
                if r.status_code == 200:
                    for line in r.iter_lines():
                        if not line.startswith("data: {"):
                            continue
                        d = json.loads(line[6:])
                        if "error" in d:
                            break
                        text = (d.get("choices") or [{}])[0].get("delta", {}).get("content")
                        if text:
                            got = True
                            yield text
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        if not got:
            yield self.fallback(messages)
