"""Agentic editing in natural language.

A command goes through three stages:
  1. Plan: one LLM call maps the command onto a small vocabulary of
     operations (rewrite / shorten / add_citations) targeting sections.
  2. Execute: each operation runs with its own focused prompt. Rewrites
     must preserve every citation token; token-set violations get one
     corrective retry, then the operation is honestly marked failed.
     add_citations searches the real APIs and can only place candidates
     we fetched; new references carry full provenance.
  3. Propose: the result is a diff-based EditProposal. Nothing touches
     the paper until the user approves, and integrity is re-checked at
     apply time (see ops.apply_diffs).
"""
from __future__ import annotations

import uuid

from ..models import EditProposal, Paper, Reference, SectionDiff
from ..parsing.intext import TOKEN_RE, extract_tokens, split_sentences
from ..search import aggregate
from . import llm
from .ops import IntegrityError, check_integrity

ACTIONS = {"rewrite", "shorten", "add_citations"}


def _plan(paper: Paper, command: str) -> list[dict]:
    outline = "\n".join(
        f"- {s.id}: \"{s.title}\" ({len(s.text.split())} words, "
        f"{len(extract_tokens(s.text))} citations)"
        for s in paper.sections
    )
    resp = llm.chat_json(
        system=(
            "You plan edits to a research paper. Map the user's command onto "
            "operations. Allowed actions:\n"
            "- rewrite: rewrite/improve a section per an instruction\n"
            "- shorten: make a section shorter\n"
            "- add_citations: find and insert real citations into a section\n"
            'Return JSON: {"ops": [{"action": "<action>", "section_id": "<id>", '
            '"instruction": "<specific instruction>"}]}\n'
            "Use only section ids from the outline. At most 4 ops."
        ),
        user=f"Paper: {paper.title}\nSections:\n{outline}\n\nCommand: {command}",
    )
    ops = []
    valid_ids = {s.id for s in paper.sections}
    for op in (resp.get("ops") or [])[:4]:
        if op.get("action") in ACTIONS and op.get("section_id") in valid_ids:
            ops.append(op)
    return ops


def _rewrite(paper: Paper, section_id: str, instruction: str,
             warnings: list[str]) -> SectionDiff | None:
    section = paper.section_by_id(section_id)
    assert section is not None
    old_text = section.text
    tokens = extract_tokens(old_text)

    base_system = (
        "You edit one section of a research paper.\n"
        "HARD RULES:\n"
        "1. The text contains citation tokens like [[cite:ref3]] or [[cite:ref1,ref2]]. "
        "Every token that appears in the input MUST appear in your output, character "
        "for character, the same number of times. You may move a token with the "
        "sentence it supports, but never delete, merge, split or invent tokens.\n"
        "2. Do not add any factual claim that is not in the input text.\n"
        "3. Keep the author's voice; edit, don't rewrite into something unrecognizable.\n"
        "Return JSON: {\"text\": \"<edited section text>\", "
        "\"changes\": [\"<one short line per change you made and why>\", ...]}"
    )
    prompt = f"Instruction: {instruction}\n\nSection text:\n{old_text}"
    last_error = ""
    for attempt in range(2):
        user = prompt if not last_error else (
            f"{prompt}\n\nYour previous attempt violated the token rule: {last_error}\n"
            "Try again, keeping every citation token intact.")
        resp = llm.chat_json(system=base_system, user=user, max_tokens=4000)
        new_text = str(resp.get("text", "")).strip()
        if not new_text:
            last_error = "empty output"
            continue
        try:
            check_integrity(old_text, new_text)
        except IntegrityError as exc:
            last_error = str(exc)
            continue
        unknown = set(extract_tokens(new_text)) - set(tokens)
        if unknown:
            last_error = f"introduced unknown citation tokens: {unknown}"
            continue
        notes = [str(c)[:200] for c in (resp.get("changes") or [])[:10] if str(c).strip()]
        return SectionDiff(section_id=section_id, old_text=old_text,
                           new_text=new_text, notes=notes)
    warnings.append(
        f"Operation on '{section.title}' failed after one corrective retry and "
        f"was not applied — the section is unchanged. Specific violation: {last_error}"
    )
    return None


