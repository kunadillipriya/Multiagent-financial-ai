"""
run_tests.py
------------
MILESTONE 4, TASK 2: "Conduct end-to-end testing -- validate citation
accuracy, agent collaboration, extraction correctness, and report
completeness."

A non-technical user runs this with:
    python run_tests.py

It exercises the REAL HTTP API (the same endpoints the chat UI calls) end
to end -- not just individual functions in isolation -- against a
throwaway, temporary data directory, so running it never touches or mixes
with the person's real workspaces/sessions/documents. It prints a plain
PASS/FAIL report and exits with code 0 (all passed) or 1 (something
failed), so it can also be wired into a CI pipeline later if needed.

What it checks, mapped directly to the task's four areas:

  AGENT COLLABORATION
    - The orchestration layer successfully runs Document -> Extraction ->
      Red Flag, in order, on all 3 seed documents.
    - The Document Agent's financial-document gate correctly REJECTS a
      non-financial file (so a later agent never sees it).

  EXTRACTION CORRECTNESS
    - The Extraction Agent's output, scored against the hand-verified
      ground truth in app/eval_ground_truth.py, clears a minimum F1 bar.

  CITATION ACCURACY (source faithfulness)
    - Every extracted metric's and every red flag's cited source chunk
      genuinely contains the value/phrase it claims to -- a 100% bar,
      since a single fabricated citation is a correctness bug, not a
      matter of degree.
    - The Research Agent returns at least one citation for a real question.

  REPORT COMPLETENESS
    - The compiled report has all 5 required sections, each non-empty for
      a session with loaded documents.
    - The PDF endpoint produces a real, non-trivial PDF file.
"""

import os
import sys
import shutil
import tempfile

# IMPORTANT: this must happen BEFORE importing anything from `app`, since
# app.paths reads FRS_DATA_DIR at import time to decide where the database,
# uploads, and vector indexes live. Pointing it at a fresh temp directory is
# what makes this test run fully isolated from the person's real data.
TEST_DATA_DIR = tempfile.mkdtemp(prefix="frs_test_")
os.environ["FRS_DATA_DIR"] = TEST_DATA_DIR

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import eval_ground_truth as gt  # noqa: E402

results = []  # (name, passed: bool, detail: str)


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))


def section(title):
    print(f"\n=== {title} ===")


def main():
    print("Multi-Agent Financial Research System -- End-to-End Test Suite")
    print(f"(running against a temporary, isolated data directory: {TEST_DATA_DIR})\n")

    # Using TestClient as a context manager ensures FastAPI's startup event
    # (db.init_db(), which creates all tables) actually runs before any
    # request is made -- without `with`, the startup/lifespan hook is never
    # triggered and every request would fail with "no such table".
    with TestClient(app) as client:
        return _run_all_checks(client)


