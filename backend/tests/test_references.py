from app.parsing.extract import Line
from app.parsing.fields import parse_entry
from app.parsing.references import find_reference_lines, segment_entries


def make_lines(specs):
    """specs: list of (text, x0)."""
    return [Line(text=t, size=9.0, bold=False, x0=x,
                 y0=float(i * 12), page=0, page_width=612.0)
            for i, (t, x) in enumerate(specs)]


def test_midline_bracket_markers_are_split():
    """Two-column extraction often concatenates [n] and [n+1] on one line."""
    lines = make_lines([
        ("[1] C. G. Atkeson and S. Schaal. Memory-based neural networks. 1995. "
         "[2] D. Bahdanau, K. Cho, and Y. Bengio. Neural machine translation. 2015.", 50),
        ("[3] Y. Bengio et al. A neural probabilistic language model. 2003.", 50),
        ("[4] J. Chung et al. Empirical evaluation of GRUs. 2014.", 50),
    ])
    entries, scheme, remainder, _ = segment_entries(lines)
    assert scheme == "bracket"
    assert remainder == ""
    assert len(entries) == 4
    assert entries[0].startswith("[1]")
    assert entries[1].startswith("[2]")
    assert "Bahdanau" in entries[1]
    assert "Atkeson" not in entries[1]


def test_table_rows_after_references_are_dropped():
    heading = Line(text="References", size=12.0, bold=True,
                   x0=50, y0=0, page=0, page_width=612.0)
    refs = make_lines([
        ("[1] C. G. Atkeson. Memory-based neural networks. 1995.", 50),
        ("[2] D. Bahdanau. Neural machine translation. 2015.", 50),
        ("[3] Y. Bengio. A neural probabilistic language model. 2003.", 50),
    ])
    junk = make_lines([
        ("PE LS 1 hop 2 hops 3 hops PE", 50),
        ("PE LS Supervised MemNN PE LS LW", 50),
        ("Key: BoW = bag-of-words representation; PE = position encoding", 50),
    ])
    found, _ = find_reference_lines([heading] + refs + junk, body_size=10.0)
    joined = " ".join(l.text for l in found)
    assert "Atkeson" in joined
    assert "PE LS" not in joined
    entries, scheme, _, _ = segment_entries(found)
    assert scheme == "bracket"
    assert len(entries) == 3


def test_sequence_gap_is_surfaced_not_dropped():
    lines = make_lines([
        ("[1] A. Vaswani et al., \u201cAttention is all you need,\u201d 2017.", 50),
        ("[2] J. Devlin et al., \u201cBERT,\u201d 2019.", 50),
        ("[4] T. Brown et al., \u201cGPT-3,\u201d 2020.", 50),
    ])
    entries, scheme, remainder, diags = segment_entries(lines)
    assert scheme == "bracket"
    assert remainder == ""
    assert len(entries) == 3
    assert any("sequence gap" in d.message.lower() for d in diags)


def test_citation_density_fallback_when_heading_missing():
    body = make_lines([(f"Some body sentence number {i} continues here.", 50) for i in range(12)])
    refs = make_lines([
        ("[1] A. Vaswani et al. Attention is all you need. 2017.", 50),
        ("[2] J. Devlin et al. BERT. 2019.", 50),
        ("[3] T. Brown et al. Language models are few-shot learners. 2020.", 50),
        ("[4] A. Radford et al. Language models are unsupervised multitask learners. 2019.", 50),
        ("[5] J. Kaplan et al. Scaling laws for neural language models. 2020.", 50),
    ])
    found, diags = find_reference_lines(body + refs, body_size=10.0)
    assert any("citation-density" in d.message.lower() for d in diags)
    assert len(found) >= 5
    assert found[0].text.startswith("[1]")


