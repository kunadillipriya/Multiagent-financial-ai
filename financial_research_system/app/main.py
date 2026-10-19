"""
main.py
-------
FastAPI application tying together Milestones 2 and 3:

  Milestone 2: workspaces/sessions, Document Agent, Extraction Agent
  Milestone 3: Red Flag Agent, multi-agent orchestration layer, Comparison
               Agent, Research Agent, chat UI, Report Agent preview,
               evaluation harness -- plus the financial-document gate added
               to the Document Agent.

Run with:  python run.py
Then open: http://127.0.0.1:8000/        (chat UI)
           http://127.0.0.1:8000/docs    (API playground, all endpoints)
"""

import os
import shutil

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app import database as db
from app import schemas
from app import orchestrator
from app import seed_loader
from app import evaluation
from app.agents import comparison_agent, research_agent, report_agent
from app.paths import UPLOAD_DIR, REPORTS_DIR, ensure_data_dirs
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

app = FastAPI(
    title="Multi-Agent Financial Research System",
    description="Milestones 2 & 3: full agent pipeline, orchestration, chat UI, evaluation.",
    version="0.3.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def on_startup():
    ensure_data_dirs()
    db.init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def serve_chat_ui():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Chat UI not found")
    return FileResponse(index_path)


# ---------------------------------------------------------------------------
# Workspace / Session management
# ---------------------------------------------------------------------------

@app.post("/workspaces")
def create_workspace(payload: schemas.WorkspaceCreate):
    workspace_id = db.create_workspace(payload.name)
    return {"id": workspace_id, "name": payload.name}


@app.get("/workspaces")
def list_workspaces():
    return db.list_workspaces()


@app.post("/workspaces/{workspace_id}/sessions")
def create_session(workspace_id: int, payload: schemas.SessionCreate):
    session_id = db.create_session(workspace_id, payload.name)
    return {"id": session_id, "workspace_id": workspace_id, "name": payload.name}


@app.get("/workspaces/{workspace_id}/sessions")
def list_sessions_in_workspace(workspace_id: int):
    return db.list_sessions(workspace_id)


@app.get("/sessions/{session_id}")
def get_session(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session["documents"] = db.list_documents(session_id)
    return session


# ---------------------------------------------------------------------------
# Seed documents
# ---------------------------------------------------------------------------

@app.get("/seed-documents")
def get_seed_document_list():
    return {"available_seed_documents": seed_loader.list_seed_files()}


@app.post("/sessions/{session_id}/load-seed-documents")
def load_seed_documents(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    results = seed_loader.load_seed_documents_into_session(session_id)
    return {"session_id": session_id, "loaded": results}


# ---------------------------------------------------------------------------
# Document upload -> orchestrated pipeline (Document -> Extraction -> Red Flag)
# ---------------------------------------------------------------------------

@app.post("/sessions/{session_id}/documents/upload")
async def upload_document(session_id: int, file: UploadFile = File(...)):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    allowed_ext = (".txt", ".pdf", ".docx")
    if not file.filename.lower().endswith(allowed_ext):
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(allowed_ext)}")

    document_id = db.create_document(session_id, file.filename, source_type="upload")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    dest_path = os.path.join(UPLOAD_DIR, f"doc_{document_id}_{file.filename}")
    with open(dest_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    result = orchestrator.run_pipeline(document_id, session_id, dest_path, file.filename)

    if result["final_status"] == "rejected_not_financial":
        # Not a server error -- a clear, expected business-rule rejection.
        # 422 Unprocessable Entity: the file was read fine, but its content
        # isn't what this endpoint accepts.
        raise HTTPException(status_code=422, detail={
            "message": "This document was not recognized as a financial document and was not processed.",
            "reason": result["steps"]["document_agent"]["reason"],
            "confidence": result["steps"]["document_agent"]["confidence"],
        })

    if result["final_status"] == "failed":
        raise HTTPException(status_code=422, detail=result["steps"]["document_agent"].get("error", "Processing failed."))

    return {"document": db.get_document(document_id), "pipeline_result": result}


@app.get("/sessions/{session_id}/documents")
def list_documents(session_id: int):
    return db.list_documents(session_id)


@app.get("/documents/{document_id}")
def get_document(document_id: int):
    doc = db.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.get("/documents/{document_id}/chunks")
def get_document_chunks(document_id: int):
    doc = db.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return db.get_chunks_for_document(document_id)


@app.get("/documents/{document_id}/metrics")
def get_document_metrics(document_id: int):
    doc = db.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return db.get_metrics_for_document(document_id)


@app.get("/documents/{document_id}/red-flags")
def get_document_red_flags(document_id: int):
    doc = db.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return db.get_red_flags_for_document(document_id)


@app.get("/documents/{document_id}/pipeline-runs")
def get_document_pipeline_runs(document_id: int):
    doc = db.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return db.get_pipeline_runs(document_id)


@app.get("/sessions/{session_id}/metrics")
def get_session_metrics(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return db.get_metrics_for_session(session_id)


@app.get("/sessions/{session_id}/red-flags")
def get_session_red_flags(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return db.get_red_flags_for_session(session_id)


# ---------------------------------------------------------------------------
# Semantic search (preview of Research Agent retrieval)
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/search")
def search_session(session_id: int, q: str, top_k: int = 5):
    from app.vector_store import get_index
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    index = get_index(session_id)
    results = index.search(q, top_k=top_k)

    output = []
    for chunk_id, score, text in results:
        chunk = db.get_chunk(chunk_id)
        doc = db.get_document(chunk["document_id"]) if chunk else None
        output.append({
            "chunk_id": chunk_id, "score": round(score, 4), "text": text,
            "document_id": chunk["document_id"] if chunk else None,
            "company_name": doc["company_name"] if doc else None,
            "filename": doc["filename"] if doc else None,
        })
    return {"query": q, "results": output}


# ---------------------------------------------------------------------------
# Comparison Agent
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/compare/{metric_name}")
def compare_metric(session_id: int, metric_name: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return comparison_agent.compare_metric(session_id, metric_name)


@app.get("/sessions/{session_id}/compare-all")
def compare_all(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return comparison_agent.compare_all_metrics(session_id)


# ---------------------------------------------------------------------------
# Research Agent
# ---------------------------------------------------------------------------

@app.post("/sessions/{session_id}/ask")
def ask_question(session_id: int, payload: schemas.AskRequest):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return research_agent.answer_question(session_id, payload.question)


@app.get("/sessions/{session_id}/qa-history")
def qa_history(session_id: int):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return db.get_qa_history(session_id)


# ---------------------------------------------------------------------------
# Report Agent
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/report/preview")
def report_preview(session_id: int):
    """Legacy 2-section preview (Executive Summary + Key Financials). Kept
    for backwards compatibility -- use /report/full for the complete report."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return report_agent.generate_report_preview(session_id)


@app.get("/sessions/{session_id}/report/full")
def report_full(session_id: int):
    """MILESTONE 4, TASK 1: the complete structured report as JSON -- all
    five sections (Executive Summary, Key Financials, Red Flags, Company
    Comparison, Outlook). This is what the PDF in /report/pdf is rendered
    from, so the two always match."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return report_agent.compile_full_report(session_id)


@app.get("/sessions/{session_id}/report/pdf")
def report_pdf(session_id: int):
    """MILESTONE 4, TASK 1: renders the full report as a downloadable PDF."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    os.makedirs(REPORTS_DIR, exist_ok=True)
    output_path = os.path.join(REPORTS_DIR, f"report_session_{session_id}.pdf")

    try:
        report_agent.render_pdf(session_id, output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate PDF: {e}")

    safe_name = (session["name"] or "report").replace(" ", "_")
    return FileResponse(
        output_path, media_type="application/pdf",
        filename=f"financial_research_report_{safe_name}.pdf",
    )


# ---------------------------------------------------------------------------
# Evaluation harness
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/evaluate")
def evaluate_session(session_id: int):
    """
    Milestone 3, Task 3: runs the evaluation harness against this session's
    documents -- accuracy (precision/recall/F1) for Extraction and Red Flag
    agents against hand-verified ground truth (seed companies only), plus
    source-faithfulness checks that apply to every document in the session.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return evaluation.run_full_evaluation(session_id)
