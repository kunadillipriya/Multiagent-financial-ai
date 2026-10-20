# System Architecture — Multi-Agent Financial Research System

## Pipeline overview

```
  Upload/Seed doc                              User question
        |                                            |
        v                                            v
 ┌─────────────────┐                        ┌──────────────────┐
 │ Document Classifier│ --reject if not-->   │  Research Agent    │
 │ (financial doc gate)│    financial        │  retrieve -> reason │
 └─────────┬─────────┘                       │  -> cite            │
           v                                 └─────────┬──────────┘
 ┌─────────────────┐                                   │
 │ 1. Document Agent │                                   │ reads
 │ parse->chunk->embed│                                   v
 │ ->index (per session)│                      shared vector index +
 └─────────┬─────────┘                         structured metrics/flags
           │ orchestrator.py triggers, in order
           v
 ┌─────────────────┐
 │ 2. Extraction Agent│
 └─────────┬─────────┘
           v
 ┌─────────────────┐
 │ 3. Red Flag Agent  │
 └─────────┬─────────┘
           v
 ┌─────────────────┐       ┌──────────────────┐
 │ 4. Comparison Agent│<----│ 6. Report Agent     │
 │ (on demand)         │     │ compiles all 5      │
 └─────────────────┘       │ sections + PDF       │
                            └──────────────────┘
```

Every agent downstream of the Document Agent reads **only** from what the
Document Agent indexed and what the Extraction/Red Flag Agents structured —
never from model "knowledge" — enforcing the project's core requirement
that every insight is grounded in source documents.

## Agent responsibilities

| # | Agent | Status | Input | Output |
|---|-------|--------|-------|--------|
| - | Document Classifier | Milestone 4 | raw parsed text | accept/reject decision + reason, before any other agent runs |
| 1 | Document Agent | Complete | file (.txt/.pdf/.docx) | chunks (SQLite) + TF-IDF vector index per session |
| 2 | Extraction Agent | Complete | a document's chunks | structured metrics, each linked to its source chunk |
| 3 | Red Flag Agent | Complete | a document's metrics + full text | flagged anomalies, each linked to a source chunk |
| 4 | Comparison Agent | Complete | metrics across 2+ documents | side-by-side benchmark + ranking |
| 5 | Research Agent | Complete | user's question | multi-step retrieval + reasoned, cited answer |
| 6 | Report Agent | Complete | outputs of agents 2-5 | 5-section report (JSON) + PDF export |

## Milestone 4 additions

### Document Classifier (`app/agents/document_classifier.py`)
Runs as the first step inside `document_agent.process_document()`, before
chunking/indexing. Scores the parsed text on three independent signals:
1. **Financial vocabulary density** — count of distinct terms from a
   curated list (revenue, EBITDA, balance sheet, auditor, etc.)
2. **Structured data lines** — count of lines matching the
   `Label: $value (period)` shape the Extraction Agent looks for
3. **Filing-language phrases** — "annual report," "10-K," "independent
   auditor," "management discussion and analysis," etc.

A document must clear a minimum bar on these signals to be accepted. If
rejected, `document_agent.py` raises `NotFinancialDocumentError` (a
`ValueError` subclass) with the specific reason and scores; the
orchestration layer and API surface this directly to the caller rather than
silently failing, and the document is marked `status = 'rejected'` in the
database (not deleted — kept for transparency).

### Complete Report Agent + PDF export (`app/agents/report_agent.py`)
Added `generate_red_flags_section()`, `generate_comparison_section()`
(reuses the Comparison Agent rather than re-implementing ranking),
`generate_outlook_section()`, and `compile_full_report()`. The Outlook
section is deliberately **rule-based, not LLM-generated** — it derives a
Stable/Caution/Elevated-Risk label purely from the red-flag severity counts
already computed by Agent 3, so the report's one "judgment" section stays
just as auditable as its purely-restated numbers. `render_pdf()` uses
reportlab (pure-Python, no system dependencies) to turn the compiled report
into an actual downloadable PDF, mirroring the JSON structure section for
section so the PDF and the `/report/full` JSON never drift apart.

### End-to-end test suite (`run_tests.py`)
Exercises the real HTTP API (via FastAPI's `TestClient`) against a
temporary, isolated data directory (`FRS_DATA_DIR` environment variable,
resolved in the new `app/paths.py`), so it never touches a user's real
data. Covers the four areas Milestone 4 calls for explicitly: agent
collaboration, extraction correctness, citation accuracy, and report
completeness. This suite is what caught and drove the fix for two real
bugs during development (see "Bugs found and fixed" below) — it is a
genuine regression safety net, not a formality.

### Optimizations (reliability across varied document formats)
- `extraction_agent.py`: `CANONICAL_METRICS` expanded from ~20 to ~50
  entries, covering common real-world label synonyms ("Net Sales" vs
  "Total Revenue", "Net Earnings" vs "Net Income", "Stockholders Equity"
  vs "Shareholders Equity", etc.) and a looser `LABEL_LINE_RE` that
  tolerates bullet markers, apostrophes, and periods in labels.
- `document_agent.py`: new `normalize_text()` step collapses whitespace
  artifacts and rejoins words hyphenated across a PDF line break, run on
  every document before chunking.
- `vector_store.py`: `TfidfVectorizer` now indexes 1- and 2-word phrases
  (`ngram_range=(1,2)`) with `sublinear_tf=True`, so multi-word financial
  terms ("material weakness," "net income") score much more precisely in
  retrieval than they did under single-word, raw-count TF-IDF.
- `app/paths.py`: centralized data-directory resolution (previously
  duplicated in 4 files), enabling the isolated test suite above.

### Bugs found and fixed by the test suite
Running `run_tests.py` for the first time surfaced two real, non-obvious
bugs, both now fixed with regression coverage in the suite itself:
1. **Red Flag Agent, cross-chunk negation blind spot**: language rules ran
   per-chunk; a negating word like "no" immediately before a line wrap
   (`"...with no\ngoing-concern..."`) sat in one chunk while the flagged
   phrase started the next, so the negation check — which only looked
   backward within the same chunk — missed it, firing a false positive.
   Separately, the negation word list required a literal trailing space
   (`"no "`), which a word immediately followed by a newline (`"no\n"`)
   never matches. **Fix:** `run_language_rules()` now scans the full
   document's raw text once (eliminating the chunk-boundary blind spot),
   keeps only the first match per flag type (eliminating duplicate flags
   from overlapping chunks), and the negation window is whitespace-
   normalized before matching.
2. **Evaluation harness, asymmetric whitespace normalization**: the
   red-flag faithfulness check stripped newlines from the chunk's stored
   text but not from the quoted snippet being checked against it, so a
   genuinely verbatim citation that happened to straddle a line wrap in
   the source document was wrongly reported as "not faithful." **Fix:**
   both sides of the comparison now go through the same
   `_collapse_whitespace()` helper.

## Data model

Unchanged from Milestone 3, plus `documents.status` now includes
`'rejected'` (with `rejection_reason` and `rejection_confidence` columns)
for documents the classifier declined to process, and `pipeline_runs`
records per-stage timing/outcome for every orchestrated run.

See `app/database.py` for the exact SQL schema; `app/paths.py` for where
all data is stored.