def test_segment_bracket_numbered():
    lines = make_lines([
        ("[1] A. Vaswani, N. Shazeer, et al., \u201cAttention is all you need,\u201d", 50),
        ("in NeurIPS, 2017.", 60),
        ("[2] J. Devlin, M. Chang, \u201cBERT: Pre-training of deep bidirectional", 50),
        ("transformers,\u201d in NAACL, 2019.", 60),
        ("[3] T. Brown et al., \u201cLanguage models are few-shot learners,\u201d 2020.", 50),
    ])
    entries, scheme, remainder, _ = segment_entries(lines)
    assert scheme == "bracket"
    assert len(entries) == 3
    assert remainder == ""
    assert "Attention is all you need" in entries[0]
    assert "NAACL" in entries[1]


def test_segment_author_year_hanging_indent():
    lines = make_lines([
        ("Devlin, J., Chang, M. (2019). BERT: Pre-training of deep", 50),
        ("bidirectional transformers. NAACL.", 62),
        ("Vaswani, A., Shazeer, N. (2017). Attention is all you need.", 50),
        ("Advances in Neural Information Processing Systems.", 62),
        ("Brown, T. (2020). Language models are few-shot learners. NeurIPS.", 50),
    ])
    entries, scheme, remainder, _ = segment_entries(lines)
    assert scheme == "author-year-indent"
    assert len(entries) == 3
    assert entries[0].startswith("Devlin")
    assert "Processing Systems" in entries[1]


def test_unsegmentable_block_surfaced_not_dropped():
    # One continuous flat blob with no markers or indents.
    lines = make_lines([(f"some flowing referencey text part {i}", 50) for i in range(8)])
    entries, _, remainder, diags = segment_entries(lines)
    assert entries == []
    assert "part 0" in remainder and "part 7" in remainder
    assert any("segment" in d.message.lower() for d in diags)


def test_parse_entry_ieee_access_doubled_quotes():
    ref = parse_entry(
        "[4] A. Vaswani et al., \u2018\u2018Attention is all you need,\u2019\u2019 in NeurIPS, 2017.",
        "ref4")
    assert ref.csl["title"] == "Attention is all you need"


def test_parse_entry_org_author_kept_as_literal():
    ref = parse_entry(
        "AI@Meta. (2024). The Llama 3 herd of models. arXiv:2407.21783.",
        "ref1")
    assert any(a.get("literal") == "AI@Meta" for a in ref.csl.get("author", []))


def test_parse_entry_ieee_quoted_title():
    ref = parse_entry(
        "[4] A. Vaswani et al., \u201cAttention is all you need,\u201d in NeurIPS, 2017, "
        "doi: 10.5555/3295222.", "ref4")
    assert ref.parse_status == "parsed"
    assert ref.csl["title"] == "Attention is all you need"
    assert ref.csl["issued"]["date-parts"] == [[2017]]
    assert ref.csl["DOI"].startswith("10.5555/")
    assert ref.csl["id"] == "ref4"


def test_parse_entry_apa():
    ref = parse_entry(
        "Devlin, J., Chang, M. W. (2019). BERT: Pre-training of deep bidirectional "
        "transformers for language understanding. NAACL.", "ref1")
    assert ref.parse_status == "parsed"
    assert ref.csl["title"].startswith("BERT")
    assert ref.csl["issued"]["date-parts"] == [[2019]]
    assert any(a["family"] == "Devlin" for a in ref.csl["author"])


def test_parse_entry_garbage_is_failed_but_kept():
    ref = parse_entry("!!! ??? ---", "ref9")
    assert ref.parse_status == "failed"
    assert ref.raw == "!!! ??? ---"


def test_trailing_figure_caption_stripped_from_last_entry():
    lines = make_lines([
        ("[1] A. Vaswani et al., \u201cAttention is all you need,\u201d 2017.", 50),
        ("[2] J. Devlin et al., \u201cBERT,\u201d 2019.", 50),
        ("[3] T. Brown et al., \u201cGPT-3,\u201d 2020. Attention Visualizations", 50),
        ("Figure 3: An example of the attention mechanism.", 50),
    ])
    entries, scheme, _, _ = segment_entries(lines)
    assert scheme == "bracket"
    assert len(entries) == 3
    assert "Visualizations" not in entries[-1]
    assert "Figure 3" not in entries[-1]
    assert "GPT-3" in entries[-1]


