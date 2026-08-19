"""EASY-RAG — a FastAPI backend for a real (small) RAG application.

The browser never holds a key and never talks to the model. It posts here;
this app retrieves the chunks nearest to the user's question from the
assistant's collection, fills the assistant's prompt template with them, calls
upstream, and hands back the answer together with the exact prompt that was
sent, the token usage, and the provenance of every chunk that was considered.

The difference from exercise 1 is the gate in the middle: the whole document
no longer rides along on every turn. Retrieval picks a handful of chunks, the
threshold decides whether they are close enough to use, and when nothing
passes, the assistant refuses instead of answering from noise.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import llm, rag
from .assistants import (
    Assistant,
    AssistantIn,
    BadRequest,
    ChatRequest,
    Document,
    build_payload,
    clean,
    last_user_message,
)
from .config import (
    DEFAULT_PROMPT_TEMPLATE,
    DEFAULT_SYSTEM_PROMPT,
    MAX_DOCUMENT_BYTES,
    REFUSAL_MESSAGE,
    config,
)
from .store import NotFound, _now, new_id, store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load()
    yield


app = FastAPI(
    title="EASY-RAG", docs_url="/api/docs", redoc_url=None, lifespan=lifespan
)


def _found(assistant_id: str) -> Assistant:
    try:
        return store.get(assistant_id)
    except NotFound:
        raise HTTPException(status_code=404, detail="No such assistant.") from None


# ---------------------------------------------------------------------- health


@app.get("/api/health")
async def health() -> dict:
    """Liveness, the defaults for the forms, and the retrieval configuration —
    shown in the UI so nobody has to guess what gate their chunks face."""
    return {
        "status": "ok",
        "model": config.model,
        "embed_model": config.embed_model,
        "max_document_bytes": MAX_DOCUMENT_BYTES,
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "default_prompt_template": DEFAULT_PROMPT_TEMPLATE,
        "rag": {
            "top_k": config.top_k,
            "threshold": config.threshold,
            "chunk_strategy": config.chunk_strategy,
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "section_level": config.section_level,
        },
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
    # After the store forgets it, so a crash here can only leak files, never
    # leave a listed assistant with missing data.
    await asyncio.to_thread(rag.delete_assistant_data, assistant_id)


# ------------------------------------------------------------------- documents


@app.post("/api/assistants/{assistant_id}/documents", status_code=201)
async def upload_document(assistant_id: str, file: UploadFile) -> Assistant:
    """Ingest one more document into this assistant's collection."""
    _found(assistant_id)
    raw = await file.read()
    name = (file.filename or "document").strip()
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{name} is {len(raw) // 1024} KB; the limit is "
                f"{MAX_DOCUMENT_BYTES // 1024} KB."
            ),
        )
    if not raw:
        raise HTTPException(status_code=400, detail=f"{name} is empty.")

    doc_id = new_id()
    try:
        # Conversion + one embedding call per chunk: seconds to minutes of
        # blocking work, kept off the event loop.
        info = await asyncio.to_thread(
            rag.ingest_document, assistant_id, doc_id, name, raw
        )
    except rag.IngestError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return await store.add_document(
        assistant_id,
        Document(id=doc_id, uploaded_at=_now(), **info),
    )


@app.delete("/api/assistants/{assistant_id}/documents/{doc_id}")
async def delete_document(assistant_id: str, doc_id: str) -> Assistant:
    _found(assistant_id)
    try:
        updated = await store.remove_document(assistant_id, doc_id)
    except NotFound:
        raise HTTPException(status_code=404, detail="No such document.") from None
    await asyncio.to_thread(rag.delete_document_chunks, assistant_id, doc_id)
    return updated


# ------------------------------------------------------------------------ chat


async def _prepare(assistant_id: str, request: ChatRequest):
    """Retrieve for this turn. Returns (assistant, retrieval, payload, filled).

    payload and filled are None when the turn is a refusal — nothing goes
    upstream on a refusal, that is what makes it honest.
    """
    assistant = _found(assistant_id)
    try:
        question = last_user_message(request)
    except BadRequest as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if not assistant.documents:
        retrieval = {
            "query": question,
            "top_k": config.top_k,
            "threshold": config.threshold,
            "hits": [],
            "injected": [],
            "refused": True,
        }
    else:
        # The embedding call blocks; keep it off the event loop too.
        retrieval = await asyncio.to_thread(rag.retrieve, assistant_id, question)

    if retrieval["refused"]:
        return assistant, retrieval, None, None

    context = rag.format_context(retrieval["injected"])
    try:
        payload, filled = build_payload(assistant, context, request)
    except BadRequest as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return assistant, retrieval, payload, filled


def _refusal(assistant: Assistant) -> str:
    if not assistant.documents:
        return (
            "This assistant has no documents yet — upload one and I will "
            "answer from it."
        )
    return REFUSAL_MESSAGE


@app.post("/api/assistants/{assistant_id}/chat")
async def chat(assistant_id: str, request: ChatRequest) -> dict:
    """Baseline: wait for the whole answer, then return it."""
    assistant, retrieval, payload, filled = await _prepare(assistant_id, request)

    if retrieval["refused"]:
        return {
            "reply": _refusal(assistant),
            "refused": True,
            "retrieval": {
                **{k: retrieval[k] for k in ("query", "top_k", "threshold", "refused")},
                "hits": rag.provenance(retrieval),
            },
            "context_sent": [],
            "filled_prompt": None,
            "usage": None,
            "model": config.model,
        }

    try:
        answer, usage = await llm.complete(payload)
    except llm.UpstreamError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {
        "reply": answer,
        "refused": False,
        "retrieval": {
            **{k: retrieval[k] for k in ("query", "top_k", "threshold", "refused")},
            "hits": rag.provenance(retrieval),
        },
        "context_sent": payload,
        "filled_prompt": filled,
        "usage": usage,
        "model": config.model,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/assistants/{assistant_id}/chat/stream")
async def chat_stream(assistant_id: str, request: ChatRequest) -> StreamingResponse:
    """Advanced: relay the upstream stream to the browser as it arrives."""
    assistant, retrieval, payload, filled = await _prepare(assistant_id, request)

    retrieval_out = {
        **{k: retrieval[k] for k in ("query", "top_k", "threshold", "refused")},
        "hits": rag.provenance(retrieval),
    }

    async def events() -> AsyncIterator[str]:
        # Sent first so the panels fill in before any token lands.
        yield _sse(
            {
                "type": "context",
                "context_sent": payload or [],
                "filled_prompt": filled,
                "retrieval": retrieval_out,
                "model": config.model,
            }
        )
        if retrieval["refused"]:
            # No LLM call: the refusal is generated here, not upstream.
            yield _sse({"type": "delta", "content": _refusal(assistant)})
            yield _sse({"type": "refused"})
        else:
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


# Static files: the ingested documents (originals + markdown) with stable URLs
# the provenance links point at. Mounted before the frontend so /static wins.
config.static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=config.static_dir), name="documents")

# Mounted last: the API routes above must win over the static files.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
