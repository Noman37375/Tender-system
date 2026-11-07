import pytest

from app.ingestion.chunker import (
    PageInput,
    chunk_pages,
    estimate_tokens,
    is_heading_line,
)


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i:04d}" for i in range(n))


def test_estimate_tokens_is_chars_over_four() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


@pytest.mark.parametrize(
    "line",
    [
        "1. Introduction",
        "2.3 Scope of Work",
        "SECTION 3: ELIGIBILITY CRITERIA",
        "Section 5 - Evaluation Criteria",
        "INVITATION FOR BIDS",
        "Annex A Technical Specifications",
        "IV. General Conditions",
    ],
)
def test_heading_lines_detected(line: str) -> None:
    assert is_heading_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "1. The bidder shall submit a bid security with the bid",
        "Section 5 of this document applies to all bidders",
        "This sentence ends with a period.",
        "The bidder must have completed at least three similar projects in the last five years "
        "with a value above PKR 50 million each",
        "12",
        "",
        "Qty",
    ],
)
def test_non_headings_rejected(line: str) -> None:
    assert not is_heading_line(line)


def test_empty_input_gives_no_chunks() -> None:
    assert chunk_pages([]) == []
    assert chunk_pages([PageInput(1, "   \n\n")]) == []


def test_small_document_is_one_chunk_with_page_range() -> None:
    pages = [PageInput(1, "Para one text here"), PageInput(2, "Para two text here")]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)
    assert chunks[0].section_heading is None
    assert "Para one" in chunks[0].content and "Para two" in chunks[0].content


def test_headings_start_new_chunks_and_label_them() -> None:
    text = (
        "1. Introduction\nThe purchaser invites bids.\n\n"
        "2. Eligibility Criteria\nBidders must be registered with tax authorities."
    )
    chunks = chunk_pages([PageInput(1, text)])
    assert [c.section_heading for c in chunks] == ["1. Introduction", "2. Eligibility Criteria"]
    assert chunks[0].content.startswith("1. Introduction")
    assert "registered" in chunks[1].content and "invites" not in chunks[1].content


def test_stacked_headings_stay_with_their_body() -> None:
    text = "PART II\n3.1 Scope of Work\nSupply and install network equipment."
    chunks = chunk_pages([PageInput(1, text)])
    assert len(chunks) == 1
    assert chunks[0].section_heading == "3.1 Scope of Work"
    assert chunks[0].content.startswith("PART II")


def test_long_section_split_near_target_with_overlap() -> None:
    paragraphs = "\n\n".join(words(60, f"p{i}-") for i in range(40))  # ~ 40 x 120 tokens
    chunks = chunk_pages([PageInput(1, "1. Scope Of Supply\n" + paragraphs)], 800, 100)
    assert len(chunks) > 3
    for chunk in chunks:
        assert chunk.token_count <= 800 + 10
        assert chunk.section_heading == "1. Scope Of Supply"
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        tail = prev.content[-200:]
        assert tail.split()[-1] in nxt.content  # the overlap carries the previous ending


def test_oversized_paragraph_is_split_and_overlap_never_exceeds_limit() -> None:
    chunks = chunk_pages([PageInput(1, words(2000))], target_tokens=200, overlap_tokens=50)
    assert len(chunks) > 5
    assert all(c.token_count <= 210 for c in chunks)
    joined = " ".join(c.content for c in chunks)
    assert "w0000" in joined and "w1999" in joined


def test_no_overlap_across_sections() -> None:
    body_a = "\n\n".join(words(50, f"a{i}-") for i in range(30))
    text = f"1. First Section\n{body_a}\n2. Second Section\nshort body"
    chunks = chunk_pages([PageInput(1, text)], 400, 50)
    second = [c for c in chunks if c.section_heading == "2. Second Section"]
    assert len(second) == 1
    assert "a29-" not in second[0].content


def test_chunks_spanning_pages_record_both_pages() -> None:
    pages = [
        PageInput(p, "\n\n".join(words(40, f"pg{p}-{i}-") for i in range(5))) for p in (1, 2, 3)
    ]
    chunks = chunk_pages(pages, 300, 30)
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 3
    assert any(c.page_start < c.page_end for c in chunks)
    for chunk in chunks:
        for p in range(1, 4):
            if f"pg{p}-" in chunk.content:
                assert chunk.page_start <= p <= chunk.page_end


def test_explicit_headings_override_heuristics() -> None:
    page = PageInput(
        1,
        "Company Overview\nWe build networks.\nINVITATION FOR BIDS mention",
        frozenset({"Company Overview"}),
    )
    chunks = chunk_pages([page])
    assert len(chunks) == 1
    assert chunks[0].section_heading == "Company Overview"


def test_explicit_empty_heading_set_disables_heuristics() -> None:
    chunks = chunk_pages([PageInput(1, "INVITATION FOR BIDS\nbody text", frozenset())])
    assert len(chunks) == 1 and chunks[0].section_heading is None


def test_trailing_heading_without_body_is_kept() -> None:
    chunks = chunk_pages([PageInput(1, "body text\n9. Annexes")])
    assert [c.section_heading for c in chunks] == [None, "9. Annexes"]


def test_invalid_overlap_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_pages([PageInput(1, "x")], target_tokens=100, overlap_tokens=100)
