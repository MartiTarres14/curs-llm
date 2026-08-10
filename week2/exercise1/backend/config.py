"""Configuration, loaded once from the environment.

Required variables have no default. If one is missing the process refuses to
start with a message that says which one and how to fix it — a silent fallback
would just move the failure to the first chat request, where it is harder to
read.

Note what is *not* here any more: the system prompt. In Week 1 there was one
prompt for the whole deployment; from this week on it belongs to an assistant,
so it lives in the store, not in .env.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# In Docker the variables arrive from docker compose; locally they come from the
# .env file next to this project. load_dotenv() never overrides a real env var.
load_dotenv()

# Not configurable on purpose: an upload cap, not a deployment knob. One
# megabyte of plain text is already far more than a small model's context
# window can hold — which is exactly the lesson of this exercise.
MAX_DOCUMENT_BYTES = 1024 * 1024

DEFAULT_MAX_HISTORY_MESSAGES = 20

# Shown in the "new assistant" form so the user starts from something that
# works instead of an empty box.
DEFAULT_SYSTEM_PROMPT = (
    "You are a careful assistant that answers strictly from the document you "
    "are given. You never invent facts."
)

DEFAULT_PROMPT_TEMPLATE = """\
Use only the information in the context below to answer the question.
If the answer is not in the context, say that you do not know.

Context:
----
{context}
----

Question: {user_input}"""


class ConfigError(RuntimeError):
    """Raised at import time when the environment is unusable."""


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    model: str
    data_dir: Path
    max_history_messages: int


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name}. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def _optional_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}.") from None
    if value < 0:
        raise ConfigError(f"{name} must not be negative, got {value}.")
    return value


def load_config() -> Config:
    default_data_dir = Path(__file__).resolve().parent.parent / "data"
    return Config(
        base_url=_required("LLM_BASE_URL"),
        api_key=_required("LLM_API_KEY"),
        model=_required("LLM_MODEL"),
        data_dir=Path(os.getenv("DATA_DIR", "").strip() or default_data_dir),
        max_history_messages=_optional_int(
            "MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES
        ),
    )


config = load_config()
