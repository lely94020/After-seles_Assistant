from datetime import datetime
from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: int
    title: str
    doc_type: str
    product_model: str | None = None
    product_series: str | None = None
    chunk_count: int
    version: int
    status: str
    reference_count: int = 0
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChunkResponse(BaseModel):
    id: int
    chunk_index: int
    content: str
    chunk_type: str
    parent_title: str | None = None
    token_count: int | None = None

    model_config = {"from_attributes": True}


class DocumentDetailResponse(DocumentResponse):
    chunks: list[ChunkResponse] = []


# === 管理员用 ===

class StatusUpdateRequest(BaseModel):
    status: str


class ScanExpiredResponse(BaseModel):
    scanned: int
    marked_review_due: int
    archived_expired: int


class TopReferencedResponse(BaseModel):
    id: int
    title: str
    doc_type: str
    product_model: str | None
    reference_count: int
    status: str

    model_config = {"from_attributes": True}