def _add_citations(paper: Paper, section_id: str, instruction: str,
                   warnings: list[str], new_refs: list[Reference],
                   base_text: str | None = None) -> SectionDiff | None:
    section = paper.section_by_id(section_id)
    assert section is not None
    old_text = base_text if base_text is not None else section.text
    plain = TOKEN_RE.sub("[CITATION]", old_text)[:4000]

    resp = llm.chat_json(
        system=('Extract up to 2 academic search queries for finding works to cite. '
                'Return JSON: {"queries": ["<query>", ...]}'),
        user=f"Instruction: {instruction}\nSection '{section.title}':\n{plain}",
    )
    already: set[str] = set()
    for ref in paper.references:
        already |= aggregate.csl_keys(ref.csl)

    candidates: list[dict] = []
    for query in (resp.get("queries") or [])[:2]:
        for result in aggregate.search_all(
                str(query), limit=6, exclude_titles=[paper.title]):
            keys = aggregate.result_keys(result)
            if keys and not (keys & already) and result.get("abstract"):
                already |= keys
                candidates.append(result)
    if not candidates:
        warnings.append(
            f"No suitable uncited works found on Semantic Scholar/OpenAlex for "
            f"'{section.title}'; no citations were added (honest empty result)."
        )
        return None

    sentences = split_sentences(old_text)
    numbered = "\n".join(f"[{i}] {TOKEN_RE.sub('[CITATION]', s)[:300]}"
                         for i, s in enumerate(sentences))
    catalog = "\n".join(
        f"[{i}] {c['title']} ({c.get('year')})\nAbstract: {c['abstract'][:500]}"
        for i, c in enumerate(candidates[:8])
    )
    placed = llm.chat_json(
        system=(
            "You place citations into a paper section. For each candidate work that "
            "genuinely supports a specific sentence, output a placement. Be selective; "
            "only place a citation where the abstract clearly supports the sentence. "
            'Return JSON: {"placements": [{"sentence_index": <int>, '
            '"candidate_index": <int>, "rationale": "<why>"}]}. At most 3; may be empty.'
        ),
        user=f"Sentences:\n{numbered}\n\nCandidates:\n{catalog}",
    )

    next_num = len(paper.references) + len(new_refs) + 1
    placements = []
    for p in (placed.get("placements") or [])[:3]:
        si, ci = p.get("sentence_index"), p.get("candidate_index")
        if isinstance(si, int) and isinstance(ci, int) \
                and 0 <= si < len(sentences) and 0 <= ci < len(candidates[:8]):
            placements.append((si, ci, str(p.get("rationale", ""))))
    if not placements:
        warnings.append(f"The model judged none of the found works a clear match for "
                        f"'{section.title}'; no citations added.")
        return None

    used: dict[int, str] = {}
    notes: list[str] = []
    for si, ci, rationale in sorted(placements, key=lambda x: -x[0]):
        cand = candidates[ci]
        if ci in used:
            ref_id = used[ci]
        else:
            ref_id = f"ref{next_num}"
            next_num += 1
            new_refs.append(Reference(
                id=ref_id,
                csl=aggregate.result_to_csl(cand, ref_id),
                parse_status="parsed",
                provenance=aggregate.result_provenance(cand),
                added_by_edit=True,
            ))
            used[ci] = ref_id
        sentence = sentences[si].rstrip()
        if sentence.endswith((".", "!", "?")):
            sentences[si] = f"{sentence[:-1]} [[cite:{ref_id}]]{sentence[-1]}"
        else:
            sentences[si] = f"{sentence} [[cite:{ref_id}]]"
        year = f" ({cand['year']})" if cand.get("year") else ""
        why = f" — {rationale[:150]}" if rationale else ""
        notes.append(f"Citation added: '{cand['title'][:90]}'{year}{why}")

    new_text = " ".join(sentences)
    check_integrity(old_text, new_text)  # additions only; must never raise
    return SectionDiff(section_id=section_id, old_text=old_text,
                       new_text=new_text, notes=list(reversed(notes)))


def propose_edit(paper: Paper, command: str) -> EditProposal:
    proposal = EditProposal(id=uuid.uuid4().hex[:12], command=command)
    try:
        ops = _plan(paper, command)
    except llm.LLMUnavailable as exc:
        proposal.status = "failed"
        proposal.warnings.append(str(exc))
        return proposal
    if not ops:
        proposal.status = "failed"
        proposal.warnings.append(
            "Could not map the command onto any supported edit operation "
            "(rewrite / shorten / add citations to a section)."
        )
        return proposal

    diffs_by_section: dict[str, SectionDiff] = {}
    for op in ops:
        section_id = op["section_id"]
        base = diffs_by_section.get(section_id)
        section = paper.section_by_id(section_id)
        original = section.text if section else ""
        try:
            if op["action"] in ("rewrite", "shorten"):
                if base is not None and section is not None:
                    section.text = base.new_text
                try:
                    diff = _rewrite(paper, section_id, op["instruction"], proposal.warnings)
                finally:
                    if section is not None:
                        section.text = original
            else:
                diff = _add_citations(
                    paper, section_id, op.get("instruction", command),
                    proposal.warnings, proposal.new_references,
                    base_text=base.new_text if base else None,
                )
        except llm.LLMUnavailable as exc:
            proposal.warnings.append(f"Operation failed: {exc}")
            diff = None
        if diff:
            if base is not None:
                diff.notes = base.notes + diff.notes
                diff.old_text = original
            diffs_by_section[section_id] = diff

    proposal.diffs = list(diffs_by_section.values())
    proposal.summary = f"{len(proposal.diffs)} section(s) changed, " \
                       f"{len(proposal.new_references)} new reference(s)."
    if not proposal.diffs:
        proposal.status = "failed"
    return proposal
