"""
report_agent.py
----------------
AGENT 6: Report Agent (Milestone 4: COMPLETE -- all five sections plus PDF
export).

Compiles outputs already produced by the other agents (Extraction, Red
Flag, Comparison) into a structured analyst-style report:
    1. Executive Summary
    2. Key Financials
    3. Red Flags
    4. Company Comparison
    5. Outlook

This agent does no extraction or analysis of its own -- every section only
reads already-computed metrics/flags from the database and formats them, so
every sentence/number in the final report is traceable back to a prior
agent's grounded output. The Outlook section is the only section that
synthesizes a judgment call ("elevated risk" / "stable") rather than just
restating a number -- it is deliberately kept 100% rule-based (not an LLM
call) so that judgment is still fully deterministic and explainable from
the red-flag counts and metric trends that produced it.
"""

import os
import datetime

from app import database as db
from app.agents import comparison_agent

# The curated subset of metrics shown in the Key Financials table and the
# Comparison section -- the full metrics table often has 20-40+ rows per
# company (including segment breakdowns); a report reads better with just
# the headline figures an analyst would lead with.
REPORT_HEADLINE_METRICS = [
    "total_revenue", "gross_margin_pct", "operating_margin_pct", "net_margin_pct",
    "net_income", "total_debt", "debt_to_equity_ratio", "current_ratio",
    "free_cash_flow", "return_on_equity_pct",
]


def _latest_two(metric_rows):
    rows = sorted(metric_rows, key=lambda r: r["period"])
    if len(rows) < 2:
        return (rows[-1] if rows else None), None
    return rows[-1], rows[-2]


def _fmt_money(v):
    if v is None:
        return "N/A"
    return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:,.2f}"


def generate_executive_summary(session_id: int) -> dict:
    """One short paragraph per company: revenue trend, margin trend, and
    the single most severe red flag (if any)."""
    docs = [d for d in db.list_documents(session_id) if d["status"] in
            ("extracted", "red_flags_scanned")]

    company_summaries = []
    for doc in docs:
        metrics = db.get_metrics_for_document(doc["id"])
        by_name = {}
        for m in metrics:
            by_name.setdefault(m["metric_name"], []).append(m)

        revenue_new, revenue_old = _latest_two(by_name.get("total_revenue", []))
        margin_new, margin_old = _latest_two(by_name.get("net_margin_pct", []))
        flags = db.get_red_flags_for_document(doc["id"])
        top_flag = next((f for f in flags if f["severity"] == "high"), flags[0] if flags else None)

        sentence_parts = []
        if revenue_new:
            sentence_parts.append(
                f"{doc['company_name']} reported {revenue_new['period']} revenue of "
                f"{_fmt_money(revenue_new['metric_value'])}"
            )
            if revenue_old and revenue_old["metric_value"]:
                pct = (revenue_new["metric_value"] - revenue_old["metric_value"]) / abs(revenue_old["metric_value"]) * 100
                direction = "grew" if pct >= 0 else "declined"
                sentence_parts.append(
                    f", which {direction} {abs(pct):.1f}% year-over-year (from "
                    f"{_fmt_money(revenue_old['metric_value'])} in {revenue_old['period']})"
                )
        if margin_new and margin_old:
            m_change = margin_new["metric_value"] - margin_old["metric_value"]
            m_direction = "expanded" if m_change >= 0 else "compressed"
            sentence_parts.append(f". Net margin {m_direction} to {margin_new['metric_value']:.2f}%")

        summary_text = "".join(sentence_parts) + "." if sentence_parts else \
            f"{doc['company_name']}: insufficient extracted data for a summary."

        if top_flag:
            summary_text += f" Most notable concern: {top_flag['description']}"

        company_summaries.append({
            "document_id": doc["id"],
            "company_name": doc["company_name"],
            "summary_text": summary_text,
            "num_red_flags": len(flags),
            "high_severity_flags": sum(1 for f in flags if f["severity"] == "high"),
        })

    overview = (
        f"This preview covers {len(company_summaries)} compan"
        f"{'y' if len(company_summaries) == 1 else 'ies'} in the current research "
        "session. Every figure and finding below was extracted directly from the "
        "uploaded source documents by the Document, Extraction, and Red Flag "
        "agents, and each one is traceable back to its exact source passage."
    )

    return {"overview": overview, "per_company": company_summaries}


