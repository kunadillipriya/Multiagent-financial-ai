"""
orchestrator.py
----------------
MILESTONE 3, TASK 2: Multi-agent orchestration layer.

Coordinates the Document, Extraction, and Red Flag agents SEQUENTIALLY on
every document upload (or seed-load), in this fixed order:

    Document Agent -> Extraction Agent -> Red Flag Agent

This is deterministic, scripted orchestration (not an LLM deciding what to
call next) -- appropriate here because the workflow never changes: every
document needs to be parsed/indexed, then have metrics pulled, then be
scanned for red flags, always in that order, always all three.

### The financial-document gate stops the pipeline early
The Document Agent's financial-document classifier (document_classifier.py)
runs as part of step 1. If a document fails that check, process_document()
raises NotFinancialDocumentError -- this orchestrator catches that
specifically and stops immediately: it does NOT run the Extraction Agent or
Red Flag Agent on a rejected document, because there would be no financial
content for them to work on. The document is left in the database with
status 'rejected' and a human-readable reason (see database.py
mark_document_rejected), which the API and chat UI surface to the person.

### Failure handling
Each stage's success/failure and timing is logged to the `pipeline_runs`
table (see database.py) for visibility. If the Document Agent itself fails
for a reason OTHER than "not a financial document" (e.g. an unreadable
file), the pipeline stops there too, since there is nothing for the later
agents to work on. If the Extraction Agent succeeds but the Red Flag Agent
fails, extraction results are kept and the failure is reported rather than
losing everything.
"""

import time

from app import database as db
from app.agents import document_agent, extraction_agent, red_flag_agent
from app.agents.document_agent import NotFinancialDocumentError


def _timed_stage(document_id: int, stage_name: str, fn, *args, **kwargs):
    start = time.time()
    try:
        result = fn(*args, **kwargs)
        duration_ms = (time.time() - start) * 1000
        db.log_pipeline_stage(document_id, stage_name, "success", duration_ms)
        return {"status": "ok", "duration_ms": round(duration_ms, 1), **(result or {})}
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        db.log_pipeline_stage(document_id, stage_name, "failed", duration_ms, detail=str(e))
        raise


def run_pipeline(document_id: int, session_id: int, file_path: str, filename: str) -> dict:
    """
    Runs the full Document -> Extraction -> Red Flag pipeline for one
    document. Returns a summary dict with a 'steps' breakdown and an overall
    'final_status'. Does not raise for a rejected (non-financial) document --
    that is a normal, expected outcome -- but DOES raise for genuine
    technical failures (unreadable file, etc.) so the API layer can return
    an appropriate error.
    """
    steps = {}

    # --- Stage 1: Document Agent (includes the financial-document gate) ---
    try:
        doc_result = _timed_stage(
            document_id, "document_agent",
            document_agent.process_document, document_id, session_id, file_path, filename,
        )
        steps["document_agent"] = doc_result
    except NotFinancialDocumentError as e:
        # Expected, handled outcome: stop the pipeline here. Nothing else
        # runs on a document that isn't a financial document.
        steps["document_agent"] = {
            "status": "rejected",
            "reason": e.classification["reason"],
            "confidence": e.classification["confidence"],
        }
        return {
            "document_id": document_id,
            "final_status": "rejected_not_financial",
            "steps": steps,
        }
    except Exception as e:
        # Genuine technical failure (bad file, zero extractable text, etc.)
        steps["document_agent"] = {"status": "failed", "error": str(e)}
        return {
            "document_id": document_id,
            "final_status": "failed",
            "steps": steps,
        }

    # --- Stage 2: Extraction Agent ------------------------------------------
    try:
        extraction_result = _timed_stage(
            document_id, "extraction_agent", extraction_agent.run_extraction, document_id,
        )
        steps["extraction_agent"] = extraction_result
    except Exception as e:
        steps["extraction_agent"] = {"status": "failed", "error": str(e)}
        return {
            "document_id": document_id,
            "final_status": "extraction_failed",
            "steps": steps,
        }

    # --- Stage 3: Red Flag Agent --------------------------------------------
    try:
        red_flag_result = _timed_stage(
            document_id, "red_flag_agent", red_flag_agent.run_red_flag_scan, document_id,
        )
        steps["red_flag_agent"] = red_flag_result
    except Exception as e:
        steps["red_flag_agent"] = {"status": "failed", "error": str(e)}
        return {
            "document_id": document_id,
            "final_status": "red_flag_scan_failed",
            "steps": steps,
        }

    return {
        "document_id": document_id,
        "final_status": "ok",
        "steps": steps,
    }
