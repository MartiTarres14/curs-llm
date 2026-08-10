"""Thin wrapper over the OpenAI-compatible endpoint.

This is the only module that talks to the model. It knows nothing about HTTP
requests from the browser, and the browser knows nothing about what is in here.
"""

import json
import logging
from collections.abc import AsyncIterator

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
)

from .config import config

log = logging.getLogger(__name__)

# Generous, because a small model on CPU can take minutes for a long answer —
# and this week every prompt carries a whole document, so it is slower still.
TIMEOUT_SECONDS = 600.0

# max_retries=0 on purpose: a generation that timed out is not a transient
# network blip. Retrying it just queues the same slow work again and multiplies
# the wait the user sits through.
client = AsyncOpenAI(
    base_url=config.base_url,
    api_key=config.api_key,
    timeout=TIMEOUT_SECONDS,
    max_retries=0,
)


class UpstreamError(RuntimeError):
    """The model endpoint failed. Message is safe to show a user."""


def _estimate_tokens(text: str) -> int:
    """Rough count for providers that do not report usage. ~4 chars per token."""
    return max(1, len(text) // 4)


def estimate_usage(payload: list[dict], answer: str) -> dict:
    prompt = _estimate_tokens(json.dumps(payload, ensure_ascii=False))
    completion = _estimate_tokens(answer)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "estimated": True,
    }


def _usage_dict(usage) -> dict | None:
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "estimated": False,
    }


def describe(error: Exception) -> str:
    """Turn an SDK exception into something worth putting on screen."""
    if isinstance(error, APITimeoutError):
        return (
            f"The LLM did not answer within {int(TIMEOUT_SECONDS)} s. "
            "Every turn sends the whole document, so a long file on a small "
            "local model can be this slow — try a shorter document, or point "
            "LLM_BASE_URL at a faster endpoint."
        )
    if isinstance(error, APIConnectionError):
        return (
            f"Cannot reach the LLM at {config.base_url}. "
            "Is it running, and is LLM_BASE_URL correct?"
        )
    if isinstance(error, APIStatusError):
        detail = ""
        try:
            body = error.response.json()
            detail = body.get("error", {}).get("message") or body.get("error") or ""
        except Exception:  # noqa: BLE001 - a non-JSON error body is not worth a crash
            detail = (error.response.text or "").strip()[:200]
        return f"The LLM returned HTTP {error.status_code}. {detail}".strip()
    return f"Unexpected error talking to the LLM: {error}"


async def complete(payload: list[dict]) -> tuple[str, dict]:
    """Wait for the whole answer. Returns (text, usage)."""
    try:
        response = await client.chat.completions.create(
            model=config.model, messages=payload
        )
    except Exception as error:
        log.warning("upstream completion failed: %s", error)
        raise UpstreamError(describe(error)) from error

    answer = response.choices[0].message.content or ""
    return answer, _usage_dict(response.usage) or estimate_usage(payload, answer)


async def _open_stream(payload: list[dict]):
    """Ask for usage in the final chunk; retry without if the provider objects."""
    try:
        return await client.chat.completions.create(
            model=config.model,
            messages=payload,
            stream=True,
            stream_options={"include_usage": True},
        )
    except BadRequestError:
        log.info("provider rejected stream_options; falling back to estimated usage")
        return await client.chat.completions.create(
            model=config.model, messages=payload, stream=True
        )


async def stream(payload: list[dict]) -> AsyncIterator[dict]:
    """Yield {"type": "delta"|"usage"|"error"} as the upstream chunks arrive.

    Chunks are relayed one by one — nothing is buffered and replayed. The text
    is accumulated only so usage can be estimated if the provider never sends
    it.
    """
    answer: list[str] = []
    usage: dict | None = None

    try:
        upstream = await _open_stream(payload)
        async for chunk in upstream:
            if chunk.usage is not None:
                usage = _usage_dict(chunk.usage)
            # A usage-only final chunk carries no choices.
            if not chunk.choices:
                continue
            piece = chunk.choices[0].delta.content
            if piece:
                answer.append(piece)
                yield {"type": "delta", "content": piece}
    except Exception as error:
        log.warning("upstream stream failed: %s", error)
        yield {"type": "error", "message": describe(error)}
        return

    yield {"type": "usage", "usage": usage or estimate_usage(payload, "".join(answer))}
