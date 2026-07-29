"""EASY-CHATGPT — FastAPI proxy between the browser and an OpenAI-compatible LLM.

The browser never holds a key and never talks to the model. It posts here; this
app builds the payload, calls upstream, and hands back the answer together with
the exact context that was sent and the token usage that came back.
"""

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import llm
from .config import MAX_IMAGE_BYTES, config
from .messages import BadRequest, ChatRequest, build_payload

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="EASY-CHATGPT", docs_url="/api/docs", redoc_url=None)


@app.get("/api/health")
async def health() -> dict:
    """Liveness plus the two things the frontend needs to configure itself."""
    return {
        "status": "ok",
        "model": config.model,
        "vision_model": config.vision_model,
        "vision_enabled": config.vision_enabled,
        "max_image_bytes": MAX_IMAGE_BYTES,
    }


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    """Baseline: wait for the whole answer, then return it."""
    try:
        payload, model = build_payload(request)
    except BadRequest as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        answer, usage = await llm.complete(payload, model)
    except llm.UpstreamError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {
        "reply": answer,
        "context_sent": payload,
        "usage": usage,
        "model": model,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Advanced: relay the upstream stream to the browser as it arrives."""
    try:
        payload, model = build_payload(request)
    except BadRequest as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    async def events() -> AsyncIterator[str]:
        # Sent first so the context view can fill in before any token lands.
        yield _sse({"type": "context", "context_sent": payload, "model": model})
        async for event in llm.stream(payload, model):
            yield _sse(event)
        yield _sse({"type": "done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Stops a reverse proxy from buffering the stream into one blob.
            "X-Accel-Buffering": "no",
        },
    )


# Mounted last: the API routes above must win over the static files.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