def _run_all_checks(client):
    # Health check -----------------------------------------------------------
    section("0. System health")
    r = client.get("/health")
    check("API responds to /health", r.status_code == 200 and r.json().get("status") == "ok")

    # Setup: workspace + session ----------------------------------------------
    r = client.post("/workspaces", json={"name": "Test Workspace"})
    check("Create workspace", r.status_code == 200)
    workspace_id = r.json()["id"]

    r = client.post(f"/workspaces/{workspace_id}/sessions", json={"name": "Test Session"})
    check("Create session", r.status_code == 200)
    session_id = r.json()["id"]

    # --- AGENT COLLABORATION: full pipeline on all 3 seed documents --------
    section("1. Agent collaboration (orchestrated pipeline on seed documents)")
    r = client.post(f"/sessions/{session_id}/load-seed-documents")
    check("Seed-load request succeeds", r.status_code == 200)
    loaded = r.json().get("loaded", [])
    check("All 3 seed documents loaded", len(loaded) == 3, f"got {len(loaded)}")

    doc_by_company = {}
    for item in loaded:
        final_status = item.get("final_status")
        filename = item.get("filename", "?")
        check(f"Pipeline completed OK for {filename}", final_status == "ok",
              f"final_status={final_status}")
        steps = item.get("steps", {})
        check(f"  Document Agent ran for {filename}", steps.get("document_agent", {}).get("status") == "ok")
        check(f"  Extraction Agent ran for {filename}", "extraction_agent" in steps)
        check(f"  Red Flag Agent ran for {filename}", "red_flag_agent" in steps)
        if "document_id" in item:
            doc_by_company[item["document_id"]] = filename

    # --- AGENT COLLABORATION: financial-document gate rejects junk ---------
    section("2. Document Agent gate rejects non-financial uploads")
    non_financial_text = (
        "Grandma's Chocolate Chip Cookies\n\n"
        "Ingredients: 2 cups flour, 1 cup sugar, 2 eggs, 1 cup chocolate chips.\n"
        "Instructions: Preheat oven to 350F. Mix ingredients. Bake for 12 minutes.\n"
        "Enjoy with a glass of milk!"
    )
    r = client.post(
        f"/sessions/{session_id}/documents/upload",
        files={"file": ("cookie_recipe.txt", non_financial_text, "text/plain")},
    )
    check("Non-financial upload is rejected (HTTP 422)", r.status_code == 422,
          f"got HTTP {r.status_code}: {r.text[:200]}")

    # --- EXTRACTION CORRECTNESS ----------------------------------------------
    section("3. Extraction correctness (vs. hand-verified ground truth)")
    r = client.get(f"/sessions/{session_id}/evaluate")
    check("Evaluation endpoint responds", r.status_code == 200)
    eval_report = r.json()

    ea = eval_report.get("extraction_accuracy", {})
    MIN_EXTRACTION_F1 = 0.85
    check(
        f"Extraction Agent overall F1 >= {MIN_EXTRACTION_F1}",
        (ea.get("overall_f1") or 0) >= MIN_EXTRACTION_F1,
        f"got {ea.get('overall_f1')}",
    )
    check(
        "Extraction Agent overall recall == 1.0 (finds everything that's really there)",
        ea.get("overall_recall") == 1.0,
        f"got {ea.get('overall_recall')}",
    )

    ra = eval_report.get("red_flag_accuracy", {})
    MIN_REDFLAG_F1 = 0.85
    check(
        f"Red Flag Agent overall F1 >= {MIN_REDFLAG_F1}",
        (ra.get("overall_f1") or 0) >= MIN_REDFLAG_F1,
        f"got {ra.get('overall_f1')}",
    )

    # --- CITATION ACCURACY / SOURCE FAITHFULNESS -----------------------------
    section("4. Citation accuracy (source faithfulness)")
    ef = eval_report.get("extraction_faithfulness", {})
    check(
        "Every extracted metric's citation is faithful to its source chunk (100%)",
        ef.get("faithfulness_rate") == 1.0,
        f"got {ef.get('faithfulness_rate')}, violations: {ef.get('violations')}",
    )
    rff = eval_report.get("red_flag_faithfulness", {})
    check(
        "Every red flag's citation is faithful to its source chunk (100%)",
        rff.get("faithfulness_rate") == 1.0,
        f"got {rff.get('faithfulness_rate')}, violations: {rff.get('violations')}",
    )

    r = client.post(
        f"/sessions/{session_id}/ask",
        json={"question": "What was Aurora's revenue and does Meridian have debt concerns?"},
    )
    check("Research Agent answers a multi-part question (HTTP 200)", r.status_code == 200)
    ask_result = r.json() if r.status_code == 200 else {}
    check("Research Agent answer is non-empty", bool(ask_result.get("answer", "").strip()))
    check("Research Agent cites at least one source", len(ask_result.get("citations", [])) >= 1)
    check("Research Agent correctly split the question into 2+ steps",
          ask_result.get("num_steps", 0) >= 2, f"got {ask_result.get('num_steps')}")

    # --- Comparison Agent sanity check ---------------------------------------
    section("5. Comparison Agent")
    r = client.get(f"/sessions/{session_id}/compare/total_revenue")
    check("Comparison endpoint responds", r.status_code == 200)
    comp = r.json() if r.status_code == 200 else {}
    check("Comparison correctly ranks Nova Foods #1 by revenue (largest company)",
          comp.get("leader") == "Nova Foods Corporation", f"got leader={comp.get('leader')}")

    # --- REPORT COMPLETENESS --------------------------------------------------
    section("6. Report completeness")
    r = client.get(f"/sessions/{session_id}/report/full")
    check("Full report endpoint responds", r.status_code == 200)
    report = r.json() if r.status_code == 200 else {}

    required_sections = ["executive_summary", "key_financials", "red_flags", "comparison", "outlook"]
    for sec in required_sections:
        present = sec in report and bool(report[sec])
        check(f"Report has non-empty '{sec}' section", present)

    check("Report covers all 3 companies",
          len(report.get("companies_covered", [])) == 3,
          f"got {report.get('companies_covered')}")

    r = client.get(f"/sessions/{session_id}/report/pdf")
    check("PDF report endpoint responds (HTTP 200)", r.status_code == 200)
    pdf_bytes = r.content if r.status_code == 200 else b""
    check("PDF file is non-trivial in size (> 3 KB)", len(pdf_bytes) > 3000,
          f"got {len(pdf_bytes)} bytes")
    check("PDF starts with a valid PDF header", pdf_bytes[:4] == b"%PDF")

    # --- Summary --------------------------------------------------------------
    section("SUMMARY")
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print(f"  {passed}/{total} checks passed.")
    if failed:
        print(f"\n  {failed} check(s) FAILED:")
        for name, ok, detail in results:
            if not ok:
                print(f"    - {name}" + (f" ({detail})" if detail else ""))
    else:
        print("  All checks passed. ✅")

    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
