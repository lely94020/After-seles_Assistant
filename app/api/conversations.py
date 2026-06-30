import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.conversation import Conversation
from app.schemas.conversation import (
    ConversationResponse, ConversationDetailResponse,
    ChatWithContextRequest
)
from app.core.security import get_current_user_id, get_current_user, CurrentUser, require_role
from app.services.conversation_service import ConversationService
from app.services.diagnosis_service import DiagnosisService

router = APIRouter()


async def _check_conversation_access(conv_id: int, user: CurrentUser, db: AsyncSession) -> Conversation:
    """校验对话归属：本人或客服主管可访问"""
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if user.user_type != "cs_manager" and conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问此对话")
    return conv


@router.post("", response_model=ConversationResponse)
async def create_conversation(
        user_id: int = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
):
    """创建新对话"""
    svc = ConversationService(db)
    conv = await svc.create(user_id=user_id)
    return ConversationResponse.model_validate(conv)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
        skip: int = 0, limit: int = 20,
        user_id: int = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
):
    svc = ConversationService(db)
    convs = await svc.list_by_user(user_id=user_id, skip=skip, limit=limit)
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/admin")
async def admin_list_conversations(
        skip: int = 0,
        limit: int = 20,
        intent: str | None = Query(None),
        status: str | None = Query(None),
        user_type: str | None = Query(None),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
        keyword: str | None = Query(None),
        user: CurrentUser = Depends(require_role("cs_manager")),
        db: AsyncSession = Depends(get_db),
):
    """管理员级全量对话列表，支持过滤（仅客服主管）"""
    svc = ConversationService(db)
    rows, total = await svc.list_all(
        skip=skip, limit=limit,
        intent=intent, status=status, user_type=user_type,
        date_from=date_from, date_to=date_to, keyword=keyword,
    )
    items = []
    for conv, ut in rows:
        resp = ConversationResponse.model_validate(conv)
        resp_dict = resp.model_dump()
        resp_dict["user_type"] = ut
        items.append(resp_dict)
    return {"items": items, "total": total}


@router.get("/{conv_id}", response_model=ConversationDetailResponse)
async def get_conversation(
        conv_id: int,
        user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _check_conversation_access(conv_id, user, db)
    svc = ConversationService(db)
    conv = await svc.get(conv_id)
    return ConversationDetailResponse.model_validate(conv)


@router.post("/{conv_id}/chat")
async def chat_with_context(
        conv_id: int,
        body: ChatWithContextRequest,
        user_id: int = Depends(get_current_user_id),
        user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    """在多轮对话上下文中发送消息（诊断流程，SSE 流式）"""
    await _check_conversation_access(conv_id, user, db)
    diag_svc = DiagnosisService(db)

    async def event_generator():
        result = await diag_svc.run_diagnosis_step(conv_id, body.question, user_id)
        # 以 SSE 格式推送诊断结果
        yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{conv_id}/close")
async def close_conversation(
        conv_id: int,
        user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _check_conversation_access(conv_id, user, db)
    svc = ConversationService(db)
    await svc.close(conv_id, "resolved")
    return {"ok": True}


@router.delete("/{conv_id}")
async def delete_conversation(
        conv_id: int,
        user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    await _check_conversation_access(conv_id, user, db)
    svc = ConversationService(db)
    await svc.delete(conv_id)
    await db.commit()
    return {"ok": True}
