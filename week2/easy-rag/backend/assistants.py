"""What an assistant is, and how one turn becomes an upstream payload.

Everything the model sees is built here, in one place, so the context panel in
the browser can show the real thing instead of a reconstruction.

The difference from exercise 1 is what goes into {context}: not the whole
document any more, but the few chunks retrieval picked for THIS question.
The template mechanics are identical — that is the point of the week: the
prompt did not change, only what fills the gap did.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from .config import config

CONTEXT_SLOT = "{context}"
USER_INPUT_SLOT = "{user_input}"

# Matched in one pass, on purpose — see fill_template().
_SLOTS = re.compile(r"\{(context|user_input)\}")


class BadRequest(ValueError):
    """A client mistake worth a 400 and a readable message."""


# --------------------------------------------------------------- the assistant


class AssistantIn(BaseModel):
    """The three things a user types when creating or editing an assistant."""

    name: str = Field(min_length=1, max_length=80)
    system_prompt: str = Field(min_length=1, max_length=8000)
    prompt_template: str = Field(min_length=1, max_length=8000)


class Document(BaseModel):
    """One ingested document: where it lives and how it was chunked.

    The text itself is not here — the original and its markdown distillation
    are files under /static, and the chunks live in the assistant's collection.
    """

    id: str
    filename: str
    title: str
    doc_url: str
    md_url: str
    markdown_chars: int
    chunks: int
    chunking_strategy: str
    uploaded_at: str


class Assistant(BaseModel):
    """An assistant as stored on disk: prompts here, knowledge elsewhere."""

    id: str
    name: str
    system_prompt: str
    prompt_template: str
    documents: list[Document] = []
    created_at: str
    updated_at: str


def validate_template(template: str) -> None:
    """Both gaps must be present, or retrieval would never reach the model.

    This is the one rule worth enforcing server-side: an assistant whose
    template forgot {context} looks like it works, and quietly answers from
    training data instead of from the retrieved chunks.
    """
    missing = [s for s in (CONTEXT_SLOT, USER_INPUT_SLOT) if s not in template]
    if missing:
        raise BadRequest(
            f"The prompt template must contain {' and '.join(missing)}. "
            f"Both {CONTEXT_SLOT} and {USER_INPUT_SLOT} are required."
        )


def clean(payload: AssistantIn) -> AssistantIn:
    """Trim the fields, then check the template. Raises BadRequest."""
    tidied = AssistantIn(
        name=payload.name.strip(),
        system_prompt=payload.system_prompt.strip(),
        prompt_template=payload.prompt_template.strip(),
    )
    if not tidied.name:
        raise BadRequest("The assistant needs a name.")
    validate_template(tidied.prompt_template)
    return tidied


# ------------------------------------------------------------- building a turn


class Message(BaseModel):
    # The system prompt is the assistant's business, so the client cannot send
    # one — it would let the browser overwrite the assistant's instructions.
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)


def fill_template(template: str, context: str, user_input: str) -> str:
    """Substitute both gaps in a single pass.

    Deliberately not str.format(): a chunk full of braces — JSON, code, a
    LaTeX snippet — would blow it up with a KeyError. And a naive
    .replace().replace() would rescan the text it just inserted, so a chunk
    that happens to contain the literal "{user_input}" would swallow the
    user's question. One regex pass substitutes each gap exactly once and
    never looks at what it wrote.
    """
    values = {"context": context, "user_input": user_input}
    return _SLOTS.sub(lambda match: values[match.group(1)], template)


def last_user_message(request: ChatRequest) -> str:
    if request.messages[-1].role != "user":
        raise BadRequest("The last message must be the user's question.")
    return request.messages[-1].content


def build_payload(
    assistant: Assistant, context: str, request: ChatRequest
) -> tuple[list[dict], str]:
    """Return (messages sent upstream, the filled prompt for the current turn).

    The layout is:

        system   -> the assistant's system prompt
        user     -> earlier questions, as the user typed them
        assistant-> earlier answers
        user     -> THIS turn's question, wrapped in the filled template

    Only the last turn carries context — and now that context is a handful of
    retrieved chunks, not the whole corpus. This is where prompt_tokens stops
    growing with the size of the knowledge.
    """
    question = last_user_message(request)

    history = request.messages[:-1]
    if config.max_history_messages:
        history = history[-config.max_history_messages :]

    filled = fill_template(assistant.prompt_template, context, question)

    payload = [{"role": "system", "content": assistant.system_prompt}]
    payload += [message.model_dump() for message in history]
    payload.append({"role": "user", "content": filled})

    return payload, filled
