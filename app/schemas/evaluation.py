from datetime import datetime
from pydantic import BaseModel


class EvaluationCreate(BaseModel):
    message_id: int
    quality_label: str  # accurate | inaccurate | incomplete | hallucination
    comment: str | None = None


class EvaluationResponse(BaseModel):
    id: int
    message_id: int
    conversation_id: int | None = None
    evaluator_id: int
    quality_label: str
    comment: str | None = None
    evaluator_name: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class EvaluationListResult(BaseModel):
    items: list[EvaluationResponse]
    total: int
