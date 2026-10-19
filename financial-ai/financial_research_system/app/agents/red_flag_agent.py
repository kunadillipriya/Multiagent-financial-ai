"""
red_flag_agent.py
------------------
AGENT 3: Red Flag Agent

Scans a document for anomalies, automatically, right after the Extraction
Agent finishes. Two independent passes, both grounded in the actual source
text/numbers (never invented):

  PASS A - Numeric rules: compares each metric's two most recent periods
  (e.g. FY2024 vs FY2023) already sitting in the `metrics` table and flags
  meaningful deteriorations -- rising debt, rising leverage, shrinking
  margins, falling returns, weakening liquidity, negative free cash flow.
  Each flag cites the exact source_chunk_id the underlying metric came from.

  PASS B - Language rules: scans each chunk's raw text for auditor/risk
  language ("material weakness", "going concern", "emphasis of matter",
  "qualified opinion", litigation, recalls, debt covenants, rising DSO).
  Each pattern has a NEGATION CHECK: if a negation word ("no", "not",
  "without", "zero", "never") appears in the ~45 characters right before the
  match, the flag is suppressed -- this is what lets "No material
  weaknesses were reported" correctly NOT raise a flag.

Both passes write to the `red_flags` table via database.py, already keyed
to the document and (where applicable) the source chunk, so every flag is
traceable back to the passage that justifies it -- the evaluation harness
in evaluation.py checks exactly this ("source faithfulness").
"""

import os
import re
from app import database as db
from app.paths import RAW_TEXT_DIR

# ---------------------------------------------------------------------------
# PASS A: Numeric rules
# ---------------------------------------------------------------------------

# Each rule: (metric_name, direction, pct_threshold, flag_type, label)
# direction "down" flags a decrease of at least pct_threshold; "up" flags an
# increase of at least pct_threshold. Percentages are relative change.
TREND_RULES = [
    ("total_debt", "up", 15, "rising_debt", "Total debt"),
    ("debt_to_equity_ratio", "up", 10, "rising_leverage", "Debt-to-equity ratio"),
    ("gross_margin_pct", "down_points", 3, "margin_compression", "Gross margin"),
    ("operating_margin_pct", "down_points", 3, "margin_compression", "Operating margin"),
    ("net_margin_pct", "down_points", 2, "margin_compression", "Net margin"),
    ("return_on_equity_pct", "down", 20, "declining_returns", "Return on equity"),
    ("current_ratio", "down", 10, "liquidity_weakening", "Current ratio (liquidity)"),
]

# Level rules: flag based on the most recent period's absolute value alone,
# regardless of trend.
LEVEL_RULES = [
    ("current_ratio", "below", 1.2, "liquidity_risk", "medium",
     "Current ratio below a healthy 1.2x threshold"),
    ("debt_to_equity_ratio", "at_or_above", 0.9, "high_leverage", "medium",
     "Debt-to-equity ratio approaching or above 0.9x"),
    ("free_cash_flow", "below", 0, "negative_free_cash_flow", "high",
     "Free cash flow is negative"),
]


def _latest_two_periods(metric_rows: list):
    """metric_rows: all rows for ONE metric_name. Returns (newer, older) or
    (None, None) if fewer than 2 periods exist. 'Newer' is just whichever
    period comes last alphabetically among FYxxxx-style labels, which holds
    for the FY2023/FY2024-style periods these documents use."""
    if len(metric_rows) < 2:
        return None, None
    rows_sorted = sorted(metric_rows, key=lambda r: r["period"])
    return rows_sorted[-1], rows_sorted[-2]


