from app.parsing.extract import Line, join_hyphenated
from app.parsing.structure import parse_structure


def line(text, size=10.0, bold=False, page=0, x0=72.0):
    return Line(text=text, size=size, bold=bold, x0=x0, y0=0.0,
                page=page, page_width=612.0)


def test_join_hyphenated():
    assert join_hyphenated(["state-of-the-", "art models"]) == "state-of-the-art models"
    assert join_hyphenated(["trans-", "formers are great"]) == "transformers are great"
    assert join_hyphenated(["URL http://arxiv.org/abs/1611.", "06194."]) == \
        "URL http://arxiv.org/abs/1611.06194."


def test_full_structure():
    lines = [
        line("A Grand Unified Theory of Testing", size=16.0, bold=True),
        line("Jane Doe, John Smith", size=10.0),
        line("Abstract", size=11.0, bold=True),
        line("We present a grand theory. It unifies everything.", size=10.0),
        line("1 Introduction", size=12.0, bold=True),
        line("Testing matters a lot. Prior work exists [1].", size=10.0),
        line("2 Methods", size=12.0, bold=True),
        line("We do things carefully.", size=10.0),
        line("2.1 Setup", size=11.0, bold=True),
        line("The setup is simple.", size=10.0),
    ]
    # Pad with body lines so the body font size is 10.
    lines += [line(f"Filler sentence number {i}.", size=10.0, page=1) for i in range(20)]

    title, abstract, sections, _ = parse_structure(lines)
    assert title == "A Grand Unified Theory of Testing"
    assert abstract.startswith("We present")
    titles = [s.title for s in sections]
    assert "1 Introduction" in titles
    assert "2 Methods" in titles
    sub = next(s for s in sections if s.title == "2.1 Setup")
    assert sub.level == 2