def generate_key_financials_section(session_id: int) -> dict:
    """A simple per-company table of the core metrics, most recent period,
    with prior-period comparison where available."""
    docs = db.list_documents(session_id)
    core_metrics = [
        "total_revenue", "gross_margin_pct", "operating_margin_pct", "net_margin_pct",
        "net_income", "total_debt", "debt_to_equity_ratio", "current_ratio",
        "free_cash_flow", "return_on_equity_pct",
    ]

    tables = []
    for doc in docs:
        if doc["status"] not in ("extracted", "red_flags_scanned"):
            continue
        metrics = db.get_metrics_for_document(doc["id"])
        by_name = {}
        for m in metrics:
            by_name.setdefault(m["metric_name"], []).append(m)

        rows = []
        for metric_name in core_metrics:
            newer, older = _latest_two(by_name.get(metric_name, []))
            if not newer:
                continue
            rows.append({
                "metric": metric_name.replace("_", " ").replace("pct", "%").title(),
                "latest_period": newer["period"],
                "latest_value": newer["raw_value"] or newer["metric_value"],
                "prior_period": older["period"] if older else None,
                "prior_value": (older["raw_value"] or older["metric_value"]) if older else None,
            })

        tables.append({
            "document_id": doc["id"],
            "company_name": doc["company_name"],
            "rows": rows,
        })

    return {"tables": tables}


def generate_red_flags_section(session_id: int) -> dict:
    """Every detected red flag, grouped by company, with a severity count
    summary. Reads directly from the red_flags table (Red Flag Agent's
    output) -- no re-analysis happens here."""
    docs = [d for d in db.list_documents(session_id) if d["status"] in
            ("extracted", "red_flags_scanned")]

    companies = []
    total_high = total_medium = total_low = 0
    for doc in docs:
        flags = db.get_red_flags_for_document(doc["id"])
        high = [f for f in flags if f["severity"] == "high"]
        medium = [f for f in flags if f["severity"] == "medium"]
        low = [f for f in flags if f["severity"] == "low"]
        total_high += len(high)
        total_medium += len(medium)
        total_low += len(low)

        companies.append({
            "document_id": doc["id"],
            "company_name": doc["company_name"],
            "num_flags": len(flags),
            "num_high": len(high),
            "num_medium": len(medium),
            "num_low": len(low),
            "flags": [
                {"flag_type": f["flag_type"], "severity": f["severity"],
                 "description": f["description"]}
                for f in sorted(flags, key=lambda f: {"high": 0, "medium": 1, "low": 2}[f["severity"]])
            ],
        })

    return {
        "companies": companies,
        "totals": {"high": total_high, "medium": total_medium, "low": total_low,
                    "all": total_high + total_medium + total_low},
    }


def generate_comparison_section(session_id: int) -> dict:
    """Side-by-side ranking on the curated headline metrics, reusing the
    Comparison Agent (Agent 4) rather than re-implementing ranking logic."""
    rows = db.get_metrics_for_session(session_id)
    available_metrics = set(r["metric_name"] for r in rows)
    metrics_to_show = [m for m in REPORT_HEADLINE_METRICS if m in available_metrics]

    return {
        "metrics": {name: comparison_agent.compare_metric(session_id, name) for name in metrics_to_show},
    }


# Outlook rule thresholds -- deliberately the same kind of plain,
# explainable thresholds the Red Flag Agent uses, so a reader can audit
# *why* a company got a given outlook label just by counting flags.
def _outlook_label(num_high: int, num_medium: int) -> tuple:
    if num_high >= 3:
        return "Elevated Risk", (
            f"{num_high} high-severity red flag(s) were identified. Continued "
            "monitoring of debt levels, margins, and liquidity is warranted "
            "before this company's financial trajectory can be considered stable."
        )
    if num_high >= 1 or num_medium >= 3:
        return "Caution", (
            f"{num_high} high-severity and {num_medium} medium-severity red "
            "flag(s) were identified. These are not necessarily severe on "
            "their own, but merit follow-up in subsequent reporting periods."
        )
    if num_medium >= 1:
        return "Generally Stable", (
            f"Only {num_medium} medium-severity red flag(s) and no high-severity "
            "flags were identified. The company's financials show no major "
            "cause for concern based on the information extracted."
        )
    return "Stable", (
        "No red flags were identified by the Red Flag Agent. Based solely on "
        "the metrics and language extracted from the source document, this "
        "company shows no material signs of financial distress."
    )


