"""
evaluation.py
--------------
MILESTONE 3, TASK 3: "Test and validate agent outputs on seed financial
documents for accuracy and source faithfulness."

Answers two questions for every seed-loaded document:

  1. ACCURACY -- did the Extraction Agent and Red Flag Agent find the right
     things? Scored against app/eval_ground_truth.py as precision/recall/F1.
  2. SOURCE FAITHFULNESS -- for every metric and every red flag produced, is
     its cited source_chunk_id real, and does that chunk's text actually
     contain the value/phrase being cited? This is what catches an agent
     "hallucinating" a plausible-looking number not actually in the source.

Exposed via GET /sessions/{id}/evaluate in app/main.py.
"""

import re

from app import database as db
from app import eval_ground_truth as gt


def _collapse_whitespace(s: str) -> str:
    """Normalizes all whitespace (spaces, newlines, tabs) to nothing, so two
    strings that differ only in where a line happens to wrap compare equal.
    Used by the faithfulness checks below -- both sides of a substring
    comparison MUST go through this same function, or a snippet that wraps
    a line differently than the chunk text it came from will wrongly read
    as "not found" even though it's a verbatim excerpt."""
    return re.sub(r"\s+", "", s)

_TOLERANCE_PCT = 0.01  # 1% relative tolerance, absorbs float rounding only


def _values_match(expected: float, actual: float) -> bool:
    if expected == 0:
        return abs(actual) < 1e-6
    return abs(actual - expected) / abs(expected) <= _TOLERANCE_PCT


def evaluate_extraction_accuracy(session_id: int) -> dict:
    documents = db.list_documents(session_id)
    per_document = []
    total_tp = total_fp = total_fn = 0

    for doc in documents:
        gt_key = gt.match_company_key(doc.get("company_name") or doc.get("filename", ""))
        if not gt_key:
            continue

        expected = gt.GROUND_TRUTH_METRICS[gt_key]
        extracted = db.get_metrics_for_document(doc["id"])
        extracted_by_key = {(m["metric_name"], m["period"]): m["metric_value"] for m in extracted}

        tp, fp, fn = 0, 0, 0
        mismatches = []
        expected_keys = {(name, period) for name, periods in expected.items() for period in periods}

        for name, period in expected_keys:
            exp_value = expected[name][period]
            if (name, period) in extracted_by_key:
                if _values_match(exp_value, extracted_by_key[(name, period)]):
                    tp += 1
                else:
                    fp += 1
                    fn += 1
                    mismatches.append({"metric": name, "period": period,
                                        "expected": exp_value, "got": extracted_by_key[(name, period)]})
            else:
                fn += 1
                mismatches.append({"metric": name, "period": period, "expected": exp_value, "got": None})

        for (name, period) in extracted_by_key:
            if (name, period) not in expected_keys:
                fp += 1
                mismatches.append({"metric": name, "period": period, "expected": None,
                                    "got": extracted_by_key[(name, period)], "note": "unexpected extra extraction"})

        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) else None

        per_document.append({
            "document_id": doc["id"], "company_name": doc["company_name"],
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
            "mismatches": mismatches,
        })
        total_tp += tp
        total_fp += fp
        total_fn += fn

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else None
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else None
    overall_f1 = (2 * overall_precision * overall_recall / (overall_precision + overall_recall)
                  if overall_precision and overall_recall and (overall_precision + overall_recall) else None)

    return {
        "metric_type": "extraction_accuracy",
        "documents_scored": len(per_document),
        "overall_precision": round(overall_precision, 4) if overall_precision is not None else None,
        "overall_recall": round(overall_recall, 4) if overall_recall is not None else None,
        "overall_f1": round(overall_f1, 4) if overall_f1 is not None else None,
        "per_document": per_document,
    }


