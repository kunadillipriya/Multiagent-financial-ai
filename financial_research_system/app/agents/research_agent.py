"""
research_agent.py
------------------
AGENT 5: Research Agent

Handles multi-part user questions with step-by-step retrieval, reasoning,
and strict source citation grounded in indexed documents.

### How multi-part questions are handled
A question is split into sub-questions on simple, reliable signals: a
question mark, or conjunctions like "and"/"also" joining two question-like
clauses. Each sub-question is then handled independently: retrieve ->
reason -> cite, and the final answer is the sub-answers stitched back
together under clear headers. This keeps every claim traceable to exactly
the retrieval step that produced it.

### How each sub-question is answered (default: fully offline, zero cost)
1. Retrieve the top-matching chunks from the session's vector index
   (app/vector_store.py).
2. Also try to match the sub-question against structured metrics
   (app/database.py's `metrics` table) by looking for company names and
   known metric keywords in the question text -- this lets "what was
   Aurora's revenue" pull the exact number rather than just a passage.
3. Compose the answer using ONLY retrieved chunk text and matched metric
   rows -- never anything from outside the documents -- with a citation
   (document + chunk/passage number) attached to every sentence.
4. If nothing relevant was retrieved, say so explicitly rather than
   guessing -- this is what keeps answers strictly grounded.

### Optional: LLM-powered phrasing (still fully grounded)
If the person sets an ANTHROPIC_API_KEY environment variable before
starting the app, step 3 is upgraded to ask Claude to write a more fluent
paragraph -- but the prompt restricts Claude to ONLY the retrieved text
(passed in as context) and explicitly forbids adding outside knowledge.
If no key is set, or the call fails for any reason, the system transparently
falls back to the offline extractive method above -- the person always gets
an answer either way.
"""

import os
import re
import json

from app import database as db
from app.vector_store import get_index

METRIC_KEYWORDS = {
    "revenue": "total_revenue", "sales": "total_revenue",
    "net income": "net_income", "profit": "net_income",
    "gross margin": "gross_margin_pct", "operating margin": "operating_margin_pct",
    "net margin": "net_margin_pct", "debt": "total_debt",
    "leverage": "debt_to_equity_ratio", "debt to equity": "debt_to_equity_ratio",
    "cash flow": "operating_cash_flow", "free cash flow": "free_cash_flow",
    "current ratio": "current_ratio", "liquidity": "current_ratio",
    "return on equity": "return_on_equity_pct", "roe": "return_on_equity_pct",
    "eps": "diluted_eps", "earnings per share": "diluted_eps",
    "assets": "total_assets", "liabilities": "total_liabilities",
}


def split_into_subquestions(question: str) -> list:
    """Simple, explainable splitting: break on '?' first; if that leaves one
    chunk, try splitting a single run-on sentence on ' and ' / ' also ' when
    both halves look like separate asks (each contains a question word or a
    company-ish capitalized token)."""
    parts = [p.strip() for p in re.split(r"(?<=\?)\s+", question.strip()) if p.strip()]
    if len(parts) > 1:
        return parts

    text = question.strip()
    for sep in [" and does ", " and what ", " and how ", " and is ", " and "]:
        if sep in text.lower():
            idx = text.lower().find(sep)
            first = text[: idx + 1].strip()
            second = (sep.strip() + " " + text[idx + len(sep):]).strip()
            second = re.sub(r"^and\s+", "", second, flags=re.IGNORECASE).strip()
            second = second[0].upper() + second[1:] if second else second
            if first and second:
                return [first if first.endswith("?") else first + "?",
                        second if second.endswith("?") else second + "?"]
    return [text]


def _match_metric_keyword(sub_question: str):
    lowered = sub_question.lower()
    for phrase, metric_name in sorted(METRIC_KEYWORDS.items(), key=lambda kv: -len(kv[0])):
        if phrase in lowered:
            return metric_name
    return None


def _match_company(sub_question: str, session_id: int):
    """Finds which indexed company (if any) the sub-question is talking
    about, by looking for its name as a substring of the question."""
    docs = db.list_documents(session_id)
    lowered = sub_question.lower()
    for d in docs:
        name = (d.get("company_name") or "").lower()
        if name and (name in lowered or name.split()[0] in lowered):
            return d
    return None


