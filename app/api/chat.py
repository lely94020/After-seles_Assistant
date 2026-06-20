import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest
from app.services.qa_service import QAService

router = APIRouter()

@router.post("",response_model=ChatResponse)
async def chat(
        body:ChatRequest,
        db:AsyncSession=Depends(get_db)
):
    """智能问答（非流式）"""
    svc=QAService(db)
    result=await svc.answer(body.question)
    return ChatResponse(
        answer=result["answer"],
        confidence=result["confidence"],
        disposition=result["disposition"],
        intent=result["intent"],
        citations=result["citations"],
    )

@router.post("/stream")
async def chat_stream(
        body:ChatRequest,
        db:AsyncSession=Depends(get_db)
):
    """智能问答（SSE 流式）"""
    svc = QAService(db)

    async def event_generator():
        async for event in svc.answer_stream(body.question):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )

@router.post("/feedback")
async def feedback(
        body: FeedbackRequest,
        db: AsyncSession = Depends(get_db),
):
    svc = QAService(db)
    await svc.record_feedback(body.question, body.intent,
  body.resolved)
    return {"ok": True}