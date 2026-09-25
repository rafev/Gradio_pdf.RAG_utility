from paper_rag.ingest.chunking import chunk_pages, clean_text, split_text
from paper_rag.ingest.pdf import slugify


def test_split_text_respects_size_and_overlaps():
    text = " ".join(f"Sentence number {i} talks about retrieval." for i in range(200))
    chunks = split_text(text, size=300, overlap=60)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)
    # consecutive chunks share some text (overlap)
    assert any(chunks[i][-20:].split()[-1] in chunks[i + 1] for i in range(len(chunks) - 1))


def test_split_text_does_not_duplicate_overlap_for_long_paragraphs():
    # One huge paragraph (no "\n\n") forces the recursive path.
    words = [f"w{i}" for i in range(600)]
    text = "Intro para.\n\n" + " ".join(words) + "\n\nOutro para."
    for chunk in split_text(text, size=300, overlap=60):
        tokens = chunk.split()
        # overlap may repeat a word across chunks, never inside one chunk
        assert len(tokens) == len(set(tokens)), chunk


def test_split_text_short_and_empty():
    assert split_text("short", 100, 10) == ["short"]
    assert split_text("   ", 100, 10) == []


def test_clean_text_dehyphenates_and_unwraps():
    assert clean_text("retrie-\nval augmented\ngeneration\n\nNew para") == "retrieval augmented generation\n\nNew para"


def test_chunk_pages_tracks_pages_sections_and_stops_at_references():
    filler = "This paragraph describes the approach in considerable detail for testing purposes. " * 6
    pages = [
        f"Abstract\n{filler}\n1 Introduction\n{filler}",
        f"2 Method\n{filler}\nReferences\n[1] Some cited paper title. 2019.",
        f"[2] Another reference that must not be indexed. {filler}",
    ]
    chunks = chunk_pages("p", pages, size=400, overlap=50)
    assert chunks, "expected chunks"
    assert {c.page for c in chunks} == {1, 2}
    sections = {c.section for c in chunks}
    assert "1 Introduction" in sections and "2 Method" in sections
    assert not any("cited paper title" in c.text for c in chunks)
    assert [c.chunk_n for c in chunks] == list(range(len(chunks)))
    assert chunks[0].id == "p:0"


def test_slugify():
    assert slugify("Attention Is All You Need (2017)") == "attention-is-all-you-need-2017"
    assert slugify("Ünïcödé   paper") == "unicode-paper"
    assert slugify("???") == "paper"