def run_numeric_rules(document_id: int) -> list:
    metrics = db.get_metrics_for_document(document_id)
    by_name = {}
    for m in metrics:
        by_name.setdefault(m["metric_name"], []).append(m)

    flags = []

    for metric_name, direction, threshold, flag_type, label in TREND_RULES:
        rows = by_name.get(metric_name, [])
        newer, older = _latest_two_periods(rows)
        if not newer or not older or older["metric_value"] in (None, 0):
            continue

        new_v, old_v = newer["metric_value"], older["metric_value"]

        if direction == "up":
            pct_change = (new_v - old_v) / abs(old_v) * 100
            triggered = pct_change >= threshold
            severity = "high" if pct_change >= threshold * 2 else "medium"
            desc = (f"{label} increased from {old_v:,.2f} ({older['period']}) to "
                    f"{new_v:,.2f} ({newer['period']}), a change of +{pct_change:.1f}%.")
        elif direction == "down":
            pct_change = (new_v - old_v) / abs(old_v) * 100
            triggered = pct_change <= -threshold
            severity = "high" if pct_change <= -threshold * 2 else "medium"
            desc = (f"{label} declined from {old_v:,.2f} ({older['period']}) to "
                    f"{new_v:,.2f} ({newer['period']}), a change of {pct_change:.1f}%.")
        elif direction == "down_points":
            point_change = new_v - old_v
            triggered = point_change <= -threshold
            # Severity escalates when the RELATIVE decline is severe (>=20%),
            # not just the absolute percentage-point move -- this is what
            # correctly tells a mild 4-point slip from a near-collapse.
            relative_pct = (point_change / abs(old_v) * 100) if old_v else 0
            severity = "high" if relative_pct <= -20 else "medium"
            desc = (f"{label} declined from {old_v:.2f} ({older['period']}) to "
                    f"{new_v:.2f} ({newer['period']}), a change of {point_change:.2f} "
                    f"percentage points.")
        else:
            continue

        if triggered:
            flags.append({
                "flag_type": flag_type,
                "description": desc,
                "severity": severity,
                "source_chunk_id": newer["source_chunk_id"],
            })

    for metric_name, comparator, threshold, flag_type, severity, label in LEVEL_RULES:
        rows = by_name.get(metric_name, [])
        if not rows:
            continue
        latest = sorted(rows, key=lambda r: r["period"])[-1]
        v = latest["metric_value"]
        if v is None:
            continue

        if comparator == "below" and v < threshold:
            triggered = True
        elif comparator == "at_or_above" and v >= threshold:
            triggered = True
        else:
            triggered = False

        if triggered:
            flags.append({
                "flag_type": flag_type,
                "description": f"{label} (current value: {v:,.2f}, {latest['period']}).",
                "severity": severity,
                "source_chunk_id": latest["source_chunk_id"],
            })

    return flags


# ---------------------------------------------------------------------------
# PASS B: Language rules
# ---------------------------------------------------------------------------

NEGATION_WORDS = ("no ", "not ", "without ", "never ", "zero ", "none ")
NEGATION_WINDOW_CHARS = 45

LANGUAGE_RULES = [
    (r"material weakness", "material_weakness", "high"),
    (r"going[- ]concern", "going_concern", "high"),
    (r"emphasis[- ]of[- ]matter", "emphasis_of_matter", "medium"),
    (r"(?<!un)qualified opinion", "qualified_audit_opinion", "high"),
    (r"litigation|lawsuit", "litigation", "medium"),
    (r"recall", "product_recall", "medium"),
    (r"covenant", "debt_covenant_mention", "medium"),
    # Handles both real-world phrasings: "days sales outstanding increased"
    # AND "[accounts] receivable days outstanding increased" (the word order
    # differs between filings, so "days" is treated as optional/either-side).
    (r"(sales|receivable)s?\s*(days\s+)?outstanding\s+increased", "rising_dso", "medium"),
]


def _is_negated(text: str, match_start: int) -> bool:
    window_start = max(0, match_start - NEGATION_WINDOW_CHARS)
    # MILESTONE 4 FIX (found by run_tests.py): a negation word right at a
    # line wrap reads as "...with no\ngoing-concern..." in real document
    # text -- the newline, not a space, separates "no" from the next word.
    # NEGATION_WORDS all end in a literal space (e.g. "no "), so without
    # this normalization that exact case is missed and the flag fires
    # anyway. Collapsing all whitespace runs (space, newline, tab) to a
    # single space before checking makes the match whitespace-agnostic.
    window = re.sub(r"\s+", " ", text[window_start:match_start].lower())
    return any(neg in window for neg in NEGATION_WORDS)


