"""Configuration, loaded once from the environment.

Required variables have no default. If one is missing the process refuses to
start with a message that says which one and how to fix it — a silent fallback
would just move the failure to the first chat request, where it is harder to
read.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# In Docker the variables arrive from docker compose; locally they come from the
# .env file next to this project. load_dotenv() never overrides a real env var.
load_dotenv()

# Not configurable on purpose: an upload cap, not a deployment knob.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
DEFAULT_MAX_HISTORY_MESSAGES = 20


class ConfigError(RuntimeError):
    """Raised at import time when the environment is unusable."""


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    model: str
    vision_model: str  # "" means vision is disabled
    system_prompt: str
    max_history_messages: int

    @property
    def vision_enabled(self) -> bool:
        return bool(self.vision_model)


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
    if value < 1:
        raise ConfigError(f"{name} must be at least 1, got {value}.")
    return value


def load_config() -> Config:
    return Config(
        base_url=_required("LLM_BASE_URL"),
        api_key=_required("LLM_API_KEY"),
        model=_required("LLM_MODEL"),
        vision_model=os.getenv("LLM_VISION_MODEL", "").strip(),
        system_prompt=os.getenv("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
        max_history_messages=_optional_int(
            "MAX_HISTORY_MESSAGES", DEFAULT_MAX_HISTORY_MESSAGES
        ),
    )


config = load_config()
