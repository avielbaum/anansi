"""Stand-in for a GPU node: an OpenAI-compatible server that needs no model.
Run: python tools/mock_node.py 9001 node-a"""
import asyncio
import json
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse


def make_node(name, latency=0.0):
    app = FastAPI()
    app.state.fail, app.state.reply, app.state.calls, app.state.last = False, None, 0, None

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        app.state.calls += 1
        app.state.last = body
        if app.state.fail:
            raise HTTPException(500, "mock failure")
        await asyncio.sleep(latency)
        if body.get("stream"):  # SSE in 7-character pieces, like a real server emitting tokens
            text = app.state.reply or f"[{name}] hello"

            async def pieces():
                for i in range(0, len(text), 7):
                    yield "data: " + json.dumps({"choices": [{"delta": {"content": text[i:i + 7]}}]}) + "\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(pieces(), media_type="text/event-stream")
        return {"id": f"mock-{name}", "object": "chat.completion", "model": body.get("model"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": app.state.reply or f"[{name}] hello"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}

    return app


if __name__ == "__main__":
    import uvicorn
    # args: port [name [latency_seconds]]
    uvicorn.run(make_node(sys.argv[2] if len(sys.argv) > 2 else "mock", float(sys.argv[3]) if len(sys.argv) > 3 else 0.0),
                port=int(sys.argv[1]), log_level="warning")
