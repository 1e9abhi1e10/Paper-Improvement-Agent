from app.models import Reference
from app.parsing.intext import _expand_numeric, extract_tokens, split_sentences, tokenize_section
from app.parsing.style import detect_style


def refs(n):
    return [Reference(id=f"ref{i+1}", raw=f"entry {i+1}",
                      csl={"id": f"ref{i+1}", "title": f"T{i+1}",
                           "author": [{"family": f"Fam{i+1}", "given": "A"}],
                           "issued": {"date-parts": [[2000 + i]]}},
                      parse_status="parsed") for i in range(n)]


def test_expand_numeric_ranges():
    assert _expand_numeric("1, 3-5") == [1, 3, 4, 5]
    assert _expand_numeric("2\u20134") == [2, 3, 4]


def test_tokenize_numeric():
    text = "Transformers changed NLP [1]. Later works [2, 3] built on this."
    out, cits = tokenize_section(text, "sec1", refs(3), [0])
    assert "[[cite:ref1]]" in out
    assert "[[cite:ref2,ref3]]" in out
    assert all(c.resolved for c in cits)
    assert extract_tokens(out) == ["ref1", "ref2", "ref3"]


def test_numeric_out_of_range_left_verbatim():
    text = "A bold claim [7]."
    out, cits = tokenize_section(text, "sec1", refs(3), [0])
    assert "[7]" in out and "[[cite:" not in out
    assert len(cits) == 1 and not cits[0].resolved


def test_tokenize_author_year():
    r = refs(2)
    r[0].csl["author"] = [{"family": "Devlin", "given": "J"}]
    r[0].csl["issued"] = {"date-parts": [[2019]]}
    r[1].csl["author"] = [{"family": "Vaswani", "given": "A"}]
    r[1].csl["issued"] = {"date-parts": [[2017]]}
    text = "BERT (Devlin et al., 2019) builds on attention (Vaswani et al., 2017)."
    out, cits = tokenize_section(text, "sec1", r, [0])
    assert "[[cite:ref1]]" in out and "[[cite:ref2]]" in out
    assert all(c.resolved for c in cits)


def test_tokenize_narrative_author_year():
    r = refs(1)
    r[0].csl["author"] = [{"family": "Devlin", "given": "J"}]
    r[0].csl["issued"] = {"date-parts": [[2019]]}
    text = "Devlin et al. (2019) showed that masked language modelling helps."
    out, cits = tokenize_section(text, "sec1", r, [0])
    assert "[[cite:ref1]]" in out
    assert all(c.resolved for c in cits)
    assert "Devlin et al. (2019)" not in out


def test_ambiguous_author_year_is_not_guessed():
    r = refs(2)
    r[0].csl["author"] = [{"family": "Smith", "given": "A"}]
    r[0].csl["issued"] = {"date-parts": [[2020]]}
    r[0].raw = "Smith, A. (2020). First paper."
    r[1].csl["author"] = [{"family": "Smith", "given": "B"}]
    r[1].csl["issued"] = {"date-parts": [[2020]]}
    r[1].raw = "Smith, B. (2020). Second paper."
    text = "A contested claim (Smith, 2020) sits here."
    out, cits = tokenize_section(text, "sec1", r, [0])
    assert "(Smith, 2020)" in out
    assert "[[cite:" not in out
    assert cits == []


def test_letter_suffix_disambiguates_same_author_year():
    r = refs(2)
    r[0].csl["author"] = [{"family": "Smith", "given": "A"}]
    r[0].csl["issued"] = {"date-parts": [[2020]]}
    r[0].raw = "Smith, A. (2020a). First paper."
    r[1].csl["author"] = [{"family": "Smith", "given": "A"}]
    r[1].csl["issued"] = {"date-parts": [[2020]]}
    r[1].raw = "Smith, A. (2020b). Second paper."
    text = "The follow-up (Smith, 2020b) extends the original."
    out, cits = tokenize_section(text, "sec1", r, [0])
    assert "[[cite:ref2]]" in out
    assert all(c.resolved for c in cits)


def test_org_author_matches_full_token_not_substring():
    r = refs(1)
    r[0].csl["author"] = [{"literal": "AI@Meta"}]
    r[0].csl["issued"] = {"date-parts": [[2024]]}
    r[0].raw = "AI@Meta. (2024). Llama 3."
    text = "The release (AI@Meta, 2024) is documented."
    out, cits = tokenize_section(text, "sec1", r, [0])
    assert "[[cite:ref1]]" in out


def test_tokenize_author_year_multipart_last_name():
    r = refs(1)
    r[0].csl["author"] = [{"family": "Sang", "given": "Erik F Tjong Kim"}]
    r[0].csl["issued"] = {"date-parts": [[2003]]}
    text = "NER (Tjong Kim Sang and De Meulder, 2003) is a standard task."
    out, cits = tokenize_section(text, "sec1", r, [0])
    assert "[[cite:ref1]]" in out
    assert all(c.resolved for c in cits)


def test_parenthetical_non_citation_untouched():
    text = "We discuss this later (see Section 4)."
    out, cits = tokenize_section(text, "sec1", refs(2), [0])
    assert out == text
    assert cits == []


def test_style_detection():
    r = refs(2)
    _, cits_numeric = tokenize_section("Known result [1].", "s", r, [0])
    assert detect_style(cits_numeric) == ("ieee", True)
    r[0].csl["author"] = [{"family": "Devlin", "given": "J"}]
    r[0].csl["issued"] = {"date-parts": [[2019]]}
    _, cits_ay = tokenize_section("Known (Devlin, 2019).", "s", r, [0])
    assert detect_style(cits_ay) == ("apa", True)
    assert detect_style([]) == ("ieee", False)


def test_split_sentences():
    assert split_sentences("One claim. Another claim! A question?") == [
        "One claim.", "Another claim!", "A question?",
    ]
