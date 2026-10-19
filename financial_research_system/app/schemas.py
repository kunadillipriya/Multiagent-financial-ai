from pydantic import BaseModel
from typing import Optional


class WorkspaceCreate(BaseModel):
    name: str


class SessionCreate(BaseModel):
    name: str


class AskRequest(BaseModel):
    question: str


class DocumentSummary(BaseModel):
    id: int
    filename: str
    company_name: Optional[str] = None
    source_type: str
    status: str
    rejection_reason: Optional[str] = None
    uploaded_at: str