def evaluate_red_flag_accuracy(session_id: int) -> dict:
    documents = db.list_documents(session_id)
    per_document = []
    total_tp = total_fp = total_fn = 0

    for doc in documents:
        gt_key = gt.match_company_key(doc.get("company_name") or doc.get("filename", ""))
        if not gt_key:
            continue

        expected_types = gt.GROUND_TRUTH_RED_FLAGS[gt_key]
        detected_types = {f["flag_type"] for f in db.get_red_flags_for_document(doc["id"])}

        tp = len(expected_types & detected_types)
        fp = len(detected_types - expected_types)
        fn = len(expected_types - detected_types)

        precision = tp / (tp + fp) if (tp + fp) else (1.0 if not expected_types else None)
        recall = tp / (tp + fn) if (tp + fn) else (1.0 if not detected_types else None)
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) else None

        per_document.append({
            "document_id": doc["id"], "company_name": doc["company_name"],
            "expected_flag_types": sorted(expected_types),
            "detected_flag_types": sorted(detected_types),
            "missed": sorted(expected_types - detected_types),
            "unexpected": sorted(detected_types - expected_types),
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": round(f1, 4) if f1 is not None else None,
        })
        total_tp += tp
        total_fp += fp
        total_fn += fn

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else None
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else None
    overall_f1 = (2 * overall_precision * overall_recall / (overall_precision + overall_recall)
                  if overall_precision and overall_recall and (overall_precision + overall_recall) else None)

    return {
        "metric_type": "red_flag_accuracy",
        "documents_scored": len(per_document),
        "overall_precision": round(overall_precision, 4) if overall_precision is not None else None,
        "overall_recall": round(overall_recall, 4) if overall_recall is not None else None,
        "overall_f1": round(overall_f1, 4) if overall_f1 is not None else None,
        "per_document": per_document,
    }


def evaluate_extraction_faithfulness(session_id: int) -> dict:
    documents = db.list_documents(session_id)
    checked, faithful, violations = 0, 0, []

    for doc in documents:
        for m in db.get_metrics_for_document(doc["id"]):
            checked += 1
            chunk = db.get_chunk(m["source_chunk_id"]) if m["source_chunk_id"] else None
            if chunk and m["raw_value"] and _collapse_whitespace(m["raw_value"].split()[0]) in _collapse_whitespace(chunk["text"]):
                faithful += 1
            else:
                violations.append({"document_id": doc["id"], "company_name": doc["company_name"],
                                    "metric_name": m["metric_name"], "period": m["period"],
                                    "raw_value": m["raw_value"], "source_chunk_id": m["source_chunk_id"]})

    return {
        "metric_type": "extraction_citation_faithfulness",
        "citations_checked": checked, "faithful": faithful,
        "faithfulness_rate": round(faithful / checked, 4) if checked else None,
        "violations": violations,
    }


def evaluate_red_flag_faithfulness(session_id: int) -> dict:
    documents = db.list_documents(session_id)
    checked, faithful, violations = 0, 0, []

    for doc in documents:
        for f in db.get_red_flags_for_document(doc["id"]):
            checked += 1
            chunk = db.get_chunk(f["source_chunk_id"]) if f["source_chunk_id"] else None
            ok = False
            if chunk and chunk["document_id"] == doc["id"]:
                if 'flagged: "...' in f["description"]:
                    snippet = f["description"].split('flagged: "...', 1)[1].rsplit('..."', 1)[0]
                    # MILESTONE 4 FIX (found by run_tests.py): the old check
                    # normalized the chunk side's newlines to spaces-then-
                    # removed but left the snippet side's embedded newline
                    # untouched, so a perfectly real, verbatim-quoted
                    # citation that happened to straddle a line wrap in the
                    # source text was wrongly reported as unfaithful. Both
                    # sides now go through the exact same normalization.
                    ok = snippet.strip() != "" and _collapse_whitespace(snippet) in _collapse_whitespace(chunk["text"])
                else:
                    ok = True  # numeric-pass flag: chunk exists and belongs to the right document
            if ok:
                faithful += 1
            else:
                violations.append({"document_id": doc["id"], "company_name": doc["company_name"],
                                    "flag_type": f["flag_type"], "source_chunk_id": f["source_chunk_id"]})

    return {
        "metric_type": "red_flag_citation_faithfulness",
        "citations_checked": checked, "faithful": faithful,
        "faithfulness_rate": round(faithful / checked, 4) if checked else None,
        "violations": violations,
    }


def run_full_evaluation(session_id: int) -> dict:
    return {
        "session_id": session_id,
        "extraction_accuracy": evaluate_extraction_accuracy(session_id),
        "red_flag_accuracy": evaluate_red_flag_accuracy(session_id),
        "extraction_faithfulness": evaluate_extraction_faithfulness(session_id),
        "red_flag_faithfulness": evaluate_red_flag_faithfulness(session_id),
        "note": (
            "Accuracy scores only cover documents matched to a known seed "
            "company (Aurora/Nova/Meridian) since those are the only ones "
            "with a hand-verified ground truth. Faithfulness scores apply "
            "to every document in the session, seed or user-uploaded."
        ),
    }
