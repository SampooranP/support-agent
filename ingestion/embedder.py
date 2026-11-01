"""Embed text with Voyage AI."""

from ingestion.config import EMBEDDING_DIM, VOYAGE_MODEL, voyage_client

BATCH_SIZE = 128


def embed_documents(texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        result = voyage_client().embed(batch, model=VOYAGE_MODEL, input_type="document")
        embeddings.extend(result.embeddings)
    _check_dim(embeddings)
    return embeddings


def embed_query(text: str) -> list[float]:
    result = voyage_client().embed([text], model=VOYAGE_MODEL, input_type="query")
    _check_dim(result.embeddings)
    return result.embeddings[0]


def _check_dim(embeddings: list[list[float]]) -> None:
    if embeddings and len(embeddings[0]) != EMBEDDING_DIM:
        raise SystemExit(
            f"{VOYAGE_MODEL} returned {len(embeddings[0])}-dim vectors, "
            f"but the table expects {EMBEDDING_DIM}."
        )
