# © 2026 Marc Alier i Forment (Universitat Politècnica de Catalunya) · https://wasabi.essi.upc.edu/ludo · https://lamb-project.org
# BSC Agents Course — Transformers, LLMs, RAG and Agents: From Theory to Production
# Licensed under Creative Commons BY-NC-SA 4.0 — reuse must credit the author, no commercial use, derivatives under the same license.

# =============================================================================================================== #
# Universitat Politècnica de Catalunya (UPC)                                                                      #
# =============================================================================================================== #

"""
🔌🤖 The hand-built agent loop, now calling an MCP server.

This is the round-trip that lands because you built both halves: the loop (from
'give the LLM hands') and the server (server.py). On connect, the client asks the
server for its REGISTRY of tools — name + description + JSON schema for each — and
hands those straight to the model as its tool list. When the model asks for a tool,
the loop routes the call over JSON-RPC to the MCP server and feeds the result back.

The loop did not change. Only where the tools come from changed: instead of being
hand-written in the client, they are DISCOVERED from the server.

    uv run agent_with_mcp.py "what is the top speed of the Pallet Pup?"
"""
import asyncio
import json
import os
import sys

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

client = OpenAI(
    base_url=os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1"),
    api_key=os.environ.get("OPENAI_API_KEY", "ollama"),
)
MODEL = os.environ.get("MODEL", "qwen3:1.7b")
SERVER = StdioServerParameters(command=sys.executable, args=["server.py"])


def to_openai_tool(t):
    """An MCP tool's registry entry IS an OpenAI tool schema, almost verbatim."""
    return {"type": "function", "function": {
        "name": t.name, "description": t.description or "", "parameters": t.inputSchema}}


async def main(user_prompt):
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. discover the registry the server advertises
            listing = await session.list_tools()
            tools = [to_openai_tool(t) for t in listing.tools]
            print("── the MCP registry the model receives ──")
            for t in tools:
                print(f"  tool: {t['function']['name']}  —  {t['function']['description']}")
            print()

            messages = [{"role": "user", "content": user_prompt}]
            while True:  # the SAME loop as 'give the LLM hands' — only the tool source changed
                resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
                print(f"  prompt_tokens: {resp.usage.prompt_tokens}")   # the registry rides in every request
                msg = resp.choices[0].message
                messages.append(msg.model_dump(exclude_none=True))
                if not msg.tool_calls:
                    print(f"✅ {msg.content}")
                    return
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    print(f"  → MCP call: {tc.function.name}({args})")
                    result = await session.call_tool(tc.function.name, args)   # JSON-RPC round-trip
                    text = "".join(getattr(c, "text", "") for c in result.content)
                    print(f"  ← MCP result: {text}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or "What is the top speed of the Pallet Pup, and who is Acme's CEO?"
    asyncio.run(main(prompt))
