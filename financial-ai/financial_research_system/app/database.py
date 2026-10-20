"""
database.py
------------
Lightweight SQLite persistence layer for the Multi-Agent Financial Research
System. No ORM is used deliberately -- this keeps the codebase easy to read
and debug for students, and has zero extra dependencies.
"""

import sqlite3
import os
import datetime
from contextlib import contextmanager

from app.paths import DB_PATH


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workspace_id) REFERENCES workspaces (id)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                company_name TEXT,
                source_type TEXT NOT NULL DEFAULT 'upload',
                status TEXT NOT NULL DEFAULT 'pending',
                rejection_reason TEXT,
                classifier_confidence REAL,
                raw_text_path TEXT,
                uploaded_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                char_start INTEGER,
                char_end INTEGER,
                FOREIGN KEY (document_id) REFERENCES documents (id)
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                raw_value TEXT,
                unit TEXT,
                period TEXT,
                source_chunk_id INTEGER,
                extracted_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents (id),
                FOREIGN KEY (source_chunk_id) REFERENCES chunks (id)
            );

            CREATE TABLE IF NOT EXISTS red_flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                flag_type TEXT NOT NULL,
                description TEXT NOT NULL,
                severity TEXT NOT NULL,
                evidence TEXT,
                source_chunk_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents (id),
                FOREIGN KEY (source_chunk_id) REFERENCES chunks (id)
            );

            CREATE TABLE IF NOT EXISTS qa_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                citations_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                stage_name TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms REAL,
                detail TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents (id)
            );
            """
        )
        # Lightweight migration for databases created before rejection_reason/
        # classifier_confidence existed, so upgrading in place doesn't break.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
        if "rejection_reason" not in existing_cols:
            conn.execute("ALTER TABLE documents ADD COLUMN rejection_reason TEXT")
        if "classifier_confidence" not in existing_cols:
            conn.execute("ALTER TABLE documents ADD COLUMN classifier_confidence REAL")


# ---------------------------------------------------------------------------
# Workspace / Session helpers
# ---------------------------------------------------------------------------

def create_workspace(name: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO workspaces (name, created_at) VALUES (?, ?)", (name, _now()))
        return cur.lastrowid


def list_workspaces():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM workspaces ORDER BY id DESC")]


def create_session(workspace_id: int, name: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (workspace_id, name, created_at) VALUES (?, ?, ?)",
            (workspace_id, name, _now()),
        )
        return cur.lastrowid


def list_sessions(workspace_id: int = None):
    with get_conn() as conn:
        if workspace_id:
            rows = conn.execute("SELECT * FROM sessions WHERE workspace_id = ? ORDER BY id DESC", (workspace_id,))
        else:
            rows = conn.execute("SELECT * FROM sessions ORDER BY id DESC")
        return [dict(r) for r in rows]


def get_session(session_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

def create_document(session_id: int, filename: str, source_type: str = "upload",
                     company_name: str = None, raw_text_path: str = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO documents
               (session_id, filename, company_name, source_type, status, raw_text_path, uploaded_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (session_id, filename, company_name, source_type, raw_text_path, _now()),
        )
        return cur.lastrowid


def update_document_status(document_id: int, status: str, company_name: str = None):
    with get_conn() as conn:
        if company_name:
            conn.execute("UPDATE documents SET status = ?, company_name = ? WHERE id = ?",
                         (status, company_name, document_id))
        else:
            conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status, document_id))


def mark_document_rejected(document_id: int, reason: str, confidence: float):
    """Used by the Document Agent's financial-document gate: the document
    was successfully read, but classified as NOT a financial document, so
    it is stopped here and never chunked, indexed, or extracted from."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE documents SET status = 'rejected', rejection_reason = ?,
               classifier_confidence = ? WHERE id = ?""",
            (reason, confidence, document_id),
        )


def get_document(document_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None


def list_documents(session_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM documents WHERE session_id = ? ORDER BY id DESC", (session_id,))
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Chunk helpers
# ---------------------------------------------------------------------------

def insert_chunks(document_id: int, chunks: list):
    with get_conn() as conn:
        ids = []
        for c in chunks:
            cur = conn.execute(
                """INSERT INTO chunks (document_id, chunk_index, text, char_start, char_end)
                   VALUES (?, ?, ?, ?, ?)""",
                (document_id, c["chunk_index"], c["text"], c.get("char_start"), c.get("char_end")),
            )
            ids.append(cur.lastrowid)
        return ids


def get_chunks_for_document(document_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index", (document_id,))
        return [dict(r) for r in rows]


def get_chunks_for_session(session_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT chunks.*, documents.company_name, documents.filename
               FROM chunks JOIN documents ON chunks.document_id = documents.id
               WHERE documents.session_id = ?""",
            (session_id,),
        )
        return [dict(r) for r in rows]


def get_chunk(chunk_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def insert_metrics(document_id: int, metrics: list):
    with get_conn() as conn:
        for m in metrics:
            conn.execute(
                """INSERT INTO metrics
                   (document_id, metric_name, metric_value, raw_value, unit, period, source_chunk_id, extracted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (document_id, m["metric_name"], m.get("metric_value"), m.get("raw_value"),
                 m.get("unit"), m.get("period"), m.get("source_chunk_id"), _now()),
            )


def get_metrics_for_document(document_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM metrics WHERE document_id = ? ORDER BY metric_name, period", (document_id,))
        return [dict(r) for r in rows]


def get_metrics_for_session(session_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT metrics.*, documents.company_name, documents.filename
               FROM metrics JOIN documents ON metrics.document_id = documents.id
               WHERE documents.session_id = ?
               ORDER BY documents.company_name, metrics.metric_name, metrics.period""",
            (session_id,),
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Red flag helpers
# ---------------------------------------------------------------------------

def insert_red_flags(document_id: int, flags: list):
    with get_conn() as conn:
        for f in flags:
            conn.execute(
                """INSERT INTO red_flags
                   (document_id, flag_type, description, severity, evidence, source_chunk_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (document_id, f["flag_type"], f["description"], f["severity"],
                 f.get("evidence"), f.get("source_chunk_id"), _now()),
            )


def get_red_flags_for_document(document_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM red_flags WHERE document_id = ? ORDER BY severity DESC", (document_id,))
        return [dict(r) for r in rows]


def get_red_flags_for_session(session_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT red_flags.*, documents.company_name, documents.filename
               FROM red_flags JOIN documents ON red_flags.document_id = documents.id
               WHERE documents.session_id = ?
               ORDER BY documents.company_name, red_flags.severity DESC""",
            (session_id,),
        )
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# QA log helpers
# ---------------------------------------------------------------------------

def log_qa(session_id: int, question: str, answer: str, citations_json: str):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO qa_log (session_id, question, answer, citations_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, question, answer, citations_json, _now()),
        )
        return cur.lastrowid


def get_qa_history(session_id: int, limit: int = 50):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM qa_log WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, limit))
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pipeline run helpers
# ---------------------------------------------------------------------------

def log_pipeline_stage(document_id: int, stage_name: str, status: str,
                        duration_ms: float, detail: str = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pipeline_runs (document_id, stage_name, status, duration_ms, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (document_id, stage_name, status, duration_ms, detail, _now()),
        )


def get_pipeline_runs(document_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM pipeline_runs WHERE document_id = ? ORDER BY id", (document_id,))
        return [dict(r) for r in rows]
