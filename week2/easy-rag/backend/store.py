"""Persistence of the assistants. Still no database for THEM — a JSON file.

    data/assistants.json      the assistants and their documents' metadata
    data/static/…             originals + markdown, served over /static
    data/collections/…        the chunks, in each assistant's collection

The knowledge moved out of this module this week: exercise 1 kept one text
file per assistant here; now the text lives as chunks in a ChromaDB collection
behind the collections manager, and this store only remembers the metadata —
which documents an assistant has and where their files are linked.

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
    """No assistant (or document) with that id."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir
        self.file = data_dir / "assistants.json"
        # Writes are serialised: two uploads landing at once would otherwise
        # race to rewrite the same file and one would win silently.
        self._lock = asyncio.Lock()
        self._assistants: dict[str, Assistant] = {}

    # ------------------------------------------------------------------ disk

    def load(self) -> None:
        """Read the file into memory. Called once, at startup."""
        self.dir.mkdir(parents=True, exist_ok=True)
        config.static_dir.mkdir(parents=True, exist_ok=True)
        config.collections_dir.mkdir(parents=True, exist_ok=True)
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
            "version": 2,
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
                id=new_id(),
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
            self._write()

    # -------------------------------------------------------------- documents

    async def add_document(self, assistant_id: str, document: Document) -> Assistant:
        async with self._lock:
            current = self.get(assistant_id)
            updated = current.model_copy(
                update={
                    "documents": [*current.documents, document],
                    "updated_at": _now(),
                }
            )
            self._assistants[assistant_id] = updated
            self._write()
            return updated

    def get_document(self, assistant_id: str, doc_id: str) -> Document:
        assistant = self.get(assistant_id)
        for document in assistant.documents:
            if document.id == doc_id:
                return document
        raise NotFound(doc_id)

    async def remove_document(self, assistant_id: str, doc_id: str) -> Assistant:
        async with self._lock:
            current = self.get(assistant_id)
            remaining = [d for d in current.documents if d.id != doc_id]
            if len(remaining) == len(current.documents):
                raise NotFound(doc_id)
            updated = current.model_copy(
                update={"documents": remaining, "updated_at": _now()}
            )
            self._assistants[assistant_id] = updated
            self._write()
            return updated


store = Store(config.data_dir)
