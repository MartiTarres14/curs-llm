"""EASY-ASSISTANT — a FastAPI backend for the simplest possible RAG app.

The browser never holds a key and never talks to the model. It posts here; this
app loads the assistant's document, fills the assistant's prompt template with
it, calls upstream, and hands back the answer together with the exact prompt
that was sent and the token usage that came back.

"Retrieval" is generous for what happens here: the whole file goes into every
prompt. That is deliberate — watching prompt_tokens refuse to shrink is what
this exercise is for.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import llm
from .assistants import (
    Assistant,
    AssistantIn,
    BadRequest,
    ChatRequest,
    build_payload,
    clean,
)
from .config import (
    DEFAULT_PROMPT_TEMPLATE,
    DEFAULT_SYSTEM_PROMPT,
    MAX_DOCUMENT_BYTES,
    config,
)
from .store import NotFound, store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Enough of the document to show in the UI without shipping a megabyte of text
# to the browser every time the user clicks an assistant.
PREVIEW_CHARS = 2000


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load()
    yield


app = FastAPI(
    title="EASY-ASSISTANT", docs_url="/api/docs", redoc_url=None, lifespan=lifespan
)


def _found(assistant_id: str) -> Assistant:
    try:
        return store.get(assistant_id)
    except NotFound:
        raise HTTPException(status_code=404, detail="No such assistant.") from None


def _document_for(assistant_id: str) -> str:
    try:
        return store.document_text(assistant_id)
    except NotFound:
        raise HTTPException(
            status_code=500,
            detail="This assistant's document is missing from disk. Upload it again.",
        ) from None


# ---------------------------------------------------------------------- health


@app.get("/api/health")
async def health() -> dict:
    """Liveness plus the defaults the frontend uses to prefill its forms."""
    return {
        "status": "ok",
        "model": config.model,
        "max_document_bytes": MAX_DOCUMENT_BYTES,
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "default_prompt_template": DEFAULT_PROMPT_TEMPLATE,
    }


# ------------------------------------------------------------------ assistants


@app.get("/api/assistants")
async def list_assistants() -> list[Assistant]:
    return store.list()


@app.post("/api/assistants", status_code=201)
async def create_assistant(payload: AssistantIn) -> Assistant:
    try:
        return await store.create(clean(payload))
    except BadRequest as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/assistants/{assistant_id}")
async def get_assistant(assistant_id: str) -> Assistant:
    return _found(assistant_id)


@app.put("/api/assistants/{assistant_id}")
async def update_assistant(assistant_id: str, payload: AssistantIn) -> Assistant:
    _found(assistant_id)
    try:
        return await store.update(assistant_id, clean(payload))
    except BadRequest as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/assistants/{assistant_id}", status_code=204)
async def delete_assistant(assistant_id: str) -> None:
    _found(assistant_id)
    await store.delete(assistant_id)


# ------------------------------------------------------------------- documents


def _decode(raw: bytes, filename: str) -> str:
    """Accept plain UTF-8 text and nothing else, with a message that says why."""
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{filename} is {len(raw) // 1024} KB; the limit is "
                f"{MAX_DOCUMENT_BYTES // 1024} KB."
            ),
        )
    if not raw.strip():
        raise HTTPException(status_code=400, detail=f"{filename} is empty.")
    if b"\x00" in raw:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{filename} looks binary, not text. This week the assistant "
                "reads plain text only — .txt or .md. Convert a PDF or a .docx "
                "to text first."
            ),
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail=f"{filename} is not valid UTF-8 text. Save it as UTF-8 and retry.",
        ) from None


@app.post("/api/assistants/{assistant_id}/document")
async def upload_document(assistant_id: str, file: UploadFile) -> Assistant:
    """Replace this assistant's document. One file per assistant, no history."""
    _found(assistant_id)
    name = (file.filename or "document.txt").strip()
    text = _decode(await file.read(), name)
    return await store.put_document(assistant_id, name, text)


@app.get("/api/assistants/{assistant_id}/document")
async def read_document(assistant_id: str) -> dict:
    """The start of the document, for the preview in the sidebar."""
    assistant = _found(assistant_id)
    if assistant.document is None:
        raise HTTPException(status_code=404, detail="This assistant has no document.")
    text = _document_for(assistant_id)
    return {
        "filename": assistant.document.filename,
        "chars": assistant.document.chars,
        "preview": text[:PREVIEW_CHARS],
        "truncated": len(text) > PREVIEW_CHARS,
    }


@app.delete("/api/assistants/{assistant_id}/document")
async def delete_document(assistant_id: str) -> Assistant:
    _found(assistant_id)
    return await store.remove_document(assistant_id)


# ------------------------------------------------------------------------ chat


def _prepare(assistant_id: str, request: ChatRequest) -> tuple[list[dict], str]:
    assistant = _found(assistant_id)
    document = _document_for(assistant_id)
    try:
        return build_payload(assistant, document, request)
    except BadRequest as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/assistants/{assistant_id}/chat")
async def chat(assistant_id: str, request: ChatRequest) -> dict:
    """Baseline: wait for the whole answer, then return it."""
    payload, filled_prompt = _prepare(assistant_id, request)

    try:
        answer, usage = await llm.complete(payload)
    except llm.UpstreamError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {
        "reply": answer,
        "context_sent": payload,
        "filled_prompt": filled_prompt,
        "usage": usage,
        "model": config.model,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/assistants/{assistant_id}/chat/stream")
async def chat_stream(assistant_id: str, request: ChatRequest) -> StreamingResponse:
    """Advanced: relay the upstream stream to the browser as it arrives."""
    payload, filled_prompt = _prepare(assistant_id, request)

    async def events() -> AsyncIterator[str]:
        # Sent first so the context panel fills in before any token lands.
        yield _sse(
            {
                "type": "context",
                "context_sent": payload,
                "filled_prompt": filled_prompt,
                "model": config.model,
            }
        )
        async for event in llm.stream(payload):
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
