# © 2026 Marc Alier i Forment (Universitat Politècnica de Catalunya) · https://wasabi.essi.upc.edu/ludo · https://lamb-project.org
# BSC Agents Course — Transformers, LLMs, RAG and Agents: From Theory to Production
# Licensed under Creative Commons BY-NC-SA 4.0 — reuse must credit the author, no commercial use, derivatives under the same license.

"""Two plain chunking strategies. No framework — chunking is a for-loop, not a library.

A CHUNK is the unit of retrieval: a piece of a document small enough to embed as
one point and inject into a prompt, big enough to still mean something on its own.
How you cut the document decides what your retriever can find.

  chunk_by_chars(text, size, overlap)   — a sliding window: `size` characters per
      chunk, stepping by size-overlap. The overlap is a shared margin so a fact
      split at a boundary still survives whole in one of the chunks.
      Works on ANY text; ignores the document's own structure.

  chunk_by_sections(markdown, level)    — split a markdown document at its own
      headings (level=2 cuts at ##, level=4 at ####). Each chunk is one section,
      heading included, so it carries its own title as context.
      Respects the author's structure; chunk sizes vary with the document.
"""

import re


def chunk_by_chars(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    """Sliding window of `size` characters, stepping by size-overlap."""
    step = max(1, size - overlap)
    chunks = []
    i = 0
    while i < len(text):
        piece = text[i:i + size].strip()
        if piece:
            chunks.append(piece)
        i += step
    return chunks


def chunk_by_sections(markdown: str, level: int = 2) -> list[str]:
    """Split a markdown document at headings of `level` (2 = ##, 4 = ####).

    Everything before the first heading (title, intro) becomes chunk 0 if it is
    not empty. Each following chunk is one section, its heading included.
    """
    heading = re.compile(rf"^#{{{level}}}\s", flags=re.MULTILINE)
    starts = [m.start() for m in heading.finditer(markdown)]
    if not starts:
        return [markdown.strip()] if markdown.strip() else []
    cuts = [0] + starts + [len(markdown)]
    chunks = []
    for a, b in zip(cuts, cuts[1:]):
        piece = markdown[a:b].strip()
        if piece:
            chunks.append(piece)
    return chunks
