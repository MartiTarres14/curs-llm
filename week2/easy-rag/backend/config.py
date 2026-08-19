"""Configuration, loaded once from the environment.

Required variables have no default. If one is missing the process refuses to
start with a message that says which one and how to fix it — a silent fallback
would just move the failure to the first chat request, where it is harder to
read.

New this project: the retrieval knobs. K, the similarity threshold and the
chunking strategy are configuration, not constants — the whole lesson of the
week 2 exercises is that the right values depend on the embeddings model and
on the corpus, so they cannot be hard-coded.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# In Docker the variables arrive from docker compose; locally they come from the
# .env file next to this project. load_dotenv() never overrides a real env var.
load_dotenv()

# Raised from exercise 1's 1 MB: uploads are now PDFs and .docx, which carry a
# lot of bytes per character of actual text. markitdown distills them anyway.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

DEFAULT_MAX_HISTORY_MESSAGES = 20

# Shown in the "new assistant" form so the user starts from something that
# works instead of an empty box.
DEFAULT_SYSTEM_PROMPT = (
    "You are a careful assistant that answers strictly from the context you "
    "are given. If the context does not contain the answer, say that you do "
    "not know. You never invent facts."
)

DEFAULT_PROMPT_TEMPLATE = """\
Use only the information in the context below to answer the question.
If the answer is not in the context, say that you do not know.

Context:
----
{context}
----

Question: {user_input}"""

# Sent instead of an answer when no chunk passes the threshold. The model is
# not called at all — an honest refusal, not an answer built from noise.
REFUSAL_MESSAGE = (
    "I don't know — nothing in this assistant's documents is close enough to "
    "your question to answer from. Try rephrasing, or upload a document that "
    "covers it."
)


class ConfigError(RuntimeError):
    """Raised at import time when the environment is unusable."""


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    model: str
    embed_model: str
    data_dir: Path
    max_history_messages: int
    # ---- the retrieval gate ----
    top_k: int
    threshold: float
    # ---- ingestion ----
    chunk_strategy: str  # "sections" | "chars"
    chunk_size: int
    chunk_overlap: int
    section_level: int

    @property
    def static_dir(self) -> Path:
        return self.data_dir / "static"

    @property
    def collections_dir(self) -> Path:
        return self.data_dir / "collections"


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


def _optional_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None


def _strategy() -> str:
    value = os.getenv("CHUNK_STRATEGY", "sections").strip().lower()
    if value not in ("sections", "chars"):
        raise ConfigError(
            f"CHUNK_STRATEGY must be 'sections' or 'chars', got {value!r}."
        )
    return value


def load_config() -> Config:
    default_data_dir = Path(__file__).resolve().parent.parent / "data"
    return Config(
        base_url=_required("LLM_BASE_URL"),
        api_key=_required("LLM_API_KEY"),
        model=_required("LLM_MODEL"),
        # collections_manager reads EMBED_MODEL itself; surfaced here only so
        # /api/health can show which model the vectors come from.
        embed_model=os.getenv("EMBED_MODEL", "nomic-embed-text").strip(),
        data_dir=Path(os.getenv("DATA_DIR", "").strip() or default_data_dir),
        max_history_messages=_optional_int(
            "MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES
        ),
        top_k=_optional_int("RAG_TOP_K", 4),
        threshold=_optional_float("RAG_THRESHOLD", 0.57),
        chunk_strategy=_strategy(),
        chunk_size=_optional_int("CHUNK_SIZE", 800),
        chunk_overlap=_optional_int("CHUNK_OVERLAP", 100),
        section_level=_optional_int("SECTION_LEVEL", 2),
    )


config = load_config()
