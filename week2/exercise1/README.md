# EASY-ASSISTANT — Week 2, Exercise 1

The simplest possible RAG system. A user creates an *assistant* (a name, a
system prompt, and a prompt template), uploads one plain-text document, and
chats with it. On every turn the backend drops the **whole document** into the
`{context}` gap of the template and the user's message into `{user_input}`, and
sends the result to the model.

Nothing is retrained and no weights change. The model answers from the file
because the file is sitting in front of it — *cheating at solitaire*.

The point of the exercise is the number in the top-right panel:
`prompt_tokens` does not shrink when your question gets shorter, because the
whole file goes up again every single turn. That is what Week 3 fixes.

---

## Run it

You need an OpenAI-compatible endpoint. A small local model is plenty:

```bash
ollama serve
ollama pull qwen2.5:3b
```

Pick a model **without** a thinking mode. `qwen3:1.7b` works too, but it
reasons out loud before every answer, and with a whole document in the prompt
that wait gets long.

### Docker (the normal way)

```bash
cp .env.example .env      # edit if you want a different model or port
docker compose up --build
```

Then open <http://localhost:6662>.

`.env` ships with `LLM_BASE_URL=http://host.docker.internal:11434/v1`, which is
how the container reaches Ollama running on your host.

### Without Docker

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env
# outside a container Ollama is just on localhost:
LLM_BASE_URL=http://localhost:11434/v1 ./.venv/bin/uvicorn backend.main:app --port 6662
```

---

## Using it

1. **＋ New** in the left rail. Give the assistant a name, a system prompt, and
   a prompt template. The template *must* contain both `{context}` and
   `{user_input}` — the backend refuses to save one that does not, because an
   assistant missing `{context}` looks like it works while quietly answering
   from training data.
2. **Upload document**. Plain text only (`.txt`, `.md`). There is a sample in
   `samples/tortuga-robotics.txt` — a fact sheet for a company that does not
   exist, which is exactly what you want for testing.
3. Ask something the document answers. Then ask something it does not
   (*"Who is the president of France?"*). The refusal is the good result.
4. Watch the right-hand panel: the **filled prompt** is the real user message
   that went upstream, and **Prompt** under Tokens is `prompt_tokens`.

---

## How it works

```
frontend/           plain HTML, CSS and JS. No framework, no build step.
backend/
  config.py         env vars, and the defaults the "new assistant" form starts from
  assistants.py     what an assistant is; template filling; building one turn's payload
  store.py          persistence: assistants.json + one .txt per document
  llm.py            the only module that talks to the model
  main.py           the HTTP routes
data/               created at runtime; git-ignored
samples/            a test document
```

### One turn

```
system    -> the assistant's system prompt
user      -> earlier questions, as the user typed them
assistant -> earlier answers
user      -> THIS question, wrapped in the filled template (with the whole document)
```

Only the last turn carries the document. Wrapping the older turns too would
send the file once per turn in history — an already wasteful prompt multiplied
by the length of the conversation.

### Two details worth knowing

**The gaps are filled with a single regex pass, not `str.format()`.** A
document containing braces — JSON, code, LaTeX — would make `.format()` raise a
`KeyError`. And a naive `.replace().replace()` rescans what it just inserted, so
a document containing the literal `{user_input}` would swallow the user's
question. See `fill_template()` in `backend/assistants.py`.

**The document text is not inside `assistants.json`.** It lives in
`data/documents/<id>.txt`. A 200 KB file escaped onto one JSON line makes the
store unreadable, and being able to open it and read it is most of the reason
to choose a JSON file over a database in the first place.

---

## API

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/health` | model name, upload limit, form defaults |
| `GET` | `/api/assistants` | list them |
| `POST` | `/api/assistants` | create one |
| `GET` | `/api/assistants/{id}` | read one |
| `PUT` | `/api/assistants/{id}` | edit name / system prompt / template |
| `DELETE` | `/api/assistants/{id}` | delete it and its document |
| `POST` | `/api/assistants/{id}/document` | upload (multipart), replaces any existing one |
| `GET` | `/api/assistants/{id}/document` | metadata + first 2000 chars |
| `DELETE` | `/api/assistants/{id}/document` | remove it |
| `POST` | `/api/assistants/{id}/chat` | ask; returns reply, payload, filled prompt, usage |
| `POST` | `/api/assistants/{id}/chat/stream` | same, as SSE |

Interactive docs at `/api/docs`.

---

## Configuration

Everything lives in `.env`. Switching from a local model to a frontier one is
three lines of config and zero lines of code:

| Variable | Meaning |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible endpoint (required) |
| `LLM_API_KEY` | any non-empty string for Ollama (required) |
| `LLM_MODEL` | model name (required) |
| `APP_PORT` | host port to publish, default `6662` |
| `DATA_DIR` | where the store lives; compose sets it to `/app/data` |
| `MAX_HISTORY_MESSAGES` | earlier turns forwarded upstream, default `20`; `0` makes every question independent |

The upload cap (1 MB) is a constant in `backend/config.py`, not a knob — it is
a property of the exercise, not of a deployment.

---

## What changed since Week 1

- The system prompt moved out of `.env` and into the assistant, where it now
  sits next to a prompt template and a document.
- New: assistants, document upload, and persistence.
- Gone: image attachments and the vision model. Week 2 is about text.
