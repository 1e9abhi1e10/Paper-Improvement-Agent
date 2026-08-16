"""Tests for grounded Q&A: sentence index + source validation (LLM-free)."""
from app.agent.qa import build_sentence_index, validate_sources
from app.models import Paper, Section


def paper():
    return Paper(
        id="p", title="T",
        abstract="We propose a novel attention mechanism for translation tasks.",
        sections=[Section(
            id="sec1", title="1 Introduction",
            text="Transformers changed natural language processing [[cite:ref1]]. "
                 "Our model trains in 3.5 days on eight GPUs, a small fraction "
                 "of previous costs. Short.",
        )],
    )


def test_sentence_index_ids_and_token_stripping():
    index = build_sentence_index(paper())
    assert "abstract#0" in index
    assert index["sec1#0"][2] == "Transformers changed natural language processing."
    assert "[[cite:" not in index["sec1#0"][2]
    # Sentences under 20 chars ("Short.") are not indexable evidence.
    assert all("Short." not in v[2] for v in index.values())


def test_valid_evidence_maps_to_verbatim_quote():
    index = build_sentence_index(paper())
    sources, ok = validate_sources(index, ["sec1#1", "(abstract#0)"])
    assert ok
    assert sources[0]["section_title"] == "1 Introduction"
    assert sources[0]["quote"].startswith("Our model trains in 3.5 days")
    assert sources[1]["section_id"] == "abstract"


def test_unknown_ids_dropped_and_flagged():
    index = build_sentence_index(paper())
    sources, ok = validate_sources(index, ["sec1#99", "sec42#0"])
    assert not ok and sources == []


def test_duplicate_ids_deduped():
    index = build_sentence_index(paper())
    sources, ok = validate_sources(index, ["sec1#0", "sec1#0"])
    assert ok is False or len(sources) == 1  # dedup keeps one
    assert len(sources) == 1


def test_fabricated_quote_impossible_by_construction():
    # The model cannot introduce text: quotes come from the index only.
    index = build_sentence_index(paper())
    sources, _ = validate_sources(index, ["sec1#1"])
    all_sentences = {v[2] for v in index.values()}
    assert sources[0]["quote"] in all_sentences
