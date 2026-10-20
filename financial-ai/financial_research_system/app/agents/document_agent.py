"""
document_agent.py
------------------
AGENT 1: Document Agent

Responsibility: handles document upload, parsing, a financial-document
check (see below), chunking, embedding generation, and vector database
indexing.

Pipeline for one document:
  1. parse_file()            -> raw text, regardless of source format
  2. classify_document()     -> GATE: is this actually a financial document?
                                 If not, STOP here -- nothing below this
                                 line runs, and no chunks are ever created.
  3. guess_company_name()    -> best-effort company name for display/filtering
  4. chunk_text()             -> overlapping text windows (paragraph-aware)
  5. index_chunks()           -> writes chunks to SQLite + adds them to the
                                 session's TF-IDF vector index

### Why the financial-document check matters
Without step 2, this agent would parse and index ANY readable file -- a
recipe, a resume, a novel chapter -- because nothing about parsing text
requires the text to be about finance. Step 2 is a hard gate: a document
that fails it is marked "rejected" in the database and the pipeline stops
immediately, so a non-financial upload never reaches the vector index, the
Extraction Agent, or the Red Flag Agent. See document_classifier.py for how
the check itself works.
"""

import os
import re

from app import database as db
from app.vector_store import get_index
from app.agents.document_classifier import classify_document

from app.paths import RAW_TEXT_DIR

CHUNK_SIZE_CHARS = 1200
CHUNK_OVERLAP_CHARS = 200


class NotFinancialDocumentError(ValueError):
    """Raised when a document is successfully read but fails the
    financial-document classifier. Carries the classifier's full result so
    the API layer can show the person exactly why it was rejected."""

    def __init__(self, classification: dict):
        self.classification = classification
        super().__init__(classification["reason"])


# ---------------------------------------------------------------------------
# 1. Parsing
# ---------------------------------------------------------------------------

def parse_file(file_path: str, original_filename: str) -> str:
    """Extracts raw text from an uploaded file. Supports .txt, .pdf, .docx."""
    ext = original_filename.lower().rsplit(".", 1)[-1] if "." in original_filename else "txt"

    if ext == "txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    elif ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)

    elif ext == "docx":
        import docx
        d = docx.Document(file_path)
        return "\n".join(p.text for p in d.paragraphs)

    else:
        raise ValueError(f"Unsupported file type '.{ext}'. Supported types: .txt, .pdf, .docx")


# MILESTONE 4 OPTIMIZATION (orchestration reliability across varied formats):
# Real-world PDFs -- unlike the clean seed .txt files -- frequently extract
# with artifacts that break both the classifier's phrase matching and the
# Extraction Agent's "Label: value (period)" pattern: runs of multiple
# spaces, a hyphen + line-break splitting one word in two ("reve-\nnue"),
# and stray blank lines. This normalization pass runs on EVERY parsed
# document (seed .txt files pass through it unchanged, since they're
# already clean) so downstream steps see consistently clean text regardless
# of source format.
def normalize_text(text: str) -> str:
    # Rejoin a word that was hyphenated across a line break by a PDF renderer.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Collapse runs of spaces/tabs (but not newlines, which carry paragraph
    # structure that chunk_text() relies on) into a single space.
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Collapse 3+ blank lines down to one blank line.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def guess_company_name(text: str, fallback_filename: str) -> str:
    """Best-effort company name from the first lines of the document."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    for line in lines[:5]:
        letters = [c for c in line if c.isalpha()]
        if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.8:
            if 3 <= len(line) <= 80:
                return line.title()
    return fallback_filename.rsplit(".", 1)[0].replace("_", " ")


# ---------------------------------------------------------------------------
# 2. Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_CHARS,
               overlap: int = CHUNK_OVERLAP_CHARS) -> list:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []

    chunks = []
    start = 0
    idx = 0
    n = len(text)

    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            break_point = text.rfind("\n\n", start, end)
            if break_point == -1 or break_point <= start:
                break_point = text.rfind(". ", start, end)
            if break_point != -1 and break_point > start:
                end = break_point + 1

        chunk_text_value = text[start:end].strip()
        if chunk_text_value:
            chunks.append({"chunk_index": idx, "text": chunk_text_value,
                            "char_start": start, "char_end": end})
            idx += 1

        if end >= n:
            break
        start = max(end - overlap, start + 1)

    return chunks


# ---------------------------------------------------------------------------
# 3. Full pipeline entry point
# ---------------------------------------------------------------------------

def process_document(document_id: int, session_id: int, file_path: str,
                      original_filename: str) -> dict:
    """
    Runs parse -> financial-document gate -> chunk -> store -> vector-index
    for one document. Raises NotFinancialDocumentError (a ValueError
    subclass) if the document fails the financial-document check -- callers
    should catch this the same way they already catch ValueError for
    "no extractable text" / "zero chunks" failures.
    """
    db.update_document_status(document_id, "parsing")

    text = parse_file(file_path, original_filename)
    if not text or not text.strip():
        db.update_document_status(document_id, "failed")
        raise ValueError("No extractable text found in document.")
    text = normalize_text(text)

    # --- Financial-document gate -------------------------------------------
    # This MUST run before any chunking/indexing/extraction. A document that
    # fails here is marked 'rejected' and the function returns immediately --
    # nothing downstream (Extraction Agent, Red Flag Agent, vector index)
    # ever sees it.
    classification = classify_document(text)
    if not classification["is_financial"]:
        db.mark_document_rejected(
            document_id,
            reason=classification["reason"],
            confidence=classification["confidence"],
        )
        raise NotFinancialDocumentError(classification)

    company_name = guess_company_name(text, original_filename)

    os.makedirs(RAW_TEXT_DIR, exist_ok=True)
    raw_text_path = os.path.join(RAW_TEXT_DIR, f"doc_{document_id}.txt")
    with open(raw_text_path, "w", encoding="utf-8") as f:
        f.write(text)

    chunks = chunk_text(text)
    if not chunks:
        db.update_document_status(document_id, "failed")
        raise ValueError("Document produced zero chunks after cleaning.")

    chunk_ids = db.insert_chunks(document_id, chunks)

    index = get_index(session_id)
    index.add_chunks(chunk_ids, [c["text"] for c in chunks])

    db.update_document_status(document_id, "indexed", company_name=company_name)

    return {
        "document_id": document_id,
        "company_name": company_name,
        "num_chunks": len(chunks),
        "chunk_ids": chunk_ids,
        "raw_text_path": raw_text_path,
        "classification": classification,
    }
