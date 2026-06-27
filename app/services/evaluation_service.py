from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import MessageEvaluation
from app.models.conversation import Message


class EvaluationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        message_id: int,
        evaluator_id: int,
        quality_label: str,
        comment: str | None = None,
    ) -> MessageEvaluation:
        """创建消息评价"""
        ev = MessageEvaluation(
            message_id=message_id,
            evaluator_id=evaluator_id,
            quality_label=quality_label,
            comment=comment,
        )
        self.db.add(ev)
        await self.db.flush()
        await self.db.refresh(ev)
        return ev

    async def get_for_message(self, message_id: int) -> MessageEvaluation | None:
        """获取某条消息的评价（最新一条）"""
        r = await self.db.execute(
            select(MessageEvaluation)
            .where(MessageEvaluation.message_id == message_id)
            .order_by(MessageEvaluation.created_at.desc())
            .limit(1)
        )
        return r.scalar_one_or_none()

    async def list_by_conversation(
        self, conversation_id: int, skip: int = 0, limit: int = 50
    ) -> tuple[list[dict], int]:
        """列出某对话下所有 assistant 消息的评价"""
        # 子查询：该对话下所有 assistant 消息的 ID
        msg_subq = (
            select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == "assistant",
            )
            .scalar_subquery()
        )

        count_r = await self.db.execute(
            select(func.count())
            .select_from(MessageEvaluation)
            .where(MessageEvaluation.message_id.in_(msg_subq))
        )
        total = count_r.scalar() or 0

        r = await self.db.execute(
            select(MessageEvaluation, Message.content)
            .join(Message, MessageEvaluation.message_id == Message.id)
            .where(MessageEvaluation.message_id.in_(msg_subq))
            .order_by(MessageEvaluation.created_at.desc())
            .offset(skip).limit(limit)
        )
        rows = r.all()
        items = []
        for ev, msg_content in rows:
            items.append({
                "id": ev.id,
                "message_id": ev.message_id,
                "evaluator_id": ev.evaluator_id,
                "quality_label": ev.quality_label,
                "comment": ev.comment,
                "created_at": ev.created_at,
                "message_preview": msg_content[:200] if msg_content else None,
            })
        return items, total

    async def get_quality_distribution(self) -> dict:
        """按 quality_label 统计评价分布"""
        r = await self.db.execute(
            select(
                MessageEvaluation.quality_label,
                func.count(MessageEvaluation.id),
            )
            .group_by(MessageEvaluation.quality_label)
        )
        result = {row[0]: row[1] for row in r.all()}
        # 确保所有 label 都有值
        for label in ("accurate", "inaccurate", "incomplete", "hallucination"):
            result.setdefault(label, 0)
        return result
