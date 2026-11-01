"""Split Markdown documents into heading-aware chunks.

Each section (text under a heading) becomes one chunk. Sections longer than
max_chars are split on paragraph boundaries, with the last paragraph of one
piece repeated at the start of the next for context. Paragraphs that are
themselves too long are split by line: a split table repeats its header rows
in every piece, a split code block is closed and reopened, and an overlong
line is cut at a word boundary. Every chunk is prefixed with its document
title and heading path so it can be understood (and embedded) on its own.
"""

import re
from dataclasses import dataclass

from ingestion.loader import Document

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


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
    paragraphs = [part for p in _paragraphs(body) for part in _split_long(p, max_chars)]
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


def _paragraphs(body: str) -> list[str]:
    """Split on blank lines, except inside fenced code blocks."""
    paragraphs: list[str] = []
    lines: list[str] = []
    in_code = False
    for line in body.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        if not line.strip() and not in_code:
            if lines:
                paragraphs.append("\n".join(lines))
                lines = []
            continue
        lines.append(line)
    if lines:
        paragraphs.append("\n".join(lines))
    return paragraphs


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    """Split a paragraph longer than max_chars into pieces by line, keeping each piece readable on its own."""
    if len(paragraph) <= max_chars:
        return [paragraph]
    lines = paragraph.splitlines()
    prefix: list[str] = []  # repeated at the start of every piece
    suffix: list[str] = []  # repeated at the end of every piece
    if len(lines) > 2 and lines[0].lstrip().startswith("|") and TABLE_SEPARATOR.match(lines[1]):
        prefix, lines = lines[:2], lines[2:]  # table: header row + separator row
    elif lines[0].startswith("```") and len(lines) > 1:
        # Code block: every piece opens with the original fence line and closes with ```.
        prefix, suffix = [lines[0]], ["```"]
        lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]

    overhead = len("\n".join(prefix + suffix)) + 2
    budget = max(max_chars - overhead, max_chars // 2)  # always leave room for content
    parts: list[list[str]] = []
    current: list[str] = []
    size = 0
    for line in (piece for line in lines for piece in _wrap(line, budget)):
        if current and size + 1 + len(line) > budget:
            parts.append(current)
            current, size = [], 0
        size += (1 if current else 0) + len(line)
        current.append(line)
    if current:
        parts.append(current)

    return ["\n".join(prefix + part + suffix) for part in parts]


def _wrap(line: str, width: int) -> list[str]:
    """Cut a line longer than width at word boundaries (hard-cutting only words longer than width)."""
    out: list[str] = []
    while len(line) > width:
        cut = line.rfind(" ", 0, width + 1)
        if cut <= 0:
            cut = width
        out.append(line[:cut].rstrip())
        line = line[cut:].lstrip()
    out.append(line)
    return out
