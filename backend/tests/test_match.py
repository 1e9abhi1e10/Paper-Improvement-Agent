from app.models import Reference
from app.search.match import classify_match, corroborate, pick_title_match, title_similarity


def _ref(title="A decomposable attention model", year=2016, raw="", family="Parikh"):
    return Reference(
        id="ref1", parse_status="parsed", raw=raw or f"{family}, A. ({year}). {title}.",
        csl={"id": "ref1", "title": title, "author": [{"family": family, "given": "A"}],
             "issued": {"date-parts": [[year]]}},
    )


def _cand(title, year=2016, family="Parikh"):
    return {"title": title, "year": year, "authors": [{"family": family, "given": "A"}],
            "url": "https://example.com/p", "source": "openalex", "external_id": "x"}


def test_title_similarity_containment_of_truncated_guess():
    score = title_similarity(
        "A decomposable attention model",
        "A Decomposable Attention Model for Natural Language Inference",
    )
    assert score == 1.0


def test_short_title_does_not_wildcard_a_longer_unrelated_one():
    # Two overlapping tokens is not enough for the containment rule.
    score = title_similarity("Attention", "Attention Is All You Need for Image Recognition")
    assert score < 0.75


def test_classify_contradiction_is_low_confidence():
    assert classify_match(0.95, year_ok=False, author_ok=True) == "low-confidence"
    assert classify_match(0.95, year_ok=True, author_ok=False) == "low-confidence"


def test_classify_corroborated_is_verified():
    assert classify_match(0.8, year_ok=True, author_ok=None) == "verified"
    assert classify_match(0.8, year_ok=None, author_ok=True) == "verified"


def test_classify_near_perfect_title_without_signals_is_verified():
    assert classify_match(0.95, None, None) == "verified"
    assert classify_match(0.8, None, None) == "low-confidence"
    assert classify_match(0.5, True, True) == "rejected"


def test_pick_prefers_corroborated_over_higher_scoring_wrong_title():
    ref = _ref()
    wrong = _cand(
        "A decomposable attention model for graphs and a longer unrelated suffix here",
        year=2020, family="Stranger",
    )
    right = _cand("A Decomposable Attention Model for Natural Language Inference", year=2016)
    picked = pick_title_match(ref, [wrong, right])
    assert picked is not None
    assert picked["match_status"] == "verified"
    assert "Natural Language Inference" in picked["title"]


def test_corroborate_year_and_author():
    ref = _ref(year=2016, raw="Parikh, A. (2016). A decomposable attention model.")
    year_ok, author_ok = corroborate(ref, _cand("whatever", year=2016, family="Parikh"))
    assert year_ok is True
    assert author_ok is True
    year_ok, author_ok = corroborate(ref, _cand("whatever", year=2010, family="Other"))
    assert year_ok is False
    assert author_ok is False