def answer_subquestion(session_id: int, sub_question: str, top_k: int = 4) -> dict:
    index = get_index(session_id)
    retrieved = index.search(sub_question, top_k=top_k)

    citations = []
    evidence_lines = []

    # Structured-metric lookup, when the question names a company + a known metric.
    metric_name = _match_metric_keyword(sub_question)
    company_doc = _match_company(sub_question, session_id)
    if metric_name and company_doc:
        metric_rows = [
            m for m in db.get_metrics_for_document(company_doc["id"])
            if m["metric_name"] == metric_name
        ]
        metric_rows = sorted(metric_rows, key=lambda r: r["period"])[-2:]
        for r in metric_rows:
            chunk = db.get_chunk(r["source_chunk_id"]) if r["source_chunk_id"] else None
            passage_no = (chunk["chunk_index"] + 1) if chunk else "?"
            evidence_lines.append(
                f"{company_doc['company_name']}'s {metric_name.replace('_', ' ').title()} "
                f"was {r['raw_value'] or r['metric_value']} in {r['period']} "
                f"[source: {company_doc['filename']}, passage #{passage_no}]."
            )
            citations.append({
                "document_id": company_doc["id"], "filename": company_doc["filename"],
                "chunk_id": r["source_chunk_id"], "passage_number": passage_no,
            })

    # Passage-level retrieval (always included for broader context/citations).
    for chunk_id, score, text in retrieved:
        chunk = db.get_chunk(chunk_id)
        doc = db.get_document(chunk["document_id"]) if chunk else None
        if not chunk or not doc:
            continue
        passage_no = chunk["chunk_index"] + 1
        snippet = text[:280].strip() + ("..." if len(text) > 280 else "")
        evidence_lines.append(
            f"Related passage from {doc['company_name']} ({doc['filename']}): "
            f"\"{snippet}\" [passage #{passage_no}]"
        )
        citations.append({
            "document_id": doc["id"], "filename": doc["filename"],
            "chunk_id": chunk_id, "passage_number": passage_no, "relevance_score": round(score, 3),
        })

    if not evidence_lines:
        return {
            "sub_question": sub_question,
            "answer_text": "I couldn't find anything in the indexed documents relevant to this part of the question.",
            "citations": [],
        }

    answer_text = "\n".join(f"- {line}" for line in evidence_lines[:6])
    return {"sub_question": sub_question, "answer_text": answer_text, "citations": citations}


def _try_llm_polish(sub_answers: list) -> str:
    """Optional: if ANTHROPIC_API_KEY is set, ask Claude to turn the
    extractive evidence into fluent prose -- STRICTLY constrained to the
    evidence already gathered, with explicit instructions not to add
    outside knowledge. Returns None (triggering the offline fallback) if no
    key is set or the call fails for any reason."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import urllib.request

        context_blocks = []
        for sa in sub_answers:
            context_blocks.append(f"Question: {sa['sub_question']}\nEvidence:\n{sa['answer_text']}")
        context = "\n\n".join(context_blocks)

        system_prompt = (
            "You are a financial research assistant. You will be given one or more "
            "sub-questions and bullet-point evidence already retrieved from source "
            "documents, each with a citation tag like [source: file, passage #N]. "
            "Write a clear, well-organized answer using ONLY the evidence given -- "
            "never add any fact, number, or claim that is not in the evidence. "
            "Preserve every citation tag exactly as given, attached to the claim it "
            "supports. If the evidence says something couldn't be found, say so."
        )

        body = json.dumps({
            "model": "claude-sonnet-4-6",
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": context}],
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        polished = "\n".join(text_parts).strip()
        return polished or None
    except Exception:
        return None  # silent fallback to the offline extractive answer


def answer_question(session_id: int, question: str) -> dict:
    sub_questions = split_into_subquestions(question)
    sub_answers = [answer_subquestion(session_id, sq) for sq in sub_questions]

    polished = _try_llm_polish(sub_answers) if len(sub_questions) >= 1 else None

    if polished:
        answer_text = polished
        mode = "llm_reasoned"
    else:
        blocks = []
        for i, sa in enumerate(sub_answers, start=1):
            header = f"**Part {i}: {sa['sub_question'].rstrip('?')}**" if len(sub_answers) > 1 else ""
            block = (header + "\n" if header else "") + sa["answer_text"]
            blocks.append(block)
        answer_text = "\n\n".join(blocks)
        mode = "offline_extractive"

    all_citations = [c for sa in sub_answers for c in sa["citations"]]

    db.log_qa(session_id, question, answer_text, json.dumps(all_citations))

    return {
        "question": question,
        "num_steps": len(sub_questions),
        "sub_questions": sub_questions,
        "answer": answer_text,
        "mode": mode,
        "citations": all_citations,
    }
