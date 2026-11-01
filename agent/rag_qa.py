"""Answer a question from the knowledge base, with citations.

Embeds the question with Voyage AI, retrieves the closest chunks from Supabase,
and passes each chunk to Claude as a citable document.

Usage (from the repo root):
    python -m agent.rag_qa "My order arrived damaged, can I get a refund?"
    python -m agent.rag_qa            # interactive: ask questions until you enter a blank line
"""

import argparse
import sys

import anthropic

from ingestion.config import require_env
from ingestion.embedder import embed_query
from ingestion.store import match_chunks

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are a customer support assistant for Lumen & Pine, an online store for outdoor gear and home goods.

Answer the customer's question using only the support documents provided with it. Cite the documents that support each claim. If the documents don't answer the question, say so plainly and suggest the customer contact support; don't guess at policies, prices, or timelines.

Keep answers short and friendly, and address the customer directly."""


def retrieve(question: str, top_k: int) -> list[dict]:
    return match_chunks(embed_query(question), match_count=top_k)


def ask_claude(client: anthropic.Anthropic, question: str, chunks: list[dict]):
    documents = [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": chunk["content"]},
            "title": _label(chunk),
            "citations": {"enabled": True},
        }
        for chunk in chunks
    ]
    return client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        # If a safety classifier declines the request, retry it server-side on Anthropic's recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [*documents, {"type": "text", "text": question}]}],
    )


def format_answer(response, chunks: list[dict]) -> str:
    """Render the answer with [n] markers after cited passages, then a numbered source list."""
    if response.stop_reason == "refusal":
        return "Sorry, I can't help with that request. Please contact support."

    numbers: dict[int, int] = {}  # document index -> citation number
    parts: list[str] = []
    for block in response.content:
        if block.type != "text":
            continue
        parts.append(block.text)
        markers = []
        for citation in block.citations or []:
            n = numbers.setdefault(citation.document_index, len(numbers) + 1)
            if f"[{n}]" not in markers:
                markers.append(f"[{n}]")
        if markers:
            parts.append("".join(markers))

    answer = "".join(parts).strip()
    if response.stop_reason == "max_tokens":
        answer += "\n\n(Answer cut off: hit max_tokens.)"
    if numbers:
        answer += "\n\nSources:"
        for doc_index, n in sorted(numbers.items(), key=lambda item: item[1]):
            answer += f"\n  [{n}] {_label(chunks[doc_index])}"
    return answer


def answer_question(client: anthropic.Anthropic, question: str, top_k: int, show_chunks: bool) -> str:
    chunks = retrieve(question, top_k)
    if show_chunks:
        print("Retrieved chunks:")
        for chunk in chunks:
            print(f"  {chunk['similarity']:.3f}  {_label(chunk)}")
        print()
    if not chunks:
        return "The knowledge base is empty. Run `python -m ingestion.ingest` first."
    return format_answer(ask_claude(client, question, chunks), chunks)


def _label(chunk: dict) -> str:
    return f"{chunk['source']} - {chunk['section']}" if chunk["section"] else chunk["source"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", help="question to answer; omit for interactive mode")
    parser.add_argument("--top-k", type=int, default=5, help="number of chunks to retrieve")
    parser.add_argument("--show-chunks", action="store_true", help="print the retrieved chunks and their similarity")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")  # docs contain characters like the en dash
    client = anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))

    if args.question:
        print(answer_question(client, args.question, args.top_k, args.show_chunks))
        return
    while True:
        try:
            question = input("\nQuestion (blank to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        print()
        print(answer_question(client, question, args.top_k, args.show_chunks))


if __name__ == "__main__":
    main()
