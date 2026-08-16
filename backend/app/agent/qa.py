"""Grounded Q&A over the parsed paper.

Same grounding principle as the rest of the agent: the model never
*produces* evidence, it *points* at it. Every sentence of the paper is
given a stable id (sec3#7); the model answers and cites sentence ids;
we look the sentences up ourselves, so a shown quote is verbatim paper
text by construction. Ids that don't exist are dropped and the answer
is flagged. If the paper doesn't contain the answer, the model must say
so -- "the paper doesn't say" is a first-class answer.
"""
from __future__ import annotations

import re

from ..models import Paper
from ..parsing.intext import TOKEN_RE, split_sentences
from . import llm

MAX_HISTORY = 6
MAX_SECTION_CHARS = 2600

SentenceIndex = dict[str, tuple[str, str, str]]  # id -> (section_id, title, sentence)


def build_sentence_index(paper: Paper) -> SentenceIndex:
    index: SentenceIndex = {}

    def add(section_id: str, title: str, text: str) -> None:
        plain = TOKEN_RE.sub("", text)[:MAX_SECTION_CHARS]
        for i, sentence in enumerate(split_sentences(plain)):
            sentence = " ".join(sentence.split())
            sentence = re.sub(r"\s+([.,;:!?])", r"\1", sentence)
            if len(sentence) >= 20:
                index[f"{section_id}#{i}"] = (section_id, title, sentence)

    if paper.abstract:
        add("abstract", "Abstract", paper.abstract)
    for section in paper.sections:
        add(section.id, section.title, section.text)
    return index


def _context(paper: Paper, index: SentenceIndex) -> str:
    lines = [f"TITLE: {paper.title}"]
    current = None
    for sid, (_section_id, title, sentence) in index.items():
        if title != current:
            lines.append(f"\n== {title} ==")
            current = title
        lines.append(f"({sid}) {sentence}")
    return "\n".join(lines)


def validate_sources(index: SentenceIndex, raw_ids: list) -> tuple[list[dict], bool]:
    """Map cited sentence ids to verbatim quotes. Unknown ids are dropped
    and reported via the all_valid flag."""
    sources: list[dict] = []
    seen: set[str] = set()
    all_valid = True
    for raw in raw_ids[:8]:
        sid = str(raw).strip("() ")
        if sid in index and sid not in seen:
            seen.add(sid)
            section_id, title, sentence = index[sid]
            sources.append({"section_id": section_id, "section_title": title,
                            "quote": sentence[:400]})
        else:
            all_valid = False
    return sources, all_valid


def answer_question(paper: Paper, question: str,
                    history: list[dict] | None = None) -> dict:
    index = build_sentence_index(paper)

    def ref_line(r) -> str:
        title = (r.csl.get("title") or r.raw)[:100]
        authors = r.csl.get("author") or []
        first = authors[0].get("family", "") if authors else ""
        issued = r.csl.get("issued", {}).get("date-parts", [[None]])
        year = issued[0][0] if issued and issued[0] else None
        meta = ", ".join(str(x) for x in
                         ([first + (" et al." if len(authors) > 1 else "")] if first else [])
                         + ([year] if year else []))
        return f"{r.id}: {title}" + (f" ({meta})" if meta else "")

    ref_index = "\n".join(ref_line(r) for r in paper.references)
    convo = ""
    for turn in (history or [])[-MAX_HISTORY:]:
        role = "Q" if turn.get("role") == "user" else "A"
        convo += f"{role}: {str(turn.get('content', ''))[:500]}\n"

    resp = llm.chat_json(
        system=(
            "You answer questions about ONE research paper, using ONLY the "
            "material provided: the paper text (every sentence has an id like "
            "(sec3#7)) and the paper's REFERENCE LIST (entries have ids like "
            "ref8). Rules:\n"
            "1. If neither the text nor the reference list contains the answer, "
            "set answered=false and write one plain sentence in 'answer' saying "
            "the paper doesn't cover it. Never use outside knowledge as if it "
            "were in the paper.\n"
            "2. For claims from the paper text, put the ids of the exact "
            "sentences your answer rests on in 'evidence'. Cite only sentences "
            "that genuinely support it.\n"
            "3. Questions about the references themselves (e.g. \"what is "
            "reference 8?\", \"list the references\", \"which works by X are "
            "cited?\") should be answered from the REFERENCE LIST; put the refN "
            "ids you used in cited_refs. Also use cited_refs whenever your "
            "evidence sentences carry citations. If asked to list the "
            "references, actually enumerate them from the REFERENCE LIST "
            "(id, title, author, year) instead of deflecting.\n"
            "Return JSON: {\"answer\": \"<concise answer>\", \"answered\": true|false, "
            "\"evidence\": [\"sec3#7\", ...], \"cited_refs\": [\"refN\", ...]}"
        ),
        user=f"PAPER:\n{_context(paper, index)}\n\nREFERENCE LIST:\n{ref_index}\n\n"
             f"{('CONVERSATION SO FAR:' + chr(10) + convo + chr(10)) if convo else ''}"
             f"QUESTION: {question}",
        max_tokens=1800,
    )

    sources, all_valid = validate_sources(index, resp.get("evidence") or [])
    known_refs = {r.id for r in paper.references}
    cited_refs = [r for r in (resp.get("cited_refs") or [])[:12]
                  if isinstance(r, str) and r in known_refs]
    # Deterministic top-up: explicit "reference 8" / "ref8" / "citation 8"
    # mentions in the question or answer count as involved references.
    answer_text = str(resp.get("answer", ""))
    for m in re.finditer(r"\b(?:ref(?:erence)?|citation)\s*#?\s*(\d{1,3})\b",
                         question + " " + answer_text, re.I):
        rid = f"ref{m.group(1)}"
        if rid in known_refs and rid not in cited_refs:
            cited_refs.append(rid)
    # ...and reference titles quoted in the answer (e.g. list-style answers).
    answer_norm = re.sub(r"[^a-z0-9]+", " ", answer_text.lower())
    for ref in paper.references:
        title = re.sub(r"[^a-z0-9]+", " ", (ref.csl.get("title") or "").lower()).strip()
        if len(title) > 15 and title in answer_norm and ref.id not in cited_refs:
            cited_refs.append(ref.id)
    cited_refs = cited_refs[:40]
    answered = bool(resp.get("answered", True))
    answer = str(resp.get("answer", "")).strip()[:3000]
    if not answered and (len(answer) < 15 or "answered" in answer.lower()):
        answer = "The paper does not contain the information needed to answer this question."

    warning = ""
    if answered and not sources and not cited_refs:
        warning = ("The model gave an answer but pointed at no verifiable "
                   "sentences or references in the paper; treat it with caution.")
    elif not all_valid:
        warning = "Some claimed evidence ids were invalid and were removed."

    return {
        "answer": answer,
        "answered": answered,
        "sources": sources,
        "cited_refs": cited_refs,
        "warning": warning,
    }
