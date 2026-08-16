from app.models import Reference, Provenance
from app.search import aggregate


def _ref(title="Neural turing machines", arxiv="1410.5401"):
    return Reference(
        id="ref8", parse_status="parsed",
        csl={"id": "ref8", "title": title, "number": f"arXiv:{arxiv}",
             "URL": f"https://arxiv.org/abs/{arxiv}"},
    )


def test_enrich_attaches_paper_page_not_search(monkeypatch):
    paper_url = "https://www.semanticscholar.org/paper/abc123"
    monkeypatch.setattr(aggregate, "resolve_reference", lambda ref: {
        "source": "semanticscholar",
        "external_id": "abc123",
        "url": paper_url,
        "title": "Neural Turing Machines",
        "doi": "",
        "abstract": "A neural turing machine.",
    })
    ref = _ref()
    n = aggregate.enrich_references([ref])
    assert n == 1
    assert ref.provenance is not None
    assert ref.provenance.url == paper_url
    assert "/search" not in ref.provenance.url
    assert ref.resolution_status == "verified"


def test_enrich_rejects_search_urls(monkeypatch):
    monkeypatch.setattr(aggregate, "resolve_reference", lambda ref: {
        "source": "semanticscholar",
        "external_id": "x",
        "url": "https://www.semanticscholar.org/search?q=neural+turing",
        "title": "Neural Turing Machines",
        "doi": "",
        "abstract": "",
    })
    ref = _ref()
    assert aggregate.enrich_references([ref]) == 0
    assert ref.provenance is None


def test_s2_result_uses_paper_page_never_search():
    from app.search.semantic_scholar import _to_result

    result = _to_result({
        "paperId": "abc123",
        "title": "Neural Turing Machines",
        "url": "https://www.semanticscholar.org/search?q=neural+turing",
        "authors": [],
        "externalIds": {},
    })
    assert result["url"] == "https://www.semanticscholar.org/paper/abc123"
    assert "/search" not in result["url"]


def test_repair_strips_search_urls_and_enriches(monkeypatch):
    ref = Reference(
        id="ref1", parse_status="parsed",
        csl={
            "id": "ref1",
            "title": "Neural Turing Machines",
            "issued": {"date-parts": [[2014]]},
            "URL": "https://www.semanticscholar.org/search?q=Neural+Turing",
        },
    )
    paper_url = "https://www.semanticscholar.org/paper/abc123"
    monkeypatch.setattr(aggregate, "resolve_reference", lambda r: {
        "source": "semanticscholar",
        "external_id": "abc123",
        "url": paper_url,
        "title": "Neural Turing Machines",
        "doi": "",
        "abstract": "",
    })
    changed = aggregate.repair_references([ref])
    assert changed >= 1
    assert "/search" not in str(ref.csl.get("URL", ""))
    assert ref.provenance is not None
    assert ref.provenance.url == paper_url


def test_csl_render_omits_search_and_hash_urls():
    from app.citations import csl

    ref = Reference(
        id="ref1", parse_status="parsed",
        csl={
            "id": "ref1", "type": "article-journal",
            "title": "Neural Turing Machines",
            "author": [{"family": "Graves", "given": "Alex"}],
            "issued": {"date-parts": [[2014]]},
            "URL": "https://www.semanticscholar.org/search?q=Neural+Turing",
        },
        provenance=Provenance(
            source="semanticscholar",
            external_id="abc123",
            url="https://www.semanticscholar.org/paper/abc123",
        ),
    )
    entry = csl.render([ref], "ieee")["ref1"]["entry"]
    # Bibliography text never shows search or hash paper-page URLs; the
    # exact page is linked from provenance in the UI.
    assert "semanticscholar.org" not in entry
    assert "Neural Turing Machines" in entry


def test_parse_entry_does_not_write_search_url():
    from app.parsing.fields import parse_entry

    ref = parse_entry(
        "Graves, A., Wayne, G., and Danihelka, I. Neural Turing Machines. arXiv:1410.5401, 2014.",
        "ref8",
    )
    url = str(ref.csl.get("URL") or "")
    assert "/search" not in url
    assert "arxiv.org/abs/1410.5401" in url


def test_fix_diacritics_recomposes_split_accents():
    from app.parsing.extract import fix_diacritics

    assert fix_diacritics("C\u00b8 . G\u00a8ulc\u00b8ehre") == "\u00c7. G\u00fcl\u00e7ehre"
    assert fix_diacritics("J. Koutn\u00b4\u0131k") == "J. Koutn\u00edk"
    assert fix_diacritics("R. Schl\u00a8uter") == "R. Schl\u00fcter"
    assert fix_diacritics("plain ASCII text.") == "plain ASCII text."


def test_venue_stripped_from_title_and_extracted():
    from app.parsing.fields import parse_entry

    ref = parse_entry(
        "[12] J. Koutn\u00edk, K. Greff, F. J. Gomez, and J. Schmidhuber. "
        "A clockwork RNN. In ICML, 2014.", "ref12")
    assert ref.csl["title"] == "A clockwork RNN"
    assert ref.csl["container-title"] == "ICML"

    ref = parse_entry(
        "[10] S. Hochreiter and J. Schmidhuber. Long short-term memory. "
        "Neural computation, 9(8):1735- 1780, 1997.", "ref10")
    assert ref.csl["container-title"] == "Neural computation"
    assert ref.csl["volume"] == "9"
    assert ref.csl["page"] == "1735-1780"


def test_numbered_list_item_is_not_a_heading():
    from app.parsing.extract import Line
    from app.parsing.structure import is_heading

    item = Line(
        text="2. Layer-wise (RNN-like): the input and output embeddings "
             "are the same across different",
        size=11.0, bold=True, x0=0, y0=0, page=3, page_width=612)
    assert not is_heading(item, body_size=10.0)
    real = Line(text="2.2 Multiple Layers", size=12.0,
                bold=True, x0=0, y0=0, page=3, page_width=612)
    assert is_heading(real, body_size=10.0)


def test_year_prefixed_bibliography_line_is_not_a_heading():
    from app.parsing.extract import Line
    from app.parsing.structure import is_heading

    wrapped = Line(
        text="2018. URL HTTP://ARXIV.ORG/ABS/1810.04805.",
        size=10.0, bold=True, x0=50, y0=0, page=10, page_width=612)
    assert not is_heading(wrapped, body_size=10.0)
