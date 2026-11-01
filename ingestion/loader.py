"""Load Markdown documents from the knowledge base."""

from dataclasses import dataclass
from pathlib import Path

from ingestion.config import DOCS_DIR


@dataclass
class Document:
    source: str  # path relative to docs/, with forward slashes
    title: str
    text: str


def load_documents(docs_dir: Path = DOCS_DIR) -> list[Document]:
    """Read every .md file under docs_dir, skipping README files."""
    documents = []
    for path in sorted(docs_dir.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8-sig")
        documents.append(
            Document(
                source=path.relative_to(docs_dir).as_posix(),
                title=_title(text, fallback=path.stem),
                text=text,
            )
        )
    return documents


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback
