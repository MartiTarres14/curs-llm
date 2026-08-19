"""The RAG half of the app: ingestion in, retrieval out.

Everything embeddings-shaped goes through the course's collections_manager
(create_collection / insert / query) — the application talks to the
abstraction layer, not to the database engine. Each assistant owns one
collection, persisted under data/collections/, so its documents survive
restarts and never mix with another assistant's.

Ingestion is the four steps from the lecture:

    1. CONVERT the upload to markdown (markitdown handles pdf, docx, txt, md…)
    2. STORE the original and the markdown distillation under /static, so
       every chunk can point back to its document by URL
    3. CHUNK the markdown (chunking.py — a for-loop, not a framework)
    4. INSERT each chunk with its provenance metadata

Retrieval is one query per turn: the user's message becomes the query, the
top-K nearest chunks come back with their similarity, and the threshold
decides which of them are allowed into the prompt. Below-threshold hits are
still returned to the UI — watching them get rejected is the lesson.
"""

import logging
import re
import shutil
from pathlib import Path

from collections_manager import Collection, create_collection, insert, query
from markitdown import MarkItDown

from .chunking import chunk_by_chars, chunk_by_sections
from .config import config

log = logging.getLogger(__name__)


class IngestError(RuntimeError):
    """Conversion or chunking failed. Message is safe to show a user."""


# One converter for the process; MarkItDown carries no per-file state.
_markitdown = MarkItDown()

# One collection handle per assistant, created on first use. The handle is a
# cheap wrapper, but re-opening Chroma on every request would be wasteful.
_collections: dict[str, Collection] = {}


def _collection_name(assistant_id: str) -> str:
    # Chroma collection names must start with a letter; assistant ids are hex.
    return f"a-{assistant_id}"


def collection_for(assistant_id: str) -> Collection:
    if assistant_id not in _collections:
        _collections[assistant_id] = create_collection(
            _collection_name(assistant_id),
            description=f"EASY-RAG chunks for assistant {assistant_id}",
            metric="cosine",
            persist_path=str(config.collections_dir),
        )
    return _collections[assistant_id]


# ------------------------------------------------------------------ ingestion


def _safe_filename(filename: str) -> str:
    """Keep the name readable but path-safe: no separators, no surprises."""
    name = Path(filename).name.strip() or "document"
    return re.sub(r"[^\w.\- ]", "_", name)


def _chunk(markdown: str) -> tuple[list[str], str]:
    """Cut the markdown; returns (chunks, the strategy actually used)."""
    if config.chunk_strategy == "sections":
        chunks = chunk_by_sections(markdown, level=config.section_level)
        # A document that converts flat (a PDF with no headings) would come
        # back as one giant chunk — fall through to the window so retrieval
        # still has something usable to work with.
        if len(chunks) > 1:
            return chunks, "sections"
        log.info("no headings found; falling back to chars chunking")
    return chunk_by_chars(markdown, config.chunk_size, config.chunk_overlap), "chars"