def generate_outlook_section(session_id: int) -> dict:
    """
    A short, rule-based outlook per company, derived ONLY from:
      - the count of high/medium-severity red flags (Red Flag Agent output)
      - the latest revenue and net margin trend direction (Extraction Agent output)

    This section is intentionally NOT written by an LLM: every other section
    of this report is a direct restatement of a number or flag that another
    agent already grounded in the source text, and Outlook preserves that
    same guarantee by deriving its judgment from a fixed, auditable rule
    table instead of free-form generation. A reader can always reconstruct
    why a company received a given label just from its flag counts below.
    """
    docs = [d for d in db.list_documents(session_id) if d["status"] in
            ("extracted", "red_flags_scanned")]

    outlooks = []
    for doc in docs:
        flags = db.get_red_flags_for_document(doc["id"])
        num_high = sum(1 for f in flags if f["severity"] == "high")
        num_medium = sum(1 for f in flags if f["severity"] == "medium")

        metrics = db.get_metrics_for_document(doc["id"])
        by_name = {}
        for m in metrics:
            by_name.setdefault(m["metric_name"], []).append(m)
        revenue_new, revenue_old = _latest_two(by_name.get("total_revenue", []))

        trend_note = ""
        if revenue_new and revenue_old and revenue_old["metric_value"]:
            pct = (revenue_new["metric_value"] - revenue_old["metric_value"]) / abs(revenue_old["metric_value"]) * 100
            trend_note = f" Revenue trend: {'+' if pct >= 0 else ''}{pct:.1f}% year-over-year."

        label, explanation = _outlook_label(num_high, num_medium)

        outlooks.append({
            "document_id": doc["id"],
            "company_name": doc["company_name"],
            "outlook_label": label,
            "explanation": explanation + trend_note,
            "based_on": {"high_severity_flags": num_high, "medium_severity_flags": num_medium},
        })

    return {"companies": outlooks}


def generate_report_preview(session_id: int) -> dict:
    """Backwards-compatible alias (Milestone 3's two-section preview).
    Kept so any existing caller of the old preview endpoint still works;
    new code should call compile_full_report() instead."""
    return {
        "session_id": session_id,
        "executive_summary": generate_executive_summary(session_id),
        "key_financials": generate_key_financials_section(session_id),
        "note": "This is the legacy 2-section preview. See /report/full for all 5 sections.",
    }


