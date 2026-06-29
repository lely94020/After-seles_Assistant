import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device


# ---- 实体提取 ----

def extract_entities(answer: str) -> list[dict]:
    """从回答中提取关键实体：型号、固件版本号、错误码"""
    entities = []

    # 型号：如 DS-2CD3T86
    for m in re.finditer(r"[A-Z]{2,}-[\w-]+", answer):
        entities.append({"type": "model_number", "value": m.group()})

    # 固件版本：如 v5.7.12
    for m in re.finditer(r"v\d+\.\d+\.\d+", answer):
        entities.append({"type": "firmware_version", "value": m.group()})

    # 错误码：海康常见错误码格式
    for m in re.finditer(r"0x[0-9A-Fa-f]{2,}|\b\d{5,7}\b", answer):
        entities.append({"type": "error_code", "value": m.group()})

    return entities


class ConfidenceService:
    """三层信号融合 + 硬规则检测的置信度评估"""

    @staticmethod
    def _entity_exists_in_docs(entity: dict, retrieved_docs: list[dict]) -> bool:
        """检查实体是否在检索文档内容中出现过"""
        value = entity["value"]
        return any(value in d.get("content", "") for d in retrieved_docs)

    @staticmethod
    async def _entity_exists_in_device(entity: dict, db: AsyncSession) -> bool:
        """检查型号是否在设备信息表中存在"""
        if entity["type"] != "model_number":
            return True  # 非型号实体不做设备表校验
        r = await db.execute(
            select(Device.id).where(Device.model_number == entity["value"])
        )
        return r.scalar_one_or_none() is not None

    @staticmethod
    def _has_overlap(retrieved_docs: list[dict]) -> bool:
        """检查两路检索是否召回相同 chunk"""
        return any(len(d.get("sources", [])) >= 2 for d in retrieved_docs)

    @staticmethod
    async def evaluate(
        answer: str,
        retrieved_docs: list[dict],
        business_context: dict,
        db: AsyncSession,
    ) -> dict:
        """
        参数：
          answer: 大模型生成的回答文本
          retrieved_docs: 混合检索返回的 chunk 列表（已包含 sources 字段）
          business_context: {
              "model_hit": bool,
              "is_high_risk": bool,
              "device_exists": bool,
              "historical_resolve_rate": float,
          }
          db: 用于查询设备信息表
        """

        # ========== 第一层：检索置信度（权重 0.4）==========
        # 适配 RRF 评分体系：基于检索结果数量和排名质量
        num_docs = len(retrieved_docs)
        if num_docs > 0:
            # 有检索结果 → 基础分 0.4，按数量递增（3 篇以上满分）
            ret_score = 0.4 + min(1.0, num_docs / 3.0) * 0.3
        else:
            ret_score = 0.0
        ret_score += (1.0 if business_context.get("model_hit") else 0.0) * 0.2
        ret_score += (1.0 if ConfidenceService._has_overlap(retrieved_docs) else 0.3) * 0.1
        ret_score = min(1.0, ret_score)

        # ========== 第二层：生成置信度（权重 0.4）==========
        entities = extract_entities(answer)
        if entities:
            known = 0
            for e in entities:
                in_docs = ConfidenceService._entity_exists_in_docs(e, retrieved_docs)
                if e["type"] == "model_number":
                    in_device = await ConfidenceService._entity_exists_in_device(e, db)
                    if in_docs or in_device:
                        known += 1
                else:
                    if in_docs:
                        known += 1
            trace_rate = known / len(entities)
        else:
            # 无实体（通用问题）→ 不惩罚，给中性分
            trace_rate = 0.6
            known = 0

        gen_score = trace_rate * 0.7
        if entities:
            gen_score += (1.0 - min(0.3 * (len(entities) - known), 1.0)) * 0.3
        else:
            gen_score += 0.3 * 0.5  # 无实体时给一半

        # 信号3：模型自评 —— 从回答末尾解析 [自评: 高/中/低]
        self_eval_match = re.search(
            r"\[自评[:：]\s*(高|中|低)\s*\]",
            answer,
        )
        if self_eval_match:
            level = self_eval_match.group(1)
            if level == "高":
                model_self_eval_score = 0.9
            elif level == "中":
                model_self_eval_score = 0.6
            else:  # 低
                model_self_eval_score = 0.2
        else:
            # 未输出自评 → 中性分，不扣分
            model_self_eval_score = 0.6

        gen_score = gen_score * 0.7 + model_self_eval_score * 0.3

        # ========== 第三层：业务置信度（权重 0.2）==========
        biz_score = 0.6
        if business_context.get("is_high_risk"):
            biz_score -= 0.15
        if not business_context.get("device_exists"):
            biz_score -= 0.05  # 未提型号是常见情况，轻微扣分
        hist_rate = business_context.get("historical_resolve_rate", 0.5)
        biz_score += (hist_rate - 0.5) * 0.4

        # ========== 加权融合 ==========
        total = ret_score * 0.4 + gen_score * 0.4 + biz_score * 0.2
        total = max(0.0, min(1.0, total))

        # ========== 硬规则检测 ==========
        hard_rule_triggered = False
        safe_answer = answer

        # 规则1：固件版本号不存在于知识库 → 替换版本号
        for e in entities:
            if e["type"] == "firmware_version":
                if not ConfidenceService._entity_exists_in_docs(e, retrieved_docs):
                    safe_answer = safe_answer.replace(
                        e["value"], "[请参考官网下载页获取最新固件]"
                    )
                    hard_rule_triggered = True

        # 规则2：高风险问题 → 附加安全提示，并强制降级
        if business_context.get("is_high_risk"):
            if "安全提示" not in safe_answer:
                safe_answer = (
                    "⚠️ **安全提示：本建议涉及高风险操作，请务必在断电后由专业人员操作，"
                    "如有不确定请直接联系海康技术支持。**\n\n" + safe_answer
                )
                hard_rule_triggered = True
            if total >= 0.75:
                total = 0.74

        # 规则3：连续两轮用户反馈"没用/不对" → 由对话管理模块处理（占位）

        # ========== 处置策略 ==========
        if total >= 0.75:
            disposition = "direct"
        elif total >= 0.5:
            disposition = "caution"
            if "以上建议仅供参考" not in safe_answer:
                safe_answer += "\n\n> 💡 以上建议仅供参考，建议联系海康技术支持确认。"
        else:
            disposition = "refuse"
            safe_answer = (
                "当前知识库信息有限，无法给出准确建议。建议您：\n"
                "1. 联系海康技术支持获取专业指导\n"
                "2. 在官网提交工单获取一对一服务"
            )

        return {
            "confidence": round(total, 4),
            "disposition": disposition,
            "retrieval_score": round(ret_score, 4),
            "generation_score": round(gen_score, 4),
            "business_score": round(biz_score, 4),
            "hard_rule_triggered": hard_rule_triggered,
            "safe_answer": safe_answer,
        }
