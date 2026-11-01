"""Load, chunk, embed and store the knowledge base.

Usage (from the repo root):
    python -m ingestion.ingest            # ingest everything in docs/
    python -m ingestion.ingest --dry-run  # chunk only; no API or database calls
"""

import argparse

from ingestion.chunker import chunk_document
from ingestion.loader import load_documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print chunks without embedding or storing them")
    parser.add_argument("--max-chars", type=int, default=1500, help="maximum characters per chunk")
    args = parser.parse_args()

    documents = load_documents()
    if not documents:
        raise SystemExit("No Markdown documents found in docs/.")

    chunks_by_doc = {doc.source: chunk_document(doc, max_chars=args.max_chars) for doc in documents}
    total = sum(len(chunks) for chunks in chunks_by_doc.values())

    if args.dry_run:
        for source, chunks in chunks_by_doc.items():
            print(f"{source}: {len(chunks)} chunks")
            for c in chunks:
                print(f"  [{c.chunk_index}] {c.section or '(intro)'} ({len(c.content)} chars)")
        print(f"Done: {len(documents)} documents, {total} chunks (dry run, nothing stored).")
        return

    from ingestion.embedder import embed_documents
    from ingestion.store import delete_missing_documents, replace_document_chunks

    # Embed every chunk up front, in as few API requests as possible.
    all_chunks = [c for chunks in chunks_by_doc.values() for c in chunks]
    embeddings = iter(embed_documents([c.content for c in all_chunks]))
    print(f"Embedded {total} chunks with Voyage.")

    for source, chunks in chunks_by_doc.items():
        replace_document_chunks(source, chunks, [next(embeddings) for _ in chunks])
        print(f"{source}: stored {len(chunks)} chunks")

    for source in delete_missing_documents(set(chunks_by_doc)):
        print(f"{source}: removed (no longer in docs/)")

    print(f"Done: {len(documents)} documents, {total} chunks.")


if __name__ == "__main__":
    main()
