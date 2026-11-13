"""Stand-in for a GPU node: an OpenAI-compatible server that needs no model.
Run: python tools/mock_node.py 9001 node-a"""
import asyncio
import json
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse


def sample(kind, schema):
    """A valid quest or storyline built from the request's schema (first allowed id everywhere)."""
    pr = schema["properties"]
    if kind == "quest":
        step = pr["steps"]["items"]["anyOf"][0]["properties"]
        return {"title": "Mock quest", "summary": "A mock quest.", "reward_tier": "small", "story_summary": "It began.",
                "steps": [{"objective": step["objective"]["enum"][0], "target_id": step["target_id"]["enum"][0],
                           "description": "Do the mock thing."}]}
    beat = pr["beats"]["items"]["properties"]
    return {"logline": "A mock story.", "beats": [{"title": "One", "summary": "First.", "npc_id": beat["npc_id"]["enum"][0],
                                                    "location_id": beat["location_id"]["enum"][0]}] * 2}


def make_node(name, latency=0.0):
    app = FastAPI()
    app.state.fail, app.state.reply, app.state.calls, app.state.last = False, None, 0, None
    app.state.auth, app.state.tokens = None, 15  # usage this node reports
    app.state.judge = "SAFE"  # answer given to the gateway's safety-judge calls
    app.state.guard, app.state.guard_last = "safe", None  # answer to calls for the "guard" model
    app.state.check, app.state.check_last = "YES", None  # answer to the gateway's action-check calls

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        app.state.calls += 1
        app.state.last, app.state.auth = body, req.headers.get("authorization")
        if app.state.fail:
            raise HTTPException(500, "mock failure")
        await asyncio.sleep(latency)
        if body.get("model") == "guard":  # a safety classifier such as Llama Guard: plain "safe" or "unsafe\nS1"
            app.state.guard_last = body
            return {"choices": [{"message": {"content": app.state.guard}}]}
        if "Answer YES only if" in (body["messages"][0]["content"] if body.get("messages") else ""):  # the action check
            app.state.check_last = body
            return {"choices": [{"message": {"content": json.dumps({"verdict": app.state.check})}}]}
        if "SAFE" in (body["messages"][0]["content"] if body.get("messages") else ""):  # the gateway's judge call
            return {"choices": [{"message": {"content": json.dumps({"verdict": app.state.judge})}}]}
        rf = (body.get("response_format") or {}).get("json_schema") or {}
        text = app.state.reply
        last = str((body.get("messages") or [{}])[-1].get("content", ""))
        if text is None and last.startswith("echo:"):  # SDK tests over HTTP script a reply this way: "echo: <reply>"
            text = last[5:].strip()
        if text is None:  # a quest or storyline request with no scripted reply gets a valid one built from its schema
            text = json.dumps(sample(rf["name"], rf["schema"])) if rf.get("name") in ("quest", "storyline") else f"[{name}] hello"
        if body.get("stream"):  # SSE in 7-character pieces, like a real server emitting tokens
            async def pieces():
                for i in range(0, len(text), 7):
                    yield "data: " + json.dumps({"choices": [{"delta": {"content": text[i:i + 7]}}]}) + "\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(pieces(), media_type="text/event-stream")
        return {"id": f"mock-{name}", "object": "chat.completion", "model": body.get("model"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": app.state.tokens}}

    return app


if __name__ == "__main__":
    import uvicorn
    # args: port [name [latency_seconds]]
    uvicorn.run(make_node(sys.argv[2] if len(sys.argv) > 2 else "mock", float(sys.argv[3]) if len(sys.argv) > 3 else 0.0),
                port=int(sys.argv[1]), log_level="warning")