def _find_chunk_for_position(chunks: list, position: int):
    """Maps a character offset in the full document text back to the chunk
    that contains it, using each chunk's stored char_start/char_end (set by
    chunk_text() in document_agent.py against this exact same text)."""
    for chunk in chunks:
        start, end = chunk["char_start"], chunk["char_end"]
        if start is not None and end is not None and start <= position < end:
            return chunk
    # Fallback (shouldn't normally happen): nearest chunk by start offset.
    return min(chunks, key=lambda c: abs((c["char_start"] or 0) - position)) if chunks else None


def run_language_rules(document_id: int) -> list:
    """
    MILESTONE 4 FIX: this previously scanned each chunk's text in
    isolation, which caused two real bugs that the end-to-end test suite
    (run_tests.py) caught:
      1. A phrase split by a chunk boundary (e.g. "...with no" at the end
         of one chunk, "going-concern issues noted" at the start of the
         next) could not see its own negating word, since the negation
         check only looked backward WITHIN the same chunk -- producing a
         false positive.
      2. The same phrase appearing in the overlapping region shared by two
         adjacent chunks (see CHUNK_OVERLAP_CHARS in document_agent.py) was
         matched and flagged twice.

    Fix: scan the document's full raw text ONCE (so negation context is
    never cut off by a chunk boundary), then keep only the first
    non-negated match per flag_type (a single underlying concern -- e.g.
    one product recall -- is one red flag, regardless of how many
    sentences mention it). The matched position is then mapped back to its
    containing chunk purely for citation purposes.
    """
    doc = db.get_document(document_id)
    chunks = db.get_chunks_for_document(document_id)
    if not chunks:
        return []

    raw_text_path = os.path.join(RAW_TEXT_DIR, f"doc_{document_id}.txt")
    if doc and os.path.exists(raw_text_path):
        with open(raw_text_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    else:
        # Fallback if the raw text file is missing for some reason: rebuild
        # from chunks in char_start order with naive overlap trimming. Less
        # precise than the raw file, but still correct for the common case.
        ordered = sorted(chunks, key=lambda c: c["chunk_index"])
        text = "\n\n".join(c["text"] for c in ordered)

    lowered = text.lower()
    flags = []
    seen_flag_types = set()

    for pattern, flag_type, severity in LANGUAGE_RULES:
        if flag_type in seen_flag_types:
            continue
        for m in re.finditer(pattern, lowered):
            if _is_negated(lowered, m.start()):
                continue
            chunk = _find_chunk_for_position(chunks, m.start())
            # Clamp the snippet window to the chosen chunk's own boundaries
            # (not just the full document's), so the quoted snippet is
            # always a genuine substring of that specific chunk's text --
            # this is exactly what evaluation.py's faithfulness check
            # verifies, so this clamp is what keeps that check meaningful.
            if chunk and chunk["char_start"] is not None:
                lo, hi = chunk["char_start"], chunk["char_end"]
            else:
                lo, hi = 0, len(text)
            snippet_start = max(lo, m.start() - 40)
            snippet_end = min(hi, m.end() + 40)
            snippet = text[snippet_start:snippet_end].strip()
            flags.append({
                "flag_type": flag_type,
                "description": f'Document language flagged: "...{snippet}..."',
                "severity": severity,
                "source_chunk_id": chunk["id"] if chunk else chunks[0]["id"],
            })
            seen_flag_types.add(flag_type)
            break  # first non-negated match for this flag_type is enough

    return flags


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_red_flag_scan(document_id: int) -> dict:
    db.update_document_status(document_id, "scanning_red_flags")

    numeric_flags = run_numeric_rules(document_id)
    language_flags = run_language_rules(document_id)
    all_flags = numeric_flags + language_flags

    if all_flags:
        db.insert_red_flags(document_id, all_flags)

    db.update_document_status(document_id, "red_flags_scanned")

    return {
        "document_id": document_id,
        "num_flags": len(all_flags),
        "num_numeric_flags": len(numeric_flags),
        "num_language_flags": len(language_flags),
        "flag_types_found": sorted(set(f["flag_type"] for f in all_flags)),
    }
