from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.conversation import (
    ConversationResponse, ConversationDetailResponse,
    ChatWithContextRequest
)
from app.core.security import get_current_user_id
from app.services.conversation_service import ConversationService
from app.services.diagnosis_service import DiagnosisService

router = APIRouter()


@router.post("", response_model=ConversationResponse)
async def create_conversation(
        user_id:int = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
):
    """创建新对话"""
    svc = ConversationService(db)
    conv = await svc.create(user_id=user_id)
    return ConversationResponse.model_validate(conv)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
        skip: int = 0, limit: int = 20,
        user_id:int = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    convs = await svc.list_by_user(user_id=user_id, skip=skip, limit=limit)
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/{conv_id}", response_model=ConversationDetailResponse)
async def get_conversation(
        conv_id: int,
        db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    conv = await svc.get(conv_id)
    return ConversationDetailResponse.model_validate(conv)


@router.post("/{conv_id}/chat")
async def chat_with_context(
        conv_id: int,
        body: ChatWithContextRequest,
        user_id:int=Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
):
    """在多轮对话上下文中发送消息（诊断流程）"""
    diag_svc = DiagnosisService(db)
    result = await diag_svc.run_diagnosis_step(conv_id, body.question,user_id)
    return result


@router.post("/{conv_id}/close")
async def close_conversation(
        conv_id: int,
        db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    await svc.close(conv_id, "resolved")
    return {"ok": True}