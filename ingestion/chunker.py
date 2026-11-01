"""Split Markdown documents into heading-aware chunks.

Each section (text under a heading) becomes one chunk. Sections longer than
max_chars are split on paragraph boundaries, with the last paragraph of one
piece repeated at the start of the next for context. Every chunk is prefixed
with its document title and heading path so it can be understood (and
embedded) on its own.
"""

import re
from dataclasses import dataclass

from ingestion.loader import Document

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    source: str
    doc_title: str
    section: str | None
    chunk_index: int
    content: str


def chunk_document(doc: Document, max_chars: int = 1500) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, body in _sections(doc.text):
        for piece in _split_paragraphs(body, max_chars):
            header = doc.title if not section else f"{doc.title} > {section}"
            chunks.append(
                Chunk(
                    source=doc.source,
                    doc_title=doc.title,
                    section=section,
                    chunk_index=len(chunks),
                    content=f"{header}\n\n{piece}",
                )
            )
    return chunks


def _sections(text: str) -> list[tuple[str | None, str]]:
    """Return (heading path, body) pairs. The H1 is the title, not part of the path."""
    path: list[tuple[int, str]] = []
    sections: list[tuple[str | None, str]] = []
    lines: list[str] = []

    def flush():
        body = "\n".join(lines).strip()
        if body:
            sections.append((" > ".join(h for _, h in path) or None, body))
        lines.clear()

    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        match = None if in_code else HEADING.match(line)
        if not match:
            lines.append(line)
            continue
        flush()
        level, heading = len(match.group(1)), match.group(2).strip()
        if level == 1:
            path = []
            continue
        path = [(lvl, h) for lvl, h in path if lvl < level] + [(level, heading)]
    flush()
    return sections


def _split_paragraphs(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    paragraphs = [
        part
        for p in re.split(r"\n\s*\n", body)
        if p.strip()
        for part in _split_long(p.strip(), max_chars)
    ]
    pieces: list[str] = []
    current: list[str] = []
    for para in paragraphs:
        if current and len("\n\n".join(current + [para])) > max_chars:
            pieces.append("\n\n".join(current))
            # Overlap: carry the last paragraph forward, but only if it still fits with the next one.
            last = current[-1]
            current = [last] if len(last) + 2 + len(para) <= max_chars else []
        current.append(para)
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    """Split a paragraph longer than max_chars on line breaks (tables, lists), then on hard length."""
    if len(paragraph) <= max_chars:
        return [paragraph]
    parts: list[str] = []
    current = ""
    for line in paragraph.splitlines():
        while len(line) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:max_chars])
            line = line[max_chars:]
        if current and len(current) + 1 + len(line) > max_chars:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts
