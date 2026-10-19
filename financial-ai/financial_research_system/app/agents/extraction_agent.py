"""
extraction_agent.py
--------------------
AGENT 2: Extraction Agent

Pulls structured financial metrics out of a document's chunks, immediately
after the Document Agent finishes ingestion. Regex-based (not an LLM call):
company financial tables follow a very consistent
    "<Metric Name>: <value> [unit] (<period>) [vs <value> [unit] (<period>)]"
shape once flattened to text, so deterministic extraction is faster, free,
and fully auditable -- every number traces back to an exact source chunk.
"""

import re
from app import database as db

# MILESTONE 4 OPTIMIZATION: expanded with common synonyms real filings use
# for the same underlying metric (e.g. "Revenues" vs "Total Revenue", "Net
# Sales" vs "Revenue", "Net Earnings" vs "Net Income"), so extraction is
# robust across different companies' and document types' label wording --
# not just the exact phrasing used by the 3 seed documents.
CANONICAL_METRICS = {
    # Revenue
    "total revenue": "total_revenue", "revenue": "total_revenue",
    "revenues": "total_revenue", "net revenue": "total_revenue",
    "net revenues": "total_revenue", "net sales": "total_revenue",
    "total net sales": "total_revenue", "sales": "total_revenue",
    # Cost of revenue
    "cost of revenue": "cost_of_revenue", "cost of revenues": "cost_of_revenue",
    "cost of sales": "cost_of_revenue", "cost of goods sold": "cost_of_revenue",
    "cogs": "cost_of_revenue",
    # Gross profit / margin
    "gross profit": "gross_profit", "gross income": "gross_profit",
    "gross margin": "gross_margin_pct", "gross profit margin": "gross_margin_pct",
    # Operating expenses / income / margin
    "operating expenses": "operating_expenses", "total operating expenses": "operating_expenses",
    "operating income": "operating_income", "income from operations": "operating_income",
    "operating profit": "operating_income",
    "operating margin": "operating_margin_pct", "operating profit margin": "operating_margin_pct",
    # Net income / margin
    "net income": "net_income", "net earnings": "net_income",
    "net profit": "net_income", "profit for the year": "net_income",
    "net income attributable to shareholders": "net_income",
    "net margin": "net_margin_pct", "net profit margin": "net_margin_pct",
    # EPS
    "earnings per share (diluted eps)": "diluted_eps", "diluted eps": "diluted_eps",
    "diluted earnings per share": "diluted_eps", "earnings per share diluted": "diluted_eps",
    "basic eps": "basic_eps", "basic earnings per share": "basic_eps",
    # EBITDA
    "ebitda": "ebitda", "adjusted ebitda": "adjusted_ebitda",
    # Balance sheet
    "total assets": "total_assets", "total liabilities": "total_liabilities",
    "total debt": "total_debt", "total borrowings": "total_debt",
    "long-term debt": "long_term_debt", "long term debt": "long_term_debt",
    "total shareholders equity": "total_shareholders_equity",
    "total stockholders equity": "total_shareholders_equity",
    "stockholders equity": "total_shareholders_equity",
    "shareholders equity": "total_shareholders_equity",
    "total equity": "total_shareholders_equity",
    "cash and cash equivalents": "cash_and_equivalents",
    "cash and equivalents": "cash_and_equivalents",
    # Cash flow
    "operating cash flow": "operating_cash_flow",
    "cash flow from operations": "operating_cash_flow",
    "net cash provided by operating activities": "operating_cash_flow",
    "free cash flow": "free_cash_flow",
    "capital expenditures": "capital_expenditures", "capex": "capital_expenditures",
    # Ratios
    "debt to equity ratio": "debt_to_equity_ratio", "debt-to-equity ratio": "debt_to_equity_ratio",
    "current ratio": "current_ratio", "quick ratio": "quick_ratio",
    "return on equity (roe)": "return_on_equity_pct", "return on equity": "return_on_equity_pct",
    "roe": "return_on_equity_pct",
    "return on assets (roa)": "return_on_assets_pct", "return on assets": "return_on_assets_pct",
    "roa": "return_on_assets_pct",
}

VALUE_GROUP_RE = re.compile(
    r"(\$?-?[\d,]+(?:\.\d+)?%?)\s*(million|billion|thousand)?\s*\(([^)]+)\)",
    re.IGNORECASE,
)
# MILESTONE 4 OPTIMIZATION: broadened to tolerate real-world formatting
# variety -- an optional leading bullet/dash marker, and labels containing
# apostrophes ("Stockholders' Equity"), periods ("U.S. Revenue"), ampersands
# ("Selling, General & Administrative"), or digits ("2024 Revenue") -- none
# of which the original (stricter) pattern allowed.
LABEL_LINE_RE = re.compile(r"^\s*[-•\*]?\s*([A-Za-z][A-Za-z0-9 /\-\(\)&'\.,]{2,70}?):\s*(.+)$")
UNIT_MULTIPLIER = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def _normalize_label(label: str) -> str:
    return CANONICAL_METRICS.get(label.strip().lower(), label.strip().lower().replace(" ", "_"))


def _parse_value(raw: str, unit_word: str):
    is_pct = raw.strip().endswith("%")
    cleaned = raw.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None, None

    if is_pct:
        return value, "%"
    if unit_word:
        value *= UNIT_MULTIPLIER.get(unit_word.lower(), 1)
        return value, "USD"
    if raw.strip().startswith("$"):
        return value, "USD"
    return value, "ratio"


def extract_metrics_from_text(label: str, rest_of_line: str) -> list:
    results = []
    matches = VALUE_GROUP_RE.findall(rest_of_line)
    if not matches:
        return results

    metric_name = _normalize_label(label)
    for raw_value, unit_word, period in matches:
        value, unit = _parse_value(raw_value, unit_word)
        if value is None:
            continue
        results.append({
            "metric_name": metric_name,
            "metric_value": value,
            "raw_value": raw_value + (f" {unit_word}" if unit_word else ""),
            "unit": unit,
            "period": period.strip(),
        })
    return results


def run_extraction(document_id: int) -> dict:
    chunks = db.get_chunks_for_document(document_id)
    all_metrics = []
    seen = set()  # dedupe metrics that land in two overlapping chunks

    for chunk in chunks:
        for line in chunk["text"].splitlines():
            m = LABEL_LINE_RE.match(line)
            if not m:
                continue
            label, rest = m.group(1), m.group(2)
            metrics = extract_metrics_from_text(label, rest)
            for metric in metrics:
                key = (metric["metric_name"], metric["period"], metric["metric_value"])
                if key in seen:
                    continue
                seen.add(key)
                metric["source_chunk_id"] = chunk["id"]
                all_metrics.append(metric)

    if all_metrics:
        db.insert_metrics(document_id, all_metrics)

    db.update_document_status(document_id, "extracted")

    return {
        "document_id": document_id,
        "num_metrics_extracted": len(all_metrics),
        "metric_names_found": sorted(set(m["metric_name"] for m in all_metrics)),
    }
