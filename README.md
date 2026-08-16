# Paper Improvement Agent

Upload a research paper PDF, see exactly how it was parsed, get a peer review
grounded in real Semantic Scholar and OpenAlex records, improve the paper with
natural-language commands (with diff approval), and export the revised paper as
LaTeX — with every citation kept intact.

The full architecture — parse pipeline, resolution, agent loop, and
citation-integrity invariant — is in
[docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md). The whiteboard diagram
is [docs/architecture.excalidraw](docs/architecture.excalidraw)
(open at [excalidraw.com](https://excalidraw.com) or with the Excalidraw
extension).

## Demo

<video src="docs/demo.mp4" controls width="100%"></video>

[Watch the demo](docs/demo.mp4) — upload a paper, parse citations, switch
IEEE/APA, ask the paper, edit with diff approval, run a grounded review, and
export LaTeX.

## How to run

Backend (Python 3.11+):

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # put your OpenAI key in .env
.venv/bin/uvicorn app.main:app --port 8000
```

Frontend (Node 18+):

```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173 (proxies /api to :8000)
```

Tests:

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

Keys: `OPENAI_API_KEY` is required for peer review and editing (parsing and
export work without it). OpenAlex needs no key; `SEMANTIC_SCHOLAR_API_KEY` is
optional and only raises rate limits.

Try it with any real paper — arXiv PDFs work well (tested with
[Attention Is All You Need](https://arxiv.org/abs/1706.03762), numeric/IEEE
citations, and [BERT](https://arxiv.org/abs/1810.04805), author-year/APA
citations).

---

## System design 1: citation parsing

See [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) for the complete write-up
(pipeline stages, SBMV resolution, token invariant, agent loop, API map).

**Goal:** PDF → structured paper with normalized CSL-JSON citations, where
every failure is surfaced, never hidden.

### The pipeline

Each step is its own module in `backend/app/parsing/`, and each step emits
`Diagnostic` records that the UI shows in the Parse tab.

```
PDF bytes
  │  1. extract.py   PyMuPDF → layout-aware lines (text, font size, bold,
  │                  x/y position, page). Drops rotated arXiv banners and
  │                  bottom-of-page page numbers; keeps everything else.
  ▼
  │  2. structure.py title = largest font near the top of page 1;
  │                  headings = numbering pattern + canonical names +
  │                  typography (size/bold); re-joins headings that PDF
  │                  extraction splits ("3" + "Model Architecture");
  │                  sub-body-size lines (footnotes, captions) are excluded
  │                  from section prose; hyphenated line wraps repaired.
  ▼
  │  3. references.py locate the last References/Bibliography/Works Cited
  │                  heading (ToC mentions are ignored). If none: citation-
  │                  density scan of the final third. Then segment: [n] /
  │                  "n." / hanging-indent per page/column. Sequence gaps
  │                  and unsegmentable remainder are surfaced, never dropped.
  ▼
  │  4. fields.py    each entry → CSL-JSON: DOI/arXiv/URL/year by pattern;
  │                  title by quoted-title (IEEE, including IEEE Access
  │                  ‘‘doubled quotes’’), (year). Title. (APA), or sentence-
  │                  folding fallback; org authors kept as CSL `literal`.
  │                  Then resolve against OpenAlex (batch DOI OR-filter) and
  │                  Semantic Scholar (POST /paper/batch). Title leftovers
  │                  use Crossref SBMV corroboration: year ±1 and first-
  │                  author surname in the raw entry — similarity alone
  │                  never earns "verified". Status: verified /
  │                  low-confidence / unverified.
  ▼
  │  5. intext.py    numeric markers ("[1, 4-6]") mapped by position;
  │                  parenthetical ("(Smith et al., 2020)") and narrative
  │                  ("Smith et al. (2020)") author-year matched by family
  │                  + year. Ambiguous matches (two Smith 2020s) are
  │                  reported, never guessed. Letter suffixes (2020a)
  │                  disambiguate. Tokens: "[[cite:ref3,ref12]]".
  ▼
  │  6. style.py     numeric-dominant → IEEE, author-year-dominant → APA
  ▼                  (CSL style id; user can override in the UI). A
  │                  consistency lint flags stray minority-style markers
  ▼                  (one numbered citation in an author-year paper).
Paper { title, abstract, sections[], references[] (CSL-JSON),
        intext[], style, diagnostics[] }
```

### The intermediate representation

Two decisions carry the whole design:

1. **CSL-JSON is the single canonical citation model.** Whether a reference
   was parsed from the PDF or fetched from Semantic Scholar/OpenAlex, it is
   stored as a CSL-JSON item (`Reference.csl`) plus provenance. All
   *formatting* — inline labels, bibliography entries, both styles — is done
   by citeproc-py with the official `apa.csl`/`ieee.csl` files
   (`app/citations/csl.py`). There are no hand-written citation templates
   anywhere.

2. **Section text is tokenized.** Every recognized in-text marker is replaced
   with `[[cite:refId,...]]`. Tokens make citations *mechanically checkable*:
   an edit is valid only if the multiset of tokens after ⊇ before. Rendering
   for the UI and the LaTeX export substitutes tokens back through CSL.

### Failure handling

- Reference entries that can't be parsed keep `parse_status="failed"` with
  their raw text; they render as raw text and are flagged in the UI and in the
  exported LaTeX.
- In-text markers that don't resolve (e.g. `[99]` with 40 refs, or an
  author-year with no matching entry) are left verbatim in the text and listed
  as unresolved. Ambiguous author-year hits are treated the same way — never
  silently linked to the first match.
- Parsed entries that the APIs cannot corroborate stay `unverified` (or
  `low-confidence` if the title matched but year/author did not). Retry
  verification re-resolves only those entries; verified ones are never
  re-touched.
- Every stage's oddities (no abstract found, unsegmentable reference block,
  sequence gaps, uncited references, heading inferred by density scan) land
  in `paper.diagnostics`, shown in the Parse tab.

## System design 2: the agent

There is no single giant prompt. Peer review and editing are decomposed into
small, single-purpose LLM calls (each returning validated JSON) around a core
of deterministic, mechanically-checked operations.

### The grounding rule

The LLM is never the source of a citation. In every prompt where the model
"chooses" a work, it can only pick **by index from a candidate list we
fetched** from Semantic Scholar/OpenAlex; picks outside the list are discarded.
New references carry `Provenance {source, external_id, url, abstract}` and
`ops.apply_diffs` refuses any new reference without API provenance. Fabricating
a source is therefore structurally impossible, not just discouraged.

### Peer review (`agent/review.py`)

*Missing work* — per major section:
1. LLM extracts the section's key claims plus short search queries (JSON).
2. Both APIs are searched (`search/aggregate.py`: merged, deduped by
   DOI/normalized title, already-cited works filtered out).
3. LLM judges the candidates' abstracts against the claim and picks at most
   two, with rationale and confidence — by index only.
4. Empty searches become honest "nothing found" findings.

*Claim ↔ citation match* — per in-text citation (capped per run):
1. The claim is the sentence containing the citation token.
2. The cited work's abstract is fetched by DOI, else by title match, from
   either API (`aggregate.resolve_reference`).
3. If no abstract exists → finding kind `unverifiable`, stated plainly.
4. Else the LLM judges supports / partially_supports / does_not_support /
   cannot_tell from the abstract alone. Mismatches become findings; verified
   claims are also shown, labeled as such.

*Uncited claims* — per section, the LLM lists sentences that assert prior
work or empirical facts but carry no citation. Candidates are kept only if
they appear verbatim in the text and genuinely have no citation token, so the
model cannot invent a problem that isn't there.

*Structural checks* — deterministic, no LLM: citation bundles (4+ works cited
together for one claim) and citation-diversity concentration (many references
sharing one first author) are flagged from the CSL-JSON data directly.

Every finding that names a work links to the real source (OpenAlex/Semantic
Scholar URL).

### Natural-language editing (`agent/editor.py` + `agent/ops.py`)

A command like "add more citations to the introduction" flows through:

1. **Plan** — one LLM call maps the command onto a small op vocabulary
   (`rewrite`, `shorten`, `add_citations`) with target section ids, validated
   against the paper's outline.
2. **Execute** — per op:
   - *rewrite/shorten*: the model edits the tokenized text under a hard rule —
     every citation token must survive verbatim, same count. The result is
     checked mechanically (`check_integrity`); a violation gets one corrective
     retry, then the op is marked failed and the section left untouched.
   - *add_citations*: queries are extracted, both APIs searched, and the model
     places candidates (by index) at specific sentences. New tokens are
     inserted deterministically by our code, not by model text generation.
3. **Propose** — everything becomes an `EditProposal` of per-section
   before/after diffs plus fully-provenanced new references. Each diff carries
   "what changed and why" notes (one line per change; for added citations, the
   source and the reason it supports that sentence), so approval is an informed
   decision, not a text-comparison chore. Nothing mutates the paper. Failed
   operations report the exact violation (which citation token, how many
   occurrences before vs. after), not a generic error.
4. **Approve** — on approval, `ops.apply_diffs` re-checks the invariant
   against the *current* paper state: no token dropped, no unknown token
   cited, no unprovenanced reference added. Only then is the text swapped.
5. **Self-review** — editing can create the exact problem review detects: a
   claim without support. So after an edit is applied, the sentences it
   introduced or reworded (and only those) are re-run through the
   uncited-claim check, and hits are attached to the proposal as warnings
   ("this new sentence may need a citation"). The check can never block an
   approved edit, only annotate it.

*History and undo* — proposals carry created/applied timestamps, so the Edit
tab doubles as an audit trail of what changed and why. The most recent
applied edit can be undone: the revert only proceeds if the affected sections
are still exactly as that edit left them, the same integrity check protects
every pre-existing citation (only references the proposal itself introduced
may disappear with it), and references it added are removed once nothing
cites them.

### Ask the paper (`agent/qa.py`)

A chat tab answers questions from the paper's own text only. The model never
*produces* evidence, it *points* at it: every sentence of the paper gets a
stable id (`sec15#3`), the model cites the ids its answer rests on, and we
look the sentences up ourselves — so a displayed quote is verbatim paper text
by construction, and a fabricated quote is structurally impossible. Invalid
ids are dropped and the answer flagged; "the paper doesn't say" is a
first-class answer. Source chips in the UI jump to the quoted section, and
any references involved are linked.

### Citation integrity invariant

`check_integrity(old, new)` compares token multisets: every token in the old
text must appear at least as often in the new text, unless its removal is in
an explicit `allowed_removals` set (surfaced to the user). This single
mechanism is what guarantees "existing citations survive, nothing is dropped
silently" across arbitrary LLM rewrites — the model physically cannot lose a
citation without the API rejecting the edit.

### External API boundary

`search/openalex.py` and `search/semantic_scholar.py` are thin, honest
clients: network errors return empty results (surfaced as findings/warnings,
never fabricated), and all calls go through an on-disk JSON cache
(`backend/data/cache/`) for reproducibility and politeness. Parse-time
resolution is batch-first (OpenAlex DOI OR-filter, Semantic Scholar
`POST /paper/batch`); title search uses `search/match.py` (SBMV
corroboration). Search results that are the paper itself are dropped
before the model sees them.

---

## Module map

```
backend/app/
  parsing/      extract → structure → references → fields → intext → style
  citations/    csl.py (citeproc rendering), styles/*.csl (official CSL files)
  search/       openalex.py, semantic_scholar.py, aggregate.py, match.py, cache.py
  agent/        llm.py (JSON-only wrapper), review.py, editor.py,
                ops.py (integrity invariant + apply)
  export/       latex.py (structure + \cite + CSL-rendered bibliography),
                bibtex.py (CSL-JSON -> biblatex .bib)
  api/routes.py REST endpoints        store.py  JSON persistence
  models.py     Paper / Reference / InTextCitation / Finding / EditProposal
frontend/src/
  App.tsx       upload-first flow, paper pane + Parse/Review/Edit/Ask tabs
  components/   CiteText (token rendering; chips are clickable), CitationModal
                ("explain this citation": resolved reference, abstract,
                claim-check verdict inline in the paper view), ReferenceLink
                (shared real-source link), ReferencesPanel, ReviewPanel,
                EditPanel (diff approval, history, undo), ChatPanel, UploadScreen
```

## Tests

`backend/tests/` covers the core behavior: reference segmentation for all
three schemes (including the surfaced-not-dropped remainder, sequence gaps,
and heading-less density fallback), field parsing per style, in-text
tokenization and resolution (ranges, parenthetical and narrative author-year,
ambiguous matches left unlinked, letter-suffix disambiguation, non-citation
parentheses), title-match corroboration (SBMV), style detection and the
style-consistency lint, CSL rendering in both styles (including correct
entry mapping under APA's alphabetical sort), the full integrity invariant (silent drops, allowed
removals, unknown tokens, unprovenanced references), undo (exact revert,
refusal when the section changed since, protection of pre-existing citations
against a corrupted revert), the post-edit new-sentence detector, and LaTeX
export (citation tokens, failed refs kept, provenance notes).

## Where AI tools were used, and what I verified

I designed the architecture myself — the parse pipeline, the CSL-JSON
intermediate representation, the citation-integrity token invariant, the
grounded agent loop, and the API surface are my design decisions (see
[docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md)). I used Cursor as a coding
assistant to write code and tests against that design. I verified myself:
the full test suite (83 tests), end-to-end parsing on two real arXiv papers
with different citation styles (Attention: 40 refs, 63/63 markers resolved,
IEEE detected; BERT: 56 refs, 41/42 markers resolved, APA detected), live
Semantic Scholar/OpenAlex queries, and the upload → parse → export HTTP flow.
LLM-dependent flows (review, editing) require an OpenAI key at runtime and
enforce their guarantees in code (index-only candidate selection, provenance
checks, token integrity), not in prompts alone.

## Known limitations / with more time

- Reference-list layout analysis assumes one- or two-column pages; exotic
  layouts fall back to regex segmentation with a surfaced warning.
- Author name splitting is best-effort; particles ("van der Maaten") stay
  on the family name, and org authors ("AI@Meta") are kept as CSL literals.
  Remaining edge cases can still be cleaned up by API enrichment.
- The LaTeX export uses `thebibliography` with CSL-rendered entries; the
  separate `.bib` export (biblatex) covers the round-trip use case, but the
  `.tex` itself doesn't reference it yet.
- Claim/citation checking judges against abstracts only (full text is rarely
  available); the verdict labels say so.
- Review runs are capped (sections/citations per run) to keep latency and
  cost sane; caps are reported honestly in the findings list.
- No streaming progress for long review runs; the UI shows a busy state.
