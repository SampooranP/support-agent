"""Write chunks to and search chunks in Supabase."""

from ingestion.chunker import Chunk
from ingestion.config import CHUNKS_TABLE, MATCH_FUNCTION, supabase_client


def replace_document_chunks(source: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
    """Replace all stored chunks for one document in a single transaction (see replace_doc_chunks in
    supabase/migrations), so re-running ingestion is idempotent and never leaves old and new chunks mixed."""
    payload = [
        {
            "doc_title": c.doc_title,
            "section": c.section,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "embedding": e,
        }
        for c, e in zip(chunks, embeddings, strict=True)
    ]
    supabase_client().rpc("replace_doc_chunks", {"p_source": source, "p_chunks": payload}).execute()


def delete_missing_documents(keep_sources: set[str]) -> list[str]:
    """Remove chunks for documents that no longer exist in docs/. Returns removed sources."""
    db = supabase_client()
    stored = {row["source"] for row in db.rpc("doc_chunk_sources").execute().data}
    removed = sorted(stored - keep_sources)
    for source in removed:
        db.table(CHUNKS_TABLE).delete(returning="minimal").eq("source", source).execute()
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
