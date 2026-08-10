"""Persistence. No database — a JSON file and one text file per document.

    data/assistants.json      the assistants, without their document text
    data/documents/<id>.txt   the uploaded document, verbatim

The document text is kept out of the JSON on purpose: a 200 KB file escaped
onto one JSON line turns assistants.json into something you cannot open and
read, and being able to open it and read it is most of the point of choosing a
JSON file in the first place.

Everything is loaded into memory at startup and written back in full on every
change. That is fine for a teaching app with a handful of assistants, and it
keeps the code short enough to check by eye.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .assistants import Assistant, AssistantIn, Document
from .config import config

log = logging.getLogger(__name__)


class NotFound(KeyError):
    """No assistant with that id."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir
        self.file = data_dir / "assistants.json"
        self.documents = data_dir / "documents"
        # Writes are serialised: two uploads landing at once would otherwise
        # race to rewrite the same file and one would win silently.
        self._lock = asyncio.Lock()
        self._assistants: dict[str, Assistant] = {}

    # ------------------------------------------------------------------ disk

    def load(self) -> None:
        """Read the file into memory. Called once, at startup."""
        self.documents.mkdir(parents=True, exist_ok=True)
        if not self.file.exists():
            log.info("no store at %s yet; starting empty", self.file)
            return

        raw = json.loads(self.file.read_text(encoding="utf-8"))
        self._assistants = {
            item["id"]: Assistant.model_validate(item) for item in raw["assistants"]
        }
        log.info("loaded %d assistant(s) from %s", len(self._assistants), self.file)

    def _write(self) -> None:
        """Write via a temp file and rename, so a crash never truncates the store."""
        body = {
            "version": 1,
            "assistants": [a.model_dump() for a in self._assistants.values()],
        }
        temp = self.file.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temp, self.file)

    # ------------------------------------------------------------ assistants

    def list(self) -> list[Assistant]:
        return sorted(self._assistants.values(), key=lambda a: a.created_at)

    def get(self, assistant_id: str) -> Assistant:
        try:
            return self._assistants[assistant_id]
        except KeyError:
            raise NotFound(assistant_id) from None

    async def create(self, payload: AssistantIn) -> Assistant:
        async with self._lock:
            stamp = _now()
            assistant = Assistant(
                id=uuid.uuid4().hex[:12],
                name=payload.name,
                system_prompt=payload.system_prompt,
                prompt_template=payload.prompt_template,
                created_at=stamp,
                updated_at=stamp,
            )
            self._assistants[assistant.id] = assistant
            self._write()
            return assistant

    async def update(self, assistant_id: str, payload: AssistantIn) -> Assistant:
        async with self._lock:
            current = self.get(assistant_id)
            updated = current.model_copy(
                update={
                    "name": payload.name,
                    "system_prompt": payload.system_prompt,
                    "prompt_template": payload.prompt_template,
                    "updated_at": _now(),
                }
            )
            self._assistants[assistant_id] = updated
            self._write()
            return updated

    async def delete(self, assistant_id: str) -> None:
        async with self._lock:
            self.get(assistant_id)
            del self._assistants[assistant_id]
            self._document_path(assistant_id).unlink(missing_ok=True)
            self._write()

    # -------------------------------------------------------------- documents

    def _document_path(self, assistant_id: str) -> Path:
        return self.documents / f"{assistant_id}.txt"

    def document_text(self, assistant_id: str) -> str:
        """The uploaded text, or "" if this assistant has no document."""
        assistant = self.get(assistant_id)
        if assistant.document is None:
            return ""
        path = self._document_path(assistant_id)
        if not path.exists():
            # The metadata says there is a file and there is not. Say so rather
            # than silently answering from an empty context.
            log.error("document missing on disk for assistant %s", assistant_id)
            raise NotFound(f"document for {assistant_id}")
        return path.read_text(encoding="utf-8")

    async def put_document(
        self, assistant_id: str, filename: str, text: str
    ) -> Assistant:
        async with self._lock:
            current = self.get(assistant_id)
            self._document_path(assistant_id).write_text(text, encoding="utf-8")
            updated = current.model_copy(
                update={
                    "document": Document(
                        filename=filename,
                        chars=len(text),
                        bytes=len(text.encode("utf-8")),
                        uploaded_at=_now(),
                    ),
                    "updated_at": _now(),
                }
            )
            self._assistants[assistant_id] = updated
            self._write()
            return updated

    async def remove_document(self, assistant_id: str) -> Assistant:
        async with self._lock:
            current = self.get(assistant_id)
            self._document_path(assistant_id).unlink(missing_ok=True)
            updated = current.model_copy(
                update={"document": None, "updated_at": _now()}
            )
            self._assistants[assistant_id] = updated
            self._write()
            return updated


store = Store(config.data_dir)
