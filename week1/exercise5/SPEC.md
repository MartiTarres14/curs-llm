# EASY-CHATGPT — Specification

A minimal but real chatbot server. FastAPI acts as a **proxy** between a vanilla-JS
frontend and an OpenAI-compatible LLM endpoint. The frontend never talks to the model
directly.

---

## 1. Architecture

```
Browser (vanilla JS/HTML/CSS)
        │  fetch / EventSource
        ▼
FastAPI backend  ──────►  OpenAI-compatible LLM
(proxy + context)  ◄──────  (Ollama, OpenAI, Anthropic-compat, ...)
```

The backend is the only component that holds credentials. Keep this shape: it is reused
in Week 2.

## 2. Repository layout

```
week1/exercise5/
├── docker-compose.yml
├── Dockerfile
├── .env.example          # committed
├── .env                  # NEVER committed
├── .gitignore
├── README.md
├── requirements.txt
├── backend/
│   ├── main.py           # FastAPI app, routes
│   ├── config.py         # env loading, no defaults that hide errors
│   └── llm.py            # OpenAI-compatible client wrapper
└── frontend/
    ├── index.html
    ├── app.js
    └── style.css
```

## 3. Configuration

All config comes from environment variables. **No hardcoded values, no fallbacks that
silently mask a missing variable** — if a required variable is absent the app must fail
loudly at startup with a clear message.

`.env.example`:

```
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=not-needed-for-ollama
LLM_MODEL=qwen2.5:3b
LLM_VISION_MODEL=
APP_PORT=6661
SYSTEM_PROMPT=You are a helpful assistant.
MAX_HISTORY_MESSAGES=20
```

`.gitignore` must include `.env`, `__pycache__/`, `.venv/`, `*.pyc`.

## 4. HTTP API

### `GET /api/health`
Returns `{"status": "ok", "model": "<LLM_MODEL>"}`. Must not leak the API key.

### `POST /api/chat` — baseline, non-streaming

Request:
```json
{
  "messages": [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "hi"},
    {"role": "user", "content": "what did I just say?"}
  ]
}
```

Response:
```json
{
  "reply": "You said hello.",
  "context_sent": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "hello"}
  ],
  "usage": {
    "prompt_tokens": 42,
    "completion_tokens": 11,
    "total_tokens": 53
  },
  "model": "qwen2.5:3b"
}
```

`context_sent` is the **exact** payload sent upstream, system prompt included. This is
what feeds the context view — it must be the real thing, not a reconstruction.

### `POST /api/chat/stream` — advanced, Server-Sent Events

Same request body. Response is `text/event-stream`. Event shapes:

```
data: {"type":"context","context_sent":[...],"model":"qwen2.5:3b"}
data: {"type":"delta","content":"Hel"}
data: {"type":"delta","content":"lo"}
data: {"type":"usage","usage":{"prompt_tokens":42,"completion_tokens":11,"total_tokens":53}}
data: {"type":"done"}
```

> Addition during implementation: the `context` event. A stream has no JSON body
> to carry `context_sent` in, and the context view needs it, so it is sent first
> — before any token. The other event shapes are unchanged.

Errors mid-stream: `data: {"type":"error","message":"..."}` then close. The backend
must relay the upstream stream chunk by chunk — buffering the whole answer and then
replaying it defeats the purpose.

Note: many OpenAI-compatible providers only send `usage` in the final chunk when asked
(`stream_options: {"include_usage": true}`). If the provider does not support it,
estimate token counts locally and label them as estimated in the UI.

### `POST /api/chat` with an image — best, vision

Extend the message content to the OpenAI multimodal array form:

```json
{"role": "user", "content": [
  {"type": "text", "text": "what is in this picture?"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]}
```

Frontend sends a base64 data URL. Enforce a max upload size (e.g. 5 MB) and reject
non-image MIME types. If `LLM_VISION_MODEL` is empty, disable the attach button and
show why.

## 5. Frontend requirements

- Vanilla JS, HTML, CSS. **No React, no Svelte, no TypeScript, no build step, no npm.**
- Chat window with message history, visually distinct user/assistant turns.
- Assistant replies rendered as **Markdown** — fenced code blocks, lists and headings
  must come out formatted. Use a single CDN library (e.g. `marked`) plus sanitisation,
  or a small hand-rolled renderer. Never inject raw model output with `innerHTML`
  unsanitised.
- **Context view**: a side panel or collapsible section showing
  - the full list of messages actually sent upstream, with roles,
  - `prompt_tokens` / `completion_tokens` / `total_tokens` for the last call,
  - a running total of tokens for the session.
  It must be visible that the context grows turn by turn and the token count climbs.

  > Addition during implementation: base64 image data is truncated to its first
  > 48 characters in this panel, with the original size shown. Everything else is
  > the verbatim payload; rendering a 5 MB data URL would freeze the page.
- A toggle between streaming and non-streaming mode, so both versions are demonstrable.
- Enter to send, Shift+Enter for newline. Disable the send button while a request is in
  flight.
- Errors from the backend must surface in the UI, not just the console.

## 6. Docker

- `Dockerfile`: slim Python base, install `requirements.txt`, run uvicorn on `0.0.0.0`
  inside the container. Serve the frontend as static files from FastAPI so there is
  exactly one container and one port.
- `docker-compose.yml`: reads `.env`, maps host `6661` to the container port, and
  includes `extra_hosts: ["host.docker.internal:host-gateway"]` so the container can
  reach an Ollama running on the host (needed on Linux; harmless elsewhere).
- The whole thing must come up with `docker compose up` after the user copies
  `.env.example` to `.env` and edits it. No other manual step.

## 7. README

Must contain, in this order: what it is, prerequisites, `cp .env.example .env`, what to
put in each variable, `docker compose up`, the URL to open, and a troubleshooting
section covering "connection refused to the LLM" and "port already in use".

## 8. Acceptance criteria

The build is done when all of these hold:

1. `docker compose up` on a clean clone, after editing only `.env`, serves the app on
   `http://localhost:6661`.
2. A multi-turn conversation works — turn 3 correctly references turn 1.
3. The context view shows the real upstream payload and token counts that increase
   across turns.
4. A reply containing a fenced code block renders as a code block, not as backticks.
5. Streaming mode types the answer out progressively; network tab shows an
   `text/event-stream` response, not one big JSON.
6. `grep -ri "sk-\|api_key\s*=\s*[\"']" backend/` finds no hardcoded secret.
7. `git status` after a fresh run shows `.env` as ignored.
8. Stopping the LLM endpoint produces a readable error in the UI, not a hung spinner.

## 9. Out of scope for now

User accounts, persistence, chat history. Design the message-handling code so these can
be added later, but do not build them yet.

## 10. Instructions to the coding agent

- Work in milestones. Stop after each one and let me run it before continuing:
  **M1** backend + `/api/health` running locally → **M2** `/api/chat` + minimal
  frontend → **M3** context view + Markdown → **M4** Docker compose → **M5** streaming
  → **M6** vision.
- Do not write code I have not asked for. No extra endpoints, no config framework,
  no abstraction layers "for later".
- Keep files short. If `main.py` passes ~150 lines, split it.
- After each milestone, tell me in three sentences what you changed and how I verify it
  by hand.
- Do not run `git commit` unless I ask.
- If a requirement in this spec is ambiguous or you think it is wrong, ask before
  implementing.