def test_appendices_heading_ends_reference_list():
    heading = Line(text="References", size=12.0, bold=True,
                   x0=50, y0=0, page=0, page_width=612.0)
    refs = make_lines([
        ("Martín Abadi et al. Tensorflow. arXiv preprint arXiv:1603.04467, 2016.", 50),
        ("Dzmitry Bahdanau et al. Neural machine translation. arXiv:1409.0473, 2014.", 50),
        ("Yoshua Bengio et al. Conditional computation. arXiv:1511.06297, 2015.", 50),
    ])
    appendix = Line(text="APPENDICES", size=9.6, bold=False,
                    x0=50, y0=400, page=1, page_width=612.0)
    junk = Line(text="As discussed in section 4, for load-balancing purposes.", size=10.0,
                bold=False, x0=50, y0=420, page=1, page_width=612.0)
    found, _ = find_reference_lines([heading] + refs + [appendix, junk], body_size=10.0)
    assert all("load-balancing" not in l.text for l in found)
    assert any("APPENDICES" == l.text for l in found) is False
    assert len(found) == 3


def test_parse_entry_corr_abs_becomes_arxiv_url():
    ref = parse_entry(
        "[2] Dzmitry Bahdanau, Kyunghyun Cho, and Yoshua Bengio. Neural machine "
        "translation by jointly learning to align and translate. CoRR, abs/1409.0473, 2014.",
        "ref2")
    assert ref.parse_status == "parsed"
    assert ref.csl["URL"] == "https://arxiv.org/abs/1409.0473"
    assert ref.csl["number"] == "arXiv:1409.0473"


def test_parse_entry_wrapped_arxiv_url():
    ref = parse_entry(
        "Rahaf Aljundi et al. Expert gate: Lifelong learning with a network of experts. "
        "CoRR, abs/1611.06194, 2016. URL http://arxiv.org/abs/1611. 06194.",
        "ref2")
    assert ref.csl["URL"] == "https://arxiv.org/abs/1611.06194"


def test_parse_entry_acl_authors_year_title():
    ref = parse_entry(
        "Kevin Clark, Minh-Thang Luong, Christopher D Manning, and Quoc Le. 2018. "
        "Semi-supervised sequence modeling with cross-view training. In Proceedings "
        "of the 2018 Conference on Empirical Methods in Natural Language Processing, "
        "pages 1914– 1925.",
        "ref12")
    assert ref.parse_status == "parsed"
    assert ref.csl["title"].startswith("Semi-supervised sequence modeling")
    assert ref.csl["issued"]["date-parts"] == [[2018]]  # not the page number 1925


def test_parse_entry_does_not_treat_colon_title_as_names():
    ref = parse_entry(
        "[24] K. Xu et al. Show, Attend and Tell: Neural Image Caption Generation "
        "with Visual Attention. ArXiv preprint: 1502.03044, 2015.",
        "ref24")
    assert "Show, Attend and Tell" in ref.csl["title"]
    assert ref.csl["URL"] == "https://arxiv.org/abs/1502.03044"


def test_parse_entry_title_starting_with_a():
    ref = parse_entry(
        "[22] Zhouhan Lin, Minwei Feng, and Yoshua Bengio. A structured self-attentive "
        "sentence embedding. arXiv preprint arXiv:1703.03130, 2017.",
        "ref22")
    assert ref.csl["title"].startswith("A structured self-attentive")
    assert ref.csl["URL"] == "https://arxiv.org/abs/1703.03130"


def test_parse_entry_imagenet_not_fei_fei_title():
    ref = parse_entry(
        "J. Deng, W. Dong, R. Socher, L.-J. Li, K. Li, and L. Fei- Fei. 2009. "
        "ImageNet: A Large-Scale Hierarchical Image Database. In CVPR09.",
        "ref16")
    assert ref.csl["title"].startswith("ImageNet")
    assert ref.csl["issued"]["date-parts"] == [[2009]]
