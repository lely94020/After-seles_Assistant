from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    conversation_id: int | None = None


class Citation(BaseModel):
    index: int
    chunk_id: int
    document_id: int
    parent_title: str = ""


class ChatResponse(BaseModel):
    answer: str
    confidence: float
    disposition: str  # direct | caution | refuse
    intent: dict
    citations: list[Citation] = []


class StreamToken(BaseModel):
    token: str = ""
    done: bool = False
    confidence: float | None = None
    disposition: str | None = None
    citations: list[Citation] | None = None


class FeedbackRequest(BaseModel):
    question: str
    intent: dict
    resolved: bool