def compile_full_report(session_id: int) -> dict:
    """MILESTONE 4, TASK 1: the complete report -- all five sections."""
    session = db.get_session(session_id)
    docs = [d for d in db.list_documents(session_id) if d["status"] in
            ("extracted", "red_flags_scanned")]

    return {
        "session_id": session_id,
        "session_name": session["name"] if session else None,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "companies_covered": [d["company_name"] for d in docs],
        "executive_summary": generate_executive_summary(session_id),
        "key_financials": generate_key_financials_section(session_id),
        "red_flags": generate_red_flags_section(session_id),
        "comparison": generate_comparison_section(session_id),
        "outlook": generate_outlook_section(session_id),
    }


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def render_pdf(session_id: int, output_path: str) -> str:
    """
    MILESTONE 4, TASK 1: renders compile_full_report() as an actual
    downloadable PDF file at output_path, using reportlab (pure-Python, no
    system dependencies -- important so this installs cleanly for a
    non-technical user on Windows/Mac without extra system libraries).
    Returns output_path on success.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )

    report = compile_full_report(session_id)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=20, spaceAfter=4)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], textColor=colors.grey, spaceAfter=18)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], spaceBefore=18, spaceAfter=8)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=12, spaceAfter=6)
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, textColor=colors.grey)

    severity_color = {"high": colors.HexColor("#C0392B"), "medium": colors.HexColor("#D68910"),
                       "low": colors.HexColor("#7D8A95")}

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc = SimpleDocTemplate(output_path, pagesize=LETTER,
                             topMargin=0.75 * inch, bottomMargin=0.75 * inch,
                             leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    story = []

    # --- Cover / title ---
    story.append(Paragraph("Financial Research Report", title_style))
    story.append(Paragraph(
        f"Session: {report['session_name'] or report['session_id']} &nbsp;|&nbsp; "
        f"Generated: {report['generated_at']} &nbsp;|&nbsp; "
        f"Companies: {', '.join(report['companies_covered']) or 'None'}",
        meta_style,
    ))
    story.append(Paragraph(
        "Every figure and finding in this report was extracted directly from the "
        "uploaded source documents by an automated multi-agent pipeline (Document, "
        "Extraction, Red Flag, and Comparison agents) and is traceable back to its "
        "exact source passage. The Outlook section is rule-based, derived only from "
        "the red-flag counts shown in this report.", body))

    # --- 1. Executive Summary ---
    story.append(Paragraph("1. Executive Summary", h1))
    story.append(Paragraph(report["executive_summary"]["overview"], body))
    for c in report["executive_summary"]["per_company"]:
        story.append(Paragraph(c["company_name"], h2))
        story.append(Paragraph(c["summary_text"], body))

    # --- 2. Key Financials ---
    story.append(PageBreak())
    story.append(Paragraph("2. Key Financials", h1))
    for t in report["key_financials"]["tables"]:
        story.append(Paragraph(t["company_name"], h2))
        if not t["rows"]:
            story.append(Paragraph("No metrics extracted.", body))
            continue
        data = [["Metric", "Latest", "Period", "Prior", "Period"]]
        for r in t["rows"]:
            data.append([r["metric"], str(r["latest_value"]), r["latest_period"],
                         str(r["prior_value"]) if r["prior_value"] is not None else "-",
                         r["prior_period"] or "-"])
        tbl = Table(data, repeatRows=1, colWidths=[1.7*inch, 1.2*inch, 0.7*inch, 1.2*inch, 0.7*inch])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F7")]),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 10))

    # --- 3. Red Flags ---
    story.append(PageBreak())
    story.append(Paragraph("3. Red Flags", h1))
    totals = report["red_flags"]["totals"]
    story.append(Paragraph(
        f"Totals across all companies: {totals['high']} high, {totals['medium']} medium, "
        f"{totals['low']} low severity.", body))
    for c in report["red_flags"]["companies"]:
        story.append(Paragraph(f"{c['company_name']} ({c['num_flags']} flag(s))", h2))
        if not c["flags"]:
            story.append(Paragraph("No red flags detected.", body))
            continue
        for f in c["flags"]:
            style = ParagraphStyle("FlagLine", parent=body, textColor=severity_color[f["severity"]])
            story.append(Paragraph(f"[{f['severity'].upper()}] {f['description']}", style))

    # --- 4. Company Comparison ---
    story.append(PageBreak())
    story.append(Paragraph("4. Company Comparison", h1))
    for metric_name, comp in report["comparison"]["metrics"].items():
        if not comp["rows"]:
            continue
        story.append(Paragraph(metric_name.replace("_", " ").title(), h2))
        data = [["Rank", "Company", "Value", "Period"]]
        for r in comp["rows"]:
            data.append([str(r["rank"]), r["company_name"], f"{r['value']:,.2f}", r["period"]])
        tbl = Table(data, repeatRows=1, colWidths=[0.6*inch, 2.4*inch, 1.5*inch, 0.9*inch])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 8))

    # --- 5. Outlook ---
    story.append(PageBreak())
    story.append(Paragraph("5. Outlook", h1))
    for o in report["outlook"]["companies"]:
        story.append(Paragraph(f"{o['company_name']} \u2014 {o['outlook_label']}", h2))
        story.append(Paragraph(o["explanation"], body))

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "Generated automatically by the Multi-Agent Financial Research System. "
        "This report is for educational/research purposes and is not investment advice.",
        small))

    doc.build(story)
    return output_path
