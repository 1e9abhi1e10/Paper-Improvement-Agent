from app.parsing.extract import Line, detect_layout, infer_year, page_count


def line(text="body", page=0, x0=72.0, page_width=612.0):
    return Line(text=text, size=10.0, bold=False, x0=x0, y0=0.0,
                page=page, page_width=page_width)


def test_page_count():
    assert page_count([]) == 0
    assert page_count([line(page=0), line(page=10)]) == 11


def test_infer_year_from_arxiv_filename():
    assert infer_year("1503.08895v5.pdf", []) == "2015"
    assert infer_year("1706.03762.pdf", []) == "2017"
    assert infer_year("paper.pdf", []) == ""


def test_infer_year_from_venue_line():
    lines = [line("Published as a conference paper at ICLR 2017")]
    assert infer_year("paper.pdf", lines) == "2017"


def test_single_column_layout():
    lines = [line(f"row {i}", page=0, x0=72.0) for i in range(20)]
    assert detect_layout(lines) == "Single column"


def test_two_column_layout():
    lines = []
    for page in (1, 2):
        lines += [line(f"L{i}", page=page, x0=54.0) for i in range(12)]
        lines += [line(f"R{i}", page=page, x0=318.0) for i in range(12)]
    assert detect_layout(lines) == "Two-column"


def test_mixed_layout():
    lines = []
    for page in (1, 2):
        lines += [line(f"wide {i}", page=page, x0=72.0) for i in range(16)]
    for page in (3, 4):
        lines += [line(f"L{i}", page=page, x0=54.0) for i in range(12)]
        lines += [line(f"R{i}", page=page, x0=318.0) for i in range(12)]
    assert detect_layout(lines) == "Mixed layout"
