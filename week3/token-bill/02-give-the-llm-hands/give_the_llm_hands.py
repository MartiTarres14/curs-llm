# © 2026 Marc Alier i Forment (Universitat Politècnica de Catalunya) · https://wasabi.essi.upc.edu/ludo · https://lamb-project.org
# BSC Agents Course — Transformers, LLMs, RAG and Agents: From Theory to Production
# Licensed under Creative Commons BY-NC-SA 4.0 — reuse must credit the author, no commercial use, derivatives under the same license.

# =============================================================================================================== #
# Universitat Politècnica de Catalunya (UPC)                                                                      #
# =============================================================================================================== #

"""
Give the LLM hands — a loop with tools.

We hand the model two tools (wget + execute_sql) and keep calling it
until it stops asking for tools. No framework. No magic. Give it a task
— not a question — and watch it chain the steps by itself.

Ollama-first: runs against a local OpenAI-compatible endpoint, no key,
no money.

NOTE ON MODELS: small local models (qwen3:1.7b) drive this loop UNEVENLY
— they forget to chain steps, malform tool arguments, or stop early.
That is itself a lesson: the loop is trivial; the intelligence steering
it is the model. Point .env at a bigger local model or a frontier /
MareNostrum endpoint and the same six lines behave far better.

Usage:
    uv run --with openai python give_the_llm_hands.py
    uv run --with openai python give_the_llm_hands.py "your own prompt"
"""

import json
import os
import sqlite3
import subprocess
import sys
import urllib.request

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- Config: Ollama-first, env-overridable (.env or shell env) -----------
BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "ollama")  # any non-empty string for Ollama
MODEL = os.getenv("MODEL", "qwen3:1.7b")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
DB_PATH = "database.db"

# --- Tool schemas exposed to the model (OpenAI function-calling) ---------
TOOLS = [
    {"type": "function", "function": {
        "name": "wget", "description": "Fetch the content of a URL.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "URL to fetch."},
            "flags": {"type": "string", "description": "Ignored; kept for compatibility."}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "execute_sql",
        "description": "Run one SQL statement against local SQLite db (database.db). "
                       "SELECT returns rows; CREATE/INSERT/UPDATE/DELETE return affected-row count.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "The SQL statement."}},
            "required": ["query"]}}},
]


def tool_wget(url, flags=""):
    """Human-in-the-loop GATE: security lives in the scaffolding, not the prompt."""
    cmd = f"wget -qO- {url}"
    print(f"\n⚠️  The LLM wants to run:\n    $ {cmd}")
    if input("    Allow? (type 'y'): ").strip().lower() != "y":
        return "USER DENIED: the user refused to execute this wget command. Do not retry."
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "give-the-llm-hands/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace")
        return body[:12000] + ("\n... [truncated]" if len(body) > 12000 else "")
    except Exception as e:
        return f"ERROR fetching {url}: {e}"


def tool_execute_sql(query):
    """CREATE/INSERT/SELECT/UPDATE/DELETE against database.db."""
    print(f"\n🗄️  SQL: {query}")
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(query)
        if query.strip().upper().startswith("SELECT"):
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            conn.close()
            return json.dumps({"columns": cols, "rows": rows}, default=str)
        conn.commit()
        n = cur.rowcount
        conn.close()
        return f"OK — {n} row(s) affected."
    except Exception as e:
        return f"SQL ERROR: {e}"


DISPATCH = {"wget": tool_wget, "execute_sql": tool_execute_sql}

SYSTEM = ("You are a data-collection assistant. Use wget to fetch URLs and "
          "execute_sql to store data in SQLite (database.db). Work step by step: "
          "fetch, create a table, insert rows, then answer in plain text.")


def run_loop(user_prompt):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt}]
    iteration = 0
    while True:                                                       # 1  THE LOOP — ask until the model stops asking
        iteration += 1
        print(f"\n── LLM call #{iteration} ──")
        resp = client.chat.completions.create(                        # 2  ask the model, hand it the tools
            model=MODEL, messages=messages, tools=TOOLS, temperature=0.2)
        print(f"prompt_tokens: {resp.usage.prompt_tokens}")
        msg = resp.choices[0].message
        if not msg.tool_calls:                                        # 3  no tool calls → final answer, STOP
            print(f"\n✅ Final answer:\n{msg.content}")
            return msg.content
        messages.append(msg.model_dump(exclude_none=True))            # 4  remember what the model asked for
        for tc in msg.tool_calls:                                     # 5  run each requested tool
            args = json.loads(tc.function.arguments or "{}")
            result = DISPATCH.get(tc.function.name, lambda **_: "ERROR: unknown tool")(**args)
            print(f"📎 {tc.function.name} → {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id,   # 6  feed results back, then LOOP
                             "name": tc.function.name, "content": result})
    # ^^^ Lines 1-6 above are the whole engine. Everything else is plumbing.


def main():
    print(f"⚙️  model={MODEL}  endpoint={BASE_URL}  db={DB_PATH}")
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = ("Fetch https://jsonplaceholder.typicode.com/users , create a "
                  "table for the user id, name, email and city, insert every "
                  "row, then tell me how many users you stored.")
        print("(no prompt given — using the built-in demo prompt)")
    run_loop(prompt)


if __name__ == "__main__":
    main()
