# EASY-RAG — Week 2, Final Project

Exercise 1's EASY-ASSISTANT, grown into a real RAG application. An *assistant*
is still a name, a system prompt and a prompt template with two gaps — but its
knowledge is no longer one pasted file. It is a **collection**: many documents,
converted, chunked, embedded, and retrieved by meaning, a few relevant chunks
per question.

The prompt did not change since exercise 1 — same `{context}` / `{user_input}`
template, filled server-side. What changed is what fills the gap: retrieval
picks the top-K chunks nearest to the question, a similarity **threshold**
decides which of them are close enough to use, and when nothing passes, the
assistant **refuses** instead of answering from noise — the model is not even
called.

Built on the course's
[`collections-manager`](https://github.com/granludo/ludo-engsoft/tree/main/week-02/collections-manager)
(© Marc Alier, UPC, CC BY-NC-SA 4.0), vendored under `collections-manager/` as
a path dependency. The app talks to its three functions — `create_collection` /
`insert` / `query` — and never to the database engine underneath.
`backend/chunking.py` is the course's chunking module, same license.

---

## Run it

Two local models through Ollama — one writes the answers, one turns text into
vectors:

```bash
ollama serve
ollama pull qwen3:1.7b
ollama pull nomic-embed-text
```

### Docker (the normal way)

```bash
cp .env.example .env      # edit if you want a different model or port
docker compose up --build
```

Then open <http://localhost:6663>.

### Without Docker

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env
# outside a container Ollama is just on localhost — edit .env:
#   LLM_BASE_URL=http://localhost:11434/v1
#   OPENAI_ENDPOINT=http://localhost:11434/v1
./.venv/bin/uvicorn backend.main:app --port 6663
```

---

## Using it

1. **＋ New** in the left rail: name, system prompt, prompt template (both
   `{context}` and `{user_input}` are required — the backend refuses a
   template without them).
2. **Upload document** — pdf, docx, pptx, html, txt or md. Each upload is
   *ingested*: converted to markdown, stored under `/static` (original +
   distillation, both linkable), chunked, and inserted into this assistant's
   collection with full provenance metadata. Upload several.
3. Ask something one of the documents answers. Under the answer you get the
   **provenance**: which chunks it came from, their similarity, and a link to
   the source document. The right-hand panel shows every retrieved chunk and
   whether it passed the gate (✓ injected / ✗ below threshold).
4. Ask something none of them answers. The best similarity stays below the
   threshold, nothing is injected, and the assistant says it does not know —
   `usage` is empty because no request went upstream.

## How one turn works

```
question ──embed──► query the assistant's collection
                        │ top-K nearest chunks, with similarity
                        ▼
              similarity ≥ THRESHOLD?
                 │ yes                        │ none passes
                 ▼                            ▼
   format chunks + provenance          honest refusal
   fill {context} / {user_input}       (no LLM call)
   send system + history + prompt
                 ▼
   answer + provenance + usage
```

## Ingestion (what "Upload document" does)

```
file ──markitdown──► markdown ──chunking──► chunks ──embed──► collection
  │                     │
  └── data/static/<assistant>/<doc>/original      (linked from every answer)
                        └── …/original.ext.md     (the distillation)
```

Chunking strategy, size, overlap and heading level are configuration
(`CHUNK_STRATEGY`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `SECTION_LEVEL`), not
constants. `sections` cuts at the document's own headings and falls back to
the sliding window when a document converts flat (a PDF with no headings).

---

## Layout

```
frontend/               plain HTML, CSS and JS. No framework, no build step.
backend/
  config.py             env vars; the retrieval gate and chunking knobs
  assistants.py         what an assistant is; template filling; payload building
  store.py              persistence of assistants + document metadata (JSON)
  rag.py                ingestion (convert/store/chunk/insert) and retrieval
  chunking.py           the course's two strategies (chars / sections)
  llm.py                the only module that talks to the answering model
  main.py               the HTTP routes
collections-manager/    the course utility, vendored as a path dependency
data/                   created at runtime; git-ignored
  assistants.json         the assistants and their documents' metadata
  static/                 originals + markdown distillations (served at /static)
  collections/            the chunks, one ChromaDB collection per assistant
```

## API

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/health` | model names, upload limit, form defaults, retrieval config |
| `GET` | `/api/assistants` | list them |
| `POST` | `/api/assistants` | create one |
| `GET` | `/api/assistants/{id}` | read one |
| `PUT` | `/api/assistants/{id}` | edit name / system prompt / template |
| `DELETE` | `/api/assistants/{id}` | delete it, its files and its collection |
| `POST` | `/api/assistants/{id}/documents` | upload + ingest one more document |
| `DELETE` | `/api/assistants/{id}/documents/{doc_id}` | remove it and its chunks |
| `POST` | `/api/assistants/{id}/chat` | ask; returns reply, retrieval, provenance, usage |
| `POST` | `/api/assistants/{id}/chat/stream` | same, as SSE |
| `GET` | `/static/…` | the ingested originals and their markdown |

Interactive docs at `/api/docs`.

## Configuration

Everything lives in `.env`:

| Variable | Meaning |
| --- | --- |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | the answering model (OpenAI-compatible) |
| `OPENAI_ENDPOINT` / `OPENAI_API_KEY` / `EMBED_MODEL` | the embeddings model (read by collections-manager) |
| `RAG_TOP_K` | how many nearest chunks to consider per question (default 4) |
| `RAG_THRESHOLD` | minimum cosine similarity to reach the prompt (default 0.57) |
| `CHUNK_STRATEGY` | `sections` (default) or `chars` |
| `SECTION_LEVEL` / `CHUNK_SIZE` / `CHUNK_OVERLAP` | chunking knobs |
| `APP_PORT` / `DATA_DIR` / `MAX_HISTORY_MESSAGES` | as in exercise 1 |

The threshold deserves its own sentence: with `nomic-embed-text`, off-topic
questions score ~0.40–0.55 (not near zero) and real answers ~0.55–0.70, so
0.57 is a **calibration against this model and these documents** — watch the
retrieval panel and adjust for yours.

## What changed since exercise 1

- One document per assistant → a collection of many, with per-chunk provenance.
- The whole file in every prompt → top-K chunks over a threshold. Watch
  `prompt_tokens`: it no longer grows with the size of the knowledge.
- Plain-text uploads only → pdf/docx/pptx/html/txt/md via markitdown, with the
  original and its markdown distillation linkable under `/static`.
- Answering from noise → an honest refusal that never reaches the model.
