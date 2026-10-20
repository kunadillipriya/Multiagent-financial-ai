"""
comparison_agent.py
--------------------
AGENT 4: Comparison Agent

Cross-references extracted financial data across every document in a
session for side-by-side benchmarking. Reads only from the `metrics` table
(already populated by the Extraction Agent) -- it does no parsing of its
own, so every number it compares is already traceable back to a source
chunk via the metrics row it came from.
"""

from app import database as db


def compare_metric(session_id: int, metric_name: str) -> dict:
    """
    Ranks every company in the session on one metric, using each company's
    most recent period for that metric. Returns a ranked list plus the
    'leader' (highest value) and 'laggard' (lowest value).
    """
    rows = db.get_metrics_for_session(session_id)
    rows = [r for r in rows if r["metric_name"] == metric_name and r["metric_value"] is not None]

    # Keep only each company's most recent period for this metric.
    latest_by_company = {}
    for r in rows:
        key = r["company_name"]
        if key not in latest_by_company or r["period"] > latest_by_company[key]["period"]:
            latest_by_company[key] = r

    ranked = sorted(latest_by_company.values(), key=lambda r: r["metric_value"], reverse=True)

    if not ranked:
        return {"metric_name": metric_name, "rows": [], "leader": None, "laggard": None}

    return {
        "metric_name": metric_name,
        "rows": [
            {
                "rank": i + 1,
                "company_name": r["company_name"],
                "value": r["metric_value"],
                "period": r["period"],
                "source_document_id": r["document_id"],
                "source_chunk_id": r["source_chunk_id"],
            }
            for i, r in enumerate(ranked)
        ],
        "leader": ranked[0]["company_name"],
        "laggard": ranked[-1]["company_name"],
    }


def compare_all_metrics(session_id: int) -> dict:
    """Runs compare_metric() for every distinct metric name present in the
    session -- this is the full benchmark table the chat UI's Compare tab
    renders."""
    rows = db.get_metrics_for_session(session_id)
    metric_names = sorted(set(r["metric_name"] for r in rows))
    return {
        "session_id": session_id,
        "metrics": {name: compare_metric(session_id, name) for name in metric_names},
    }
