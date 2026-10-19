"""
paths.py
--------
MILESTONE 4 OPTIMIZATION (reliability/testability): a single shared place
that decides where the system stores its data (database, uploads, vector
indexes, raw text, generated reports).

Why this exists: previously, database.py, vector_store.py, document_agent.py,
seed_loader.py, and main.py each computed their own "data/" path by walking
up from their own file location with os.path.dirname(...). That worked, but
it meant:
  1. There was no single source of truth for "where is the data directory."
  2. The end-to-end test suite (run_tests.py) had no way to point the
     system at a throwaway test directory instead of the person's real
     data/app.db -- running the tests would have mixed test documents into
     their real research sessions.

Setting the FRS_DATA_DIR environment variable before starting the app (or
before importing app.database, in a test) overrides where everything is
stored. run_tests.py uses this to run entirely in a temporary directory
that gets deleted afterward, leaving the person's real data untouched.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.environ.get("FRS_DATA_DIR") or os.path.join(PROJECT_ROOT, "data")

DB_PATH = os.path.join(DATA_DIR, "app.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
RAW_TEXT_DIR = os.path.join(DATA_DIR, "raw_text")
INDEX_DIR = os.path.join(DATA_DIR, "vector_indexes")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")


def ensure_data_dirs():
    for d in (DATA_DIR, UPLOAD_DIR, RAW_TEXT_DIR, INDEX_DIR, REPORTS_DIR):
        os.makedirs(d, exist_ok=True)
