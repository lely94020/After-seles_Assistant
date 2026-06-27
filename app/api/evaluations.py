from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.conversation import Message
from app.schemas.evaluation import EvaluationCreate, EvaluationResponse, EvaluationListResult
from app.core.security import get_current_user_id
from app.services.evaluation_service import EvaluationService

router = APIRouter()


@router.post("", response_model=EvaluationResponse)
async def create_evaluation(
        body: EvaluationCreate,
        user_id: int = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
):
    """创建消息评价"""
    svc = EvaluationService(db)

    # 验证消息存在且为 assistant 消息
    msg = await db.get(Message, body.message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="只能评价 AI 回答")

    ev = await svc.create(
        message_id=body.message_id,
        evaluator_id=user_id,
        quality_label=body.quality_label,
        comment=body.comment,
    )
    return EvaluationResponse(
        id=ev.id,
        message_id=ev.message_id,
        conversation_id=msg.conversation_id,
        evaluator_id=ev.evaluator_id,
        quality_label=ev.quality_label,
        comment=ev.comment,
        created_at=ev.created_at,
    )


@router.get("", response_model=EvaluationListResult)
async def list_evaluations(
        conversation_id: int | None = Query(None),
        skip: int = 0,
        limit: int = 50,
        db: AsyncSession = Depends(get_db),
):
    """列出评价，支持按对话过滤"""
    svc = EvaluationService(db)
    if conversation_id:
        items, total = await svc.list_by_conversation(conversation_id, skip=skip, limit=limit)
        return EvaluationListResult(items=items, total=total)
    return EvaluationListResult(items=[], total=0)


@router.get("/by-message/{message_id}")
async def get_evaluation_for_message(
        message_id: int,
        db: AsyncSession = Depends(get_db),
):
    """获取某条消息的评价"""
    svc = EvaluationService(db)
    ev = await svc.get_for_message(message_id)
    if not ev:
        return None
    msg = await db.get(Message, ev.message_id)
    return EvaluationResponse(
        id=ev.id,
        message_id=ev.message_id,
        conversation_id=msg.conversation_id if msg else None,
        evaluator_id=ev.evaluator_id,
        quality_label=ev.quality_label,
        comment=ev.comment,
        created_at=ev.created_at,
    )
