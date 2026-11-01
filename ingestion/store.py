"""Write chunks to and search chunks in Supabase."""

from ingestion.chunker import Chunk
from ingestion.config import CHUNKS_TABLE, MATCH_FUNCTION, supabase_client


def replace_document_chunks(source: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    """Replace all stored chunks for one document, so re-running ingestion is idempotent.

    Upserts first and only then trims chunks past the new end, so a failed run never
    leaves a document missing from the table.
    """
    db = supabase_client()
    rows = [
        {
            "source": c.source,
            "doc_title": c.doc_title,
            "section": c.section,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "embedding": e,
        }
        for c, e in zip(chunks, embeddings, strict=True)
    ]
    if rows:
        db.table(CHUNKS_TABLE).upsert(rows, on_conflict="source,chunk_index", returning="minimal").execute()
    db.table(CHUNKS_TABLE).delete(returning="minimal").eq("source", source).gte("chunk_index", len(rows)).execute()


def delete_missing_documents(keep_sources: set[str]) -> list[str]:
    """Remove chunks for documents that no longer exist in docs/. Returns removed sources."""
    db = supabase_client()
    stored: set[str] = set()
    page = 1000  # Supabase returns at most 1000 rows per request, so read in pages
    for start in range(0, 10**9, page):
        rows = db.table(CHUNKS_TABLE).select("source").order("id").range(start, start + page - 1).execute().data
        stored.update(row["source"] for row in rows)
        if len(rows) < page:
            break
    removed = sorted(stored - keep_sources)
    for source in removed:
        db.table(CHUNKS_TABLE).delete().eq("source", source).execute()
    return removed


def match_chunks(query_embedding: list[float], match_count: int = 5, min_similarity: float = 0.0) -> list[dict]:
    response = supabase_client().rpc(
        MATCH_FUNCTION,
        {
            "query_embedding": query_embedding,
            "match_count": match_count,
            "min_similarity": min_similarity,
        },
    ).execute()
    return response.data
