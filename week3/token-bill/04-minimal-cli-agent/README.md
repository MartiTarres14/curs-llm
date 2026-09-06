# A minimal CLI agent — memory in files, skills on demand, a terminal for hands

Week 3 closing example: everything the week taught, in one folder. The engine is the same six-line loop from `02-give-the-llm-hands`. What is new is the **self**:

```
04-minimal-cli-agent/
├── minimal_cli_agent.py   # ~120 lines: build the self, two tools, the loop
├── agent.md               # who the agent is, what it must do
├── memory/                # markdown files, loaded whole at startup
│   └── preferences.md
├── skills/                # one folder per skill — INDEXED at startup,
│   └── word-report/       # READ on demand with read_skill
│       └── skill.md
└── workspace/             # the documents the sample agent works on
```

- **`agent.md`** goes at the top of the system prompt: purpose and rules.
- **`memory/*.md`** is loaded whole — fixed memory, cheap and always present.
- **`skills/`** is loaded as an *index only* (the first line of each `skill.md`). When a task matches, the model calls `read_skill` and gets the full instructions — discovery on demand, the same trick `--help` plays. Compare with the MCP registry from lecture 3.3, which rides whole in every request.
- **Two tools:** `run_command` (one shell command, printed, y-gated — security in the scaffolding) and `read_skill`.

## Run

```bash
cd week-03/demos/04-minimal-cli-agent
uv venv && source .venv/bin/activate && uv sync
python minimal_cli_agent.py "make me a word report of the workspace"
```

Watch the order: the agent reads the skill first, then asks permission for `ls`, then for `wc`, then reports — in the style `memory/preferences.md` asks for, signed the way the skill demands. Nobody scripted that sequence.

Every call prints `prompt_tokens`: the agent's whole self — persona, memory, skill index, two tool schemas — costs a few hundred tokens. Keep that number in mind next to your Exercise 2 measurements.

## Make it yours

Edit `agent.md`, drop your own markdown into `memory/`, add a `skills/<name>/skill.md` with a first line that says when to use it. No code changes needed for any of that. That is the point.

## Config

Defaults are Ollama-first (`qwen3:1.7b` — small models drive unevenly; a bigger engine drives better). Copy `.env.example` to `.env` to point at any OpenAI-compatible endpoint.

## 📖 License & author

Licensed under **CC BY-NC-SA 4.0**. © 2026 **Marc Alier i Forment** (UPC) · <https://wasabi.essi.upc.edu/ludo> · <https://lamb-project.org>. BSC Agents Course.
