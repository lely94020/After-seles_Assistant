import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.chat import ChatRequest, FeedbackRequest
from app.core.security import get_current_user_id, get_current_user, CurrentUser
from app.services.qa_service import QAService
from app.services.audit_service import AuditService

router = APIRouter()


@router.post("")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """智能问答（SSE 流式）"""
    svc = QAService(db)

    async def event_generator():
        full_answer = ""
        done_event = None
        async for event in svc.answer_stream(body.question, user_id=user_id, conversation_id=body.conversation_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("token") and not event.get("done"):
                full_answer += event["token"]
            if event.get("done"):
                done_event = event

        # 流式结束后持久化消息到对话
        if body.conversation_id and full_answer:
            from app.services.conversation_service import ConversationService
            conv_svc = ConversationService(db)
            await conv_svc.add_message(
                conv_id=body.conversation_id,
                role="user",
                content=body.question,
            )
            await conv_svc.add_message(
                conv_id=body.conversation_id,
                role="assistant",
                content=full_answer,
                citations=done_event.get("citations") if done_event else None,
                confidence=done_event.get("confidence") if done_event else None,
                intent=done_event.get("intent", {}).get("primary") if done_event else None,
            )
        # 审计：AI 对话调用
        audit = AuditService(db)
        await audit.log(
            user_id=user_id,
            action="ai_call",
            resource_type="chat",
            resource_id=str(body.conversation_id) if body.conversation_id else None,
            detail={"intent": done_event.get("intent", {}).get("primary") if done_event else None},
        )
        # 无论有无 conversation_id，都提交事务（answer_stream 内部可能已创建诊断会话）
        await db.commit()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback")
async def feedback(
    body: FeedbackRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = QAService(db)
    await svc.record_feedback(body.question, body.intent, body.resolved)
    return {"ok": True}