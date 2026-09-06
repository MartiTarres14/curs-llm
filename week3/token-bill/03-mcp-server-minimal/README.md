<!-- =============================================================================================================== -->
<!-- Universitat Politècnica de Catalunya (UPC)                                                                      -->
<!-- =============================================================================================================== -->

# 🔌 A minimal MCP server — and the agent loop that calls it

MCP (the Model Context Protocol) is a standard way to plug capabilities into an LLM-driven
app without hand-wiring each one. Expose a capability **once**, as a server, and any
compliant agent can discover and use it.

- **`server.py`** — a complete MCP server in a handful of lines: one **tool**
  (`get_robot_spec`) and one **resource** (`acme://company`), served over stdio. A decorator
  turns a function into a tool; the library handles the JSON-RPC.
- **`agent_with_mcp.py`** — the hand-built agent loop from `give-the-llm-hands`, now pointed
  at the server. **The loop does not change — only the source of the tools does.** On connect
  it discovers the server's **registry** (name + description + schema per tool) and hands it
  to the model; the model's calls are routed over JSON-RPC and the results fed back.

```bash
uv venv && source .venv/bin/activate && uv pip install openai mcp
MODEL=qwen3.6:27b OPENAI_BASE_URL=http://localhost:11434/v1 \
  uv run agent_with_mcp.py "what is the top speed of the Pallet Pup?"
```

`agent_with_mcp.py` spawns `server.py` itself, so run it from this directory. Use a
tool-calling model.

> **Supply-chain note:** pin the `mcp` SDK to a release that has been out for a couple of
> weeks (the course's "don't install it the day it ships" rule). A fresh release is exactly
> where a compromised dependency would first appear.

## 📖 License & author

Licensed under **CC BY-NC-SA 4.0**. © 2026 **Marc Alier i Forment** (UPC) ·
<https://wasabi.essi.upc.edu/ludo> · <https://lamb-project.org>. BSC Agents Course.
