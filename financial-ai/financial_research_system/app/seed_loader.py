"""
seed_loader.py
--------------
Loads the pre-bundled seed company documents into a research session,
running each one through the full orchestrated pipeline (Document ->
Extraction -> Red Flag), exactly like a real user upload would.
"""

import os
import shutil

from app import database as db
from app import orchestrator
from app.paths import UPLOAD_DIR

SEED_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "seed_documents")


def list_seed_files():
    if not os.path.isdir(SEED_DIR):
        return []
    return sorted(f for f in os.listdir(SEED_DIR) if f.lower().endswith((".txt", ".pdf", ".docx")))


def load_seed_documents_into_session(session_id: int) -> list:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    results = []

    for filename in list_seed_files():
        src_path = os.path.join(SEED_DIR, filename)
        document_id = db.create_document(session_id, filename, source_type="seed")

        dest_path = os.path.join(UPLOAD_DIR, f"doc_{document_id}_{filename}")
        shutil.copyfile(src_path, dest_path)

        result = orchestrator.run_pipeline(document_id, session_id, dest_path, filename)
        result["filename"] = filename
        results.append(result)

    return results