def ingest_document(
    assistant_id: str, doc_id: str, filename: str, raw: bytes
) -> dict:
    """Run the four ingestion steps. Returns what the store needs to remember.

    Files land in  data/static/<assistant_id>/<doc_id>/  so /static URLs are
    stable, and the whole folder can be deleted with the document.
    """
    safe_name = _safe_filename(filename)
    folder = config.static_dir / assistant_id / doc_id
    folder.mkdir(parents=True, exist_ok=True)

    # 2a. store the original (markitdown reads it from disk anyway)
    original = folder / safe_name
    original.write_bytes(raw)

    # 1. convert to markdown
    try:
        markdown = _markitdown.convert(str(original)).text_content
    except Exception as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise IngestError(
            f"Could not convert {safe_name} to text ({error}). "
            "Supported: pdf, docx, pptx, html, txt, md."
        ) from error
    if not markdown.strip():
        shutil.rmtree(folder, ignore_errors=True)
        raise IngestError(
            f"{safe_name} converted to empty text. A scanned document has no "
            "text layer — this app does not run OCR."
        )

    # 2b. store the distillation next to it
    md_file = original.with_suffix(original.suffix + ".md")
    md_file.write_text(markdown, encoding="utf-8")

    doc_url = f"/static/{assistant_id}/{doc_id}/{original.name}"
    md_url = f"/static/{assistant_id}/{doc_id}/{md_file.name}"
    title = Path(safe_name).stem

    # 3. chunk
    chunks, strategy = _chunk(markdown)
    if not chunks:
        shutil.rmtree(folder, ignore_errors=True)
        raise IngestError(f"{safe_name} produced no chunks.")

    # 4. insert, with the provenance every retrieved chunk will carry
    collection = collection_for(assistant_id)
    stored = 0
    for number, chunk in enumerate(chunks):
        result = insert(
            collection,
            chunk,
            {
                "source": doc_id,
                "chunk_number": number,
                "title": title,
                "doc_url": doc_url,
                "md_url": md_url,
                "chunking_strategy": strategy,
                "ingested_at": _now(),
            },
        )
        if result["ok"]:
            stored += 1
        else:
            log.warning("chunk %d of %s not inserted: %s", number, doc_id, result["error"])

    if stored == 0:
        shutil.rmtree(folder, ignore_errors=True)
        raise IngestError(
            "No chunk could be embedded. Is Ollama running and "
            f"'{config.embed_model}' pulled?"
        )

    return {
        "filename": safe_name,
        "title": title,
        "doc_url": doc_url,
        "md_url": md_url,
        "markdown_chars": len(markdown),
        "chunks": stored,
        "chunking_strategy": strategy,
    }


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def delete_document_chunks(assistant_id: str, doc_id: str) -> None:
    """Remove one document's chunks and its /static folder.

    The collections manager has no delete — this is the one place the app
    reaches under the abstraction to the Chroma handle it wraps.
    """
    collection = collection_for(assistant_id)
    collection._chroma.delete(where={"source": doc_id})  # noqa: SLF001
    shutil.rmtree(config.static_dir / assistant_id / doc_id, ignore_errors=True)


def delete_assistant_data(assistant_id: str) -> None:
    """Remove everything an assistant owns: chunks and static files."""
    import chromadb

    _collections.pop(assistant_id, None)
    try:
        client = chromadb.PersistentClient(path=str(config.collections_dir))
        client.delete_collection(_collection_name(assistant_id))
    except Exception:  # noqa: BLE001 - an assistant that never ingested has no collection
        pass
    shutil.rmtree(config.static_dir / assistant_id, ignore_errors=True)


# ------------------------------------------------------------------ retrieval


def retrieve(assistant_id: str, user_query: str) -> dict:
    """One turn's retrieval: top-K nearest chunks, gated by the threshold.

    Deliberately queried WITHOUT the manager's threshold filter: the UI shows
    the rejected rows too (✗ below threshold), exactly like the course's
    embeddings-rag-explorer — an empty panel teaches nothing.
    """
    hits = query(collection_for(assistant_id), user_query, top_k=config.top_k)
    for hit in hits:
        hit["injected"] = hit["similarity"] >= config.threshold
    injected = [h for h in hits if h["injected"]]
    return {
        "query": user_query,
        "top_k": config.top_k,
        "threshold": config.threshold,
        "hits": hits,
        "injected": injected,
        "refused": not injected,
    }


def format_context(injected: list[dict]) -> str:
    """The retrieved chunks as the {context} block, provenance included."""
    blocks = []
    for hit in injected:
        meta = hit["metadata"]
        blocks.append(
            f"[{meta['title']} · chunk {meta['chunk_number']} "
            f"· similarity {hit['similarity']:.3f}]\n{hit['chunk']}"
        )
    return "\n\n".join(blocks)


def provenance(retrieval: dict) -> list[dict]:
    """What the frontend shows next to the answer: source, chunk, similarity."""
    return [
        {
            "title": hit["metadata"]["title"],
            "chunk_number": hit["metadata"]["chunk_number"],
            "similarity": hit["similarity"],
            "injected": hit["injected"],
            "doc_url": hit["metadata"]["doc_url"],
            "md_url": hit["metadata"]["md_url"],
            "preview": hit["chunk"][:240],
        }
        for hit in retrieval["hits"]
    ]
