"""Request shapes and the code that turns them into an upstream payload.

Everything the model sees is built here, in one place, so the context view can
show the real thing instead of a reconstruction.
"""

import base64
import binascii
import math
import re
from typing import Literal

from pydantic import BaseModel, Field

from .config import MAX_IMAGE_BYTES, config

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

# data:image/png;base64,AAAA...
_DATA_URL = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<data>.+)$", re.S)


class BadRequest(ValueError):
    """A client mistake worth a 400 and a readable message."""


class ImageUrl(BaseModel):
    url: str


class TextPart(BaseModel):
    type: Literal["text"]
    text: str


class ImagePart(BaseModel):
    type: Literal["image_url"]
    image_url: ImageUrl


class Message(BaseModel):
    # The system prompt is the backend's business, so the client cannot send one.
    role: Literal["user", "assistant"]
    content: str | list[TextPart | ImagePart]


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)


def _validate_image(part: ImagePart) -> None:
    match = _DATA_URL.match(part.image_url.url.strip())
    if not match:
        raise BadRequest(
            "Images must be sent as a base64 data URL "
            "(data:image/png;base64,...); remote URLs are not accepted."
        )

    mime = match.group("mime").lower()
    if mime not in ALLOWED_IMAGE_TYPES:
        raise BadRequest(
            f"Unsupported image type {mime}. "
            f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}."
        )

    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError):
        raise BadRequest("The image is not valid base64.") from None

    if len(raw) > MAX_IMAGE_BYTES:
        # Round the actual size up, so a hair over the limit never prints as
        # "5120 KB; the limit is 5120 KB".
        raise BadRequest(
            f"Image is {math.ceil(len(raw) / 1024)} KB; the limit is "
            f"{MAX_IMAGE_BYTES // 1024} KB."
        )


def has_image(messages: list[Message]) -> bool:
    return any(
        isinstance(message.content, list)
        and any(isinstance(part, ImagePart) for part in message.content)
        for message in messages
    )


def build_payload(request: ChatRequest) -> tuple[list[dict], str]:
    """Return (messages sent upstream, model to send them to).

    Raises BadRequest for images the upstream call would only reject later, or
    that we refuse on our own terms (size, MIME type, vision disabled).
    """
    for message in request.messages:
        if isinstance(message.content, list):
            for part in message.content:
                if isinstance(part, ImagePart):
                    _validate_image(part)

    wants_vision = has_image(request.messages)
    if wants_vision and not config.vision_enabled:
        raise BadRequest(
            "This deployment has no vision model configured. "
            "Set LLM_VISION_MODEL in .env to send images."
        )

    history = request.messages[-config.max_history_messages :]
    payload = [{"role": "system", "content": config.system_prompt}]
    payload += [
        message.model_dump(mode="json", exclude_none=True) for message in history
    ]

    return payload, config.vision_model if wants_vision else config.model
