from datetime import datetime, date
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.evaluation import MessageEvaluation
from app.models.work_order import WorkOrder


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(self) -> dict:
        """概览统计：今日对话数、AI解决率、转人工率、平均置信度"""
        today = date.today()

        # 今日对话数
        r = await self.db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(func.date(Conversation.created_at) == today)
        )
        # 当执行了 COUNT、SUM、AVG 等聚合函数，或者只查询单个字段且确定只返回一个值时，scalar() 获取该纯数值
        today_conversations = r.scalar() or 0

        # 总对话数
        r = await self.db.execute(select(func.count()).select_from(Conversation))
        total_conversations = r.scalar() or 0

        # AI 解决率：status='resolved' 且 resolved_by_ai=True 的比例
        r = await self.db.execute(
            select(
                func.count(case((Conversation.resolved_by_ai == True, 1))),
                func.count(),
            ).where(Conversation.status == "resolved")
        )
        row = r.one()
        resolved_by_ai = row[0] or 0
        total_resolved = row[1] or 1
        ai_resolution_rate = resolved_by_ai / total_resolved if total_resolved > 0 else 0

        # 转人工率：status='escalated'
        r = await self.db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.status == "escalated")
        )
        escalated = r.scalar() or 0
        human_transfer_rate = escalated / total_conversations if total_conversations > 0 else 0

        # 平均置信度
        r = await self.db.execute(
            select(func.avg(Message.confidence))
            .where(Message.role == "assistant", Message.confidence.isnot(None))
        )
        avg_confidence = r.scalar()

        # 工单数
        r = await self.db.execute(select(func.count()).select_from(WorkOrder))
        work_orders_created = r.scalar() or 0

        return {
            "today_conversations": today_conversations,
            "total_conversations": total_conversations,
            "ai_resolution_rate": round(ai_resolution_rate, 4),
            "human_transfer_rate": round(human_transfer_rate, 4),
            "avg_confidence": round(avg_confidence, 4) if avg_confidence else None,
            "work_orders_created": work_orders_created,
        }

    async def get_quality_distribution(self) -> dict:
        """质量标签分布"""
        r = await self.db.execute(
            select(
                MessageEvaluation.quality_label,
                func.count(MessageEvaluation.id),
            )
            .group_by(MessageEvaluation.quality_label)
        )
        result = {row[0]: row[1] for row in r.all()}
        #如果字典中已经存在该标签，则不做任何操作；如果不存在，则将其值设置为 0
        for label in ("accurate", "inaccurate", "incomplete", "hallucination"):
            result.setdefault(label, 0)
        return result

    async def get_knowledge_gaps(self) -> list[dict]:
        """知识库缺口：按 intent 分组，统计低置信度消息和负面评价"""
        # 低置信度消息按 intent 分组
        low_conf_r = await self.db.execute(
            select(
                Message.intent,
                func.count(Message.id).label("count"),
                func.avg(Message.confidence).label("avg_conf"),
            )
            .where(
                Message.role == "assistant",
                Message.confidence.isnot(None),
                Message.confidence < 0.6,
            )
            .group_by(Message.intent)
            .order_by(func.count(Message.id).desc())
            .limit(10)
        )
        low_conf_rows = low_conf_r.all()

        # 负面评价按 intent 分组
        neg_eval_r = await self.db.execute(
            select(
                Message.intent,
                func.count(MessageEvaluation.id).label("count"),
            )
            .join(Message, MessageEvaluation.message_id == Message.id)
            .where(
                MessageEvaluation.quality_label.in_(["inaccurate", "hallucination"]),
            )
            .group_by(Message.intent)
            .order_by(func.count(MessageEvaluation.id).desc())
            .limit(10)
        )
        neg_eval_rows = neg_eval_r.all()

        # 合并结果
        intent_map = {}
        for row in low_conf_rows:
            intent = row[0] or "未知"
            intent_map[intent] = {
                "topic": intent,
                "low_confidence_count": row[1],
                "avg_confidence": round(row[2], 4) if row[2] else None,
                "negative_eval_count": 0,
                "sample_questions": [],
            }
        for row in neg_eval_rows:
            intent = row[0] or "未知"
            if intent in intent_map:
                intent_map[intent]["negative_eval_count"] = row[1]
            else:
                intent_map[intent] = {
                    "topic": intent,
                    "low_confidence_count": 0,
                    "avg_confidence": None,
                    "negative_eval_count": row[1],
                    "sample_questions": [],
                }

        # 获取示例问题
        for intent_key in intent_map:
            sample_r = await self.db.execute(
                select(Message.content)
                .where(
                    Message.role == "user",
                    Message.intent == intent_key if intent_key != "未知" else Message.intent.is_(None),
                )
                .order_by(Message.created_at.desc())
                .limit(3)
            )
            intent_map[intent_key]["sample_questions"] = [
                row[0][:100] for row in sample_r.all()
            ]

        return sorted(intent_map.values(), key=lambda x: x["low_confidence_count"] + x["negative_eval_count"], reverse=True)

    async def get_prompt_suggestions(self) -> list[dict]:
        """Prompt 优化建议：分析负面评价的评论模式"""
        r = await self.db.execute(
            select(
                Message.intent,
                MessageEvaluation.quality_label,
                func.count(MessageEvaluation.id).label("count"),
            )
            .join(Message, MessageEvaluation.message_id == Message.id)
            .where(
                MessageEvaluation.quality_label.in_(["inaccurate", "hallucination"]),
                MessageEvaluation.comment.isnot(None),
                MessageEvaluation.comment != "",
            )
            .group_by(Message.intent, MessageEvaluation.quality_label)
            .order_by(func.count(MessageEvaluation.id).desc())
            .limit(20)
        )
        rows = r.all()

        suggestions = []
        for intent, label, count in rows:
            # 获取该分组下的评论样本
            comment_r = await self.db.execute(
                select(MessageEvaluation.comment)
                .join(Message, MessageEvaluation.message_id == Message.id)
                .where(
                    Message.intent == intent,
                    MessageEvaluation.quality_label == label,
                    MessageEvaluation.comment.isnot(None),
                    MessageEvaluation.comment != "",
                )
                .limit(5)
            )
            comments = [row[0] for row in comment_r.all()]

            suggestion_text = ""
            if label == "hallucination":
                suggestion_text = "存在幻觉问题，建议检查知识库覆盖度和 Prompt 中的事实约束指令"
            elif label == "inaccurate":
                suggestion_text = "回答不准确，建议优化检索策略或补充相关知识文档"

            suggestions.append({
                "pattern": f"{intent or '未知'} - {label}",
                "intent": intent or "未知",
                "quality_label": label,
                "count": count,
                "suggestion": suggestion_text,
                "sample_comments": comments,
            })

        return suggestions
