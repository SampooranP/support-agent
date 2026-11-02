from ingestion.chunker import _split_paragraphs, chunk_document
from ingestion.loader import Document

MAX = 1000


def test_short_section_is_one_chunk_with_title_and_heading():
    doc = Document("x.md", "Title", "# Title\n\nIntro.\n\n## Returns\n\nThirty days.")
    chunks = chunk_document(doc, max_chars=MAX)
    assert [c.section for c in chunks] == [None, "Returns"]
    assert chunks[1].content == "Title > Returns\n\nThirty days."
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_nested_headings_build_a_path():
    doc = Document("x.md", "T", "# T\n\n## Orders\n\n### Tracking\n\nUse the link.")
    assert chunk_document(doc)[0].section == "Orders > Tracking"


def test_overlap_never_duplicates_or_exceeds_the_limit():
    pieces = _split_paragraphs("\n\n".join(["A" * 900, "B" * 400, "C" * 400]), MAX)
    assert all(len(p) <= MAX for p in pieces)
    assert sum(p.count("A" * 900) for p in pieces) == 1


def test_split_table_repeats_its_header():
    table = "| Method | Cost |\n|---|---|\n" + "\n".join(f"| m{i} | ${i}.99 |" for i in range(120))
    pieces = _split_paragraphs(table, MAX)
    assert len(pieces) > 1
    assert all(p.startswith("| Method | Cost |\n|---|---|") and len(p) <= MAX for p in pieces)


def test_split_code_block_stays_fenced_and_keeps_blank_lines_together():
    code = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(200)) + "\n\n# after blank\n```"
    pieces = _split_paragraphs(code, MAX)
    assert all(p.startswith("```python") and p.endswith("```") for p in pieces)
    assert any("# after blank" in p for p in pieces)


def test_long_lines_are_cut_between_words():
    pieces = _split_paragraphs(" ".join(["policy"] * 500), MAX)
    assert all(set(p.split()) == {"policy"} for p in pieces)
