# Give the LLM hands — a loop with tools

Week 3 teaching example. We hand the model two tools — `wget` to fetch a URL and `execute_sql` to write to a local SQLite database — and we keep calling it until it stops asking for tools. Then we give it a **task**, not a question, and watch what happens.

## Prerequisites

Local Ollama running with a small tool-capable model:

```bash
ollama serve
ollama pull qwen3:1.7b
```

## Run

The usual setup, same as every demo in this course:

```bash
cd week-03/demos/02-give-the-llm-hands
uv venv
source .venv/bin/activate
uv sync
python give_the_llm_hands.py
```

Or with your own prompt:

```bash
python give_the_llm_hands.py "fetch https://api.github.com/users/torvalds and store the login, name and public_repos count"
```

The default prompt fetches a JSON API, asks the model to create a table, insert the rows, and report how many it stored — a task that needs several steps, so you watch the `while` loop turn over (`── LLM call #N ──`): fetch, create table, insert, answer. Nobody tells the program the order of the steps. The model decides; the loop executes.

When `wget` is requested you will be prompted: type `y` to allow. This is deliberate — the exact command is printed, and the dangerous action runs only with your approval. A denial is reported back to the model (it is *told* it was denied) and the loop keeps running, nothing crashes.

## Config

Defaults are Ollama-first; no `.env` is needed to run locally. Copy `.env.example` to `.env` to override `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `MODEL` (e.g. to point at a frontier endpoint).

**Note on models:** small local models drive this loop unevenly — they forget to chain steps, malform tool arguments, or stop early. The loop is trivial; the intelligence steering it is the model. Point `.env` at a bigger model and the same six lines behave far better.

---

## The reveal — read this after the lecture

**You have just built an agent.** That is the whole secret: an agent is a `while` loop that keeps calling the model until the model stops asking for tools. No framework, no magic.

1. **The loop is the whole engine.** Six lines of `give_the_llm_hands.py` do the work — they are marked in the source as lines `1`–`6` inside `run_loop()`. Everything else (tool schemas, SQLite, printing, config) is plumbing.
   - `1` the `while True` loop
   - `2` call the model, hand it the tool schemas
   - `3` no tool calls returned → that's the final answer, stop
   - `4` append the model's tool-call message to history
   - `5` execute each requested tool
   - `6` append the results, then loop back to `2`
2. **Tools give the model hands.** Without tools an LLM can only talk. With `wget` and `execute_sql` it can reach the web and write to a database — it *acts*.
3. **Security lives in the scaffolding, not in the prompt.** You do not ask the model nicely to behave; you gate the dangerous action in code. That is the `y` prompt.
4. **The agentic behavior comes from the software, not from the LLM.** The model proposes; your program disposes. Hold on to that sentence — the rest of the course stands on it.
