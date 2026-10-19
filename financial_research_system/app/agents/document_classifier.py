"""
document_classifier.py
-----------------------
A gatekeeper the Document Agent runs on every uploaded file BEFORE chunking,
indexing, or extracting anything from it. Its only job is to answer one
question: "Is this actually a financial document?"

Why this exists: without it, the Document Agent will happily parse, chunk,
and index ANY readable text file -- a recipe, a novel, a resume -- because
parsing text doesn't require the text to be about finance. This module adds
a check in front of that pipeline so non-financial uploads are rejected
before they ever reach the Extraction or Red Flag agents.

How it decides (no AI model, no API call -- fully deterministic and free):
A real financial document (annual report, 10-K, 10-Q, earnings release,
balance sheet, etc.) reliably contains a mix of three kinds of evidence:

  1. STRONG PHRASES   -- things that only appear in financial filings, e.g.
                          "balance sheet", "independent auditor", "10-K".
                          Finding even ONE of these is enough on its own.
  2. METRIC TERMS      -- financial vocabulary, e.g. "revenue", "EBITDA",
                          "gross margin". These are good evidence but, on
                          their own, two or three could appear in an
                          unrelated article, so several are required together.
  3. STRUCTURED METRIC LINES -- lines shaped like "Total Revenue: $482.30
                          million (FY2024)", the same pattern the Extraction
                          Agent looks for. A document with several of these
                          is almost certainly a real financial statement.

A document passes if ANY of these three kinds of evidence clears its bar.
This mirrors how a human skimming the document would decide, and -- because
it's just pattern matching over the text -- it's instant, needs no API key,
and never has to be "trusted" the way a black-box AI classifier would.
"""

import re

# --- 1. Strong phrases: finding even one is enough on its own ---------------
STRONG_PHRASES = [
    "annual report", "form 10-k", "10-k filing", " 10-k ", "form 10-q",
    "quarterly report", "balance sheet", "income statement",
    "statement of operations", "statement of cash flows", "cash flow statement",
    "financial statements", "independent auditor", "auditor's report",
    "auditor's opinion", "management discussion and analysis", "md&a",
    "securities and exchange commission", "sec filing", "earnings release",
    "earnings call transcript", "prospectus", "selected financial data",
    "notes to financial statements", "consolidated balance sheet",
    "consolidated statement", "10-k", "10-q",
]

# --- 2. Financial vocabulary: need several together to count ----------------
METRIC_TERMS = [
    "revenue", "net income", "gross profit", "operating income", "ebitda",
    "total assets", "total liabilities", "shareholders equity",
    "stockholders equity", "earnings per share", "diluted eps",
    "gross margin", "operating margin", "net margin", "cash and cash equivalents",
    "accounts receivable", "accounts payable", "free cash flow",
    "operating cash flow", "return on equity", "debt to equity",
    "current ratio", "cost of revenue", "cost of goods sold", "fiscal year",
    "quarterly earnings", "capital expenditure", "working capital",
]
MIN_METRIC_TERMS = 4  # need at least this many distinct terms to count as evidence

# --- 3. Structured "Label: $value (period)" lines, same shape the ----------
#        Extraction Agent looks for -- see extraction_agent.py
STRUCTURED_LINE_RE = re.compile(
    r"^\s*[A-Za-z][A-Za-z /\-\(\)]{2,60}?:\s*.*"
    r"(\$?-?[\d,]+(?:\.\d+)?%?)\s*(million|billion|thousand)?\s*\([^)]+\)",
    re.IGNORECASE | re.MULTILINE,
)
MIN_STRUCTURED_LINES = 3  # need at least this many to count as evidence


def classify_document(text: str) -> dict:
    """
    Returns:
        {
            "is_financial": bool,
            "confidence": float (0-1, a rough signal strength, not a probability),
            "matched_strong_phrases": [...],
            "matched_metric_terms": [...],
            "structured_line_count": int,
            "reason": str,   # human-readable explanation, shown to the user on rejection
        }
    """
    lowered = text.lower()

    matched_strong = sorted({p.strip() for p in STRONG_PHRASES if p.strip() in lowered})
    matched_metrics = sorted({t for t in METRIC_TERMS if t in lowered})
    structured_lines = STRUCTURED_LINE_RE.findall(text)
    structured_count = len(structured_lines)

    has_strong = len(matched_strong) >= 1
    has_enough_metrics = len(matched_metrics) >= MIN_METRIC_TERMS
    has_enough_structure = structured_count >= MIN_STRUCTURED_LINES

    is_financial = has_strong or has_enough_metrics or has_enough_structure

    # Confidence is just a simple, explainable blend of the three signals --
    # not a statistical probability, just a number the UI can show a bar for.
    confidence = min(
        1.0,
        (0.5 if has_strong else 0.0)
        + min(len(matched_metrics) / 10, 0.3)
        + min(structured_count / 10, 0.3),
    )

    if is_financial:
        reasons = []
        if has_strong:
            reasons.append(f"found financial filing language ({', '.join(matched_strong[:3])})")
        if has_enough_metrics:
            reasons.append(f"found {len(matched_metrics)} financial metric terms")
        if has_enough_structure:
            reasons.append(f"found {structured_count} structured financial data lines")
        reason = "Classified as a financial document: " + "; ".join(reasons) + "."
    else:
        reason = (
            "This does not look like a financial document. Found only "
            f"{len(matched_metrics)} financial metric term(s) (need at least "
            f"{MIN_METRIC_TERMS}), {structured_count} structured financial data "
            f"line(s) (need at least {MIN_STRUCTURED_LINES}), and no financial "
            "filing language (e.g. 'balance sheet', 'annual report', "
            "'independent auditor'). Please upload an annual report, 10-K/10-Q "
            "filing, earnings release, or similar financial statement."
        )

    return {
        "is_financial": is_financial,
        "confidence": round(confidence, 3),
        "matched_strong_phrases": matched_strong,
        "matched_metric_terms": matched_metrics,
        "structured_line_count": structured_count,
        "reason": reason,
    }
