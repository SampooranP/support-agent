"""Write chunks to and search chunks in Supabase."""

from ingestion.chunker import Chunk
from ingestion.config import CHUNKS_TABLE, MATCH_FUNCTION, supabase_client


def replace_document_chunks(source: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    """Replace all stored chunks for one document, so re-running ingestion is idempotent."""
    db = supabase_client()
    db.table(CHUNKS_TABLE).delete().eq("source", source).execute()
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
        db.table(CHUNKS_TABLE).insert(rows).execute()


def delete_missing_documents(keep_sources: set[str]) -> list[str]:
    """Remove chunks for documents that no longer exist in docs/. Returns removed sources."""
    db = supabase_client()
    stored = db.table(CHUNKS_TABLE).select("source").execute().data
    removed = sorted({row["source"] for row in stored} - keep_sources)
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
