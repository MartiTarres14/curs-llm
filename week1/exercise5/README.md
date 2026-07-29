# EASY-CHATGPT

A small chatbot server. A **FastAPI backend acts as a proxy** between a vanilla
JavaScript frontend and any OpenAI-compatible LLM endpoint: the browser posts to
this app, this app calls the model, and the answer comes back. The frontend never
talks to the model and never sees an API key.

It also shows you **the exact payload sent upstream** and the **token usage** that
came back, so you can watch the context grow and the token count climb turn by
turn.

```
Browser (vanilla JS/HTML/CSS)
        │  fetch — JSON, or Server-Sent Events when streaming
        ▼
FastAPI proxy  ──────►  OpenAI-compatible LLM
                ◄──────  (Ollama, OpenAI, vLLM, OpenRouter, …)
```

Week 1 · Exercise 5 of *Transformers, LLMs, RAG and Agents: From Theory to
Production*. The requirements it implements are in [SPEC.md](SPEC.md).

## Features

- **Baseline** — non-streaming: `POST /api/chat` waits for the whole answer.
- **Advanced** — streaming: `POST /api/chat/stream` relays the upstream stream
  chunk by chunk over SSE, so the answer types itself out. Toggle in the UI.
- **Best** — vision: attach an image when `LLM_VISION_MODEL` is set.
- Replies rendered as Markdown (headings, lists, fenced code, links).
- Context view: the real upstream messages, per-turn tokens, and a session total.

## Prerequisites

- Docker and Docker Compose (`docker compose version`).
- An OpenAI-compatible LLM endpoint. Either a hosted one, or
  [Ollama](https://ollama.com) on your machine with a model pulled:
  ```
  ollama pull qwen2.5:3b
  ```

## Run it

```bash
cp .env.example .env      # then edit .env — see below
docker compose up --build
```

Open **<http://localhost:6661>**.

### What to put in .env

| Variable               | What it is                                                              |
| ---------------------- | ----------------------------------------------------------------------- |
| `LLM_BASE_URL`         | OpenAI-compatible base URL, **including `/v1`**. For Ollama on the host: `http://host.docker.internal:11434/v1` |
| `LLM_API_KEY`          | The key for that endpoint. Ollama ignores it, but it must be non-empty.  |
| `LLM_MODEL`            | Model name, e.g. `qwen2.5:3b`, `gpt-4o-mini`.                           |
| `LLM_VISION_MODEL`     | Vision-capable model. **Leave empty** to disable image attachments.      |
| `APP_PORT`             | Host port to publish. Default `6661`.                                   |
| `SYSTEM_PROMPT`        | Prepended to every conversation, and visible in the context view.        |
| `MAX_HISTORY_MESSAGES` | How many recent turns get forwarded upstream. Default `20`.              |

`.env` is git-ignored and must never be committed. Nothing is hardcoded: if a
required variable is missing the app refuses to start and says which one.

### Running without Docker

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# in .env use http://localhost:11434/v1 — host.docker.internal only exists in the container
.venv/bin/uvicorn backend.main:app --port 6661
```

## HTTP API

| Endpoint            | Method | Notes                                                    |
| ------------------- | ------ | -------------------------------------------------------- |
| `/api/health`       | GET    | Status, model name, whether vision is on. No key leaked. |
| `/api/chat`         | POST   | Returns `reply`, `context_sent`, `usage`, `model`.        |
| `/api/chat/stream`  | POST   | `text/event-stream`; events `context`, `delta`, `usage`, `done`, `error`. |
| `/api/docs`         | GET    | Generated OpenAPI docs.                                  |

Two things worth knowing, both noted in SPEC.md:

- The SSE stream begins with a **`context` event** carrying `context_sent`, since
  a stream has no response body to put it in. The spec listed `delta`/`usage`/
  `done`/`error` only; this is an addition, not a replacement.
- The context view **truncates base64 image data** to the first 48 characters. It
  is the real payload otherwise; a 5 MB data URL in the panel would freeze the
  page.

## Troubleshooting

**"Cannot reach the LLM at …" / connection refused**

The container cannot see your LLM. Check, in order:

1. Is it up? `curl http://localhost:11434/v1/models` on the host.
2. From inside Docker, `localhost` is *the container*. Use
   `http://host.docker.internal:11434/v1` — `docker-compose.yml` already maps
   that name to the host gateway.
3. On native Linux Docker, an Ollama bound only to `127.0.0.1` is invisible to the
   container — restart it as `OLLAMA_HOST=0.0.0.0 ollama serve`. (With Docker
   Desktop, including WSL2, the loopback bind usually works as-is.)
4. Does `LLM_BASE_URL` end in `/v1`? Without it every call 404s.

**"The LLM returned HTTP 404. model '…' not found"**

The endpoint answered, so the URL and key are fine — it just does not have that
model. `LLM_MODEL` must match a name from `ollama list` exactly, tag included
(`qwen2.5:3b`, not `qwen2.5`).

Watch out for **two Ollama instances**: on Windows with WSL2 you can easily have
one inside WSL and one as the Windows app, both on port 11434 but with separate
model libraries. `ollama list` in your shell shows one of them; the container
reaching `host.docker.internal` may well hit the other. Ask the endpoint itself
what it has, instead of trusting your shell:

```bash
docker compose exec easy-chatgpt \
  python -c "import urllib.request;print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').read())"
```

**"Port already in use"**

Something else holds 6661. Change `APP_PORT` in `.env` (6662, 6663, …) and
`docker compose up` again — the port inside the container never changes.

**Answers take minutes / "The LLM did not answer within 600 s"**

First, ignore the first request after startup: loading the model into RAM can take
a minute on its own. Time the *second* one.

If it is still slow, suspect the endpoint rather than the model. On this machine the
same `qwen2.5:3b`, both on CPU, ran at **0.3 tokens/s under the WSL Ollama and 21
tokens/s under the Windows Ollama** — a 70× difference on identical work. If you have
two instances (see the 404 entry above), try the other one before blaming the model.

Otherwise: turn **Streaming on** so the first token shows in under a second instead
of staring at a spinner, or point `LLM_BASE_URL` at a hosted endpoint.

**Replies are empty with a reasoning model (`qwen3`, `deepseek-r1`, …)**

Those models spend hundreds of tokens thinking before they emit any answer, and
Ollama returns that thinking in a separate `reasoning` field that this app does
not display. On a slow machine you may wait a long time for nothing to appear.
A non-reasoning model of the same size answers far sooner.

**Tokens are marked as estimated**

The provider did not report `usage`, so the counts are a local approximation
(~4 characters per token) and the context panel says so.

## Layout

```
backend/
  main.py       FastAPI app: routes, SSE plumbing, static files
  config.py     environment loading; fails loudly on a missing variable
  llm.py        the only module that talks to the model
  messages.py   request models, image validation, upstream payload
frontend/
  index.html    chat window and context panel
  app.js        sending, SSE parsing, context view
  markdown.js   small Markdown renderer (escapes first, then formats)
  style.css
```
