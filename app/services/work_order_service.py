import asyncio
import json
import logging
import re
from datetime import datetime

import dashscope
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.work_order import WorkOrder, WorkOrderNote
from app.models.conversation import Conversation, Message
from app.models.device import Device

logger = logging.getLogger(__name__)

# 不同工单类型的必填字段（serial_number 和 device_model 满足其一即可）
REQUIRED_FIELDS = {
    "fault_repair": ["serial_number_or_device_model", "fault_description", "contact_info"],
    "general_inquiry": ["contact_info"],
    "installation": ["contact_info"],
    "other": ["contact_info"],
}

# 追问话术（LLM 失败时的回退模板）
FOLLOWUP_QUESTIONS = {
    "serial_number": "请提供设备的序列号（S/N码），一般在设备底部标签上，格式类似 DS-7608NI-K2/8P 或纯数字编码。如果找不到序列号，提供设备型号也可以。",
    "serial_number_or_device_model": "请提供设备序列号（S/N码）或设备型号（通常以 DS- 开头），一般在设备底部标签或包装盒上可以看到。",
    "fault_description": "能再具体描述一下故障现象吗？比如是什么情况下出现的、有没有错误提示？",
    "contact_info": "请提供一下您的联系电话，方便售后网点后续联系您。",
    "device_model": "请问您的设备型号是什么？可以在设备标签上找到，通常以 DS- 开头。",
}

# 字段中文标签
FIELD_LABELS = {
    "device_model": "设备型号",
    "serial_number": "设备序列号",
    "fault_description": "故障描述",
    "contact_info": "联系方式",
    "order_type": "工单类型",
    "serial_number_or_device_model": "设备型号/序列号",
}


class WorkOrderService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- CRUD ----

    async def create(
        self,
        user_id: int,
        order_type: str,
        fault_description: str | None = None,
        serial_number: str | None = None,
        contact_info: str | None = None,
        device_model: str | None = None,
        device_id: int | None = None,
        conversation_id: int | None = None,
    ) -> WorkOrder:
        # 如果传了 device_model 但没传 device_id，自动查找
        if device_model and not device_id:
            r = await self.db.execute(
                select(Device).where(Device.model_number == device_model)
            )
            device = r.scalar_one_or_none()
            if device:
                device_id = device.id

        order_number = await self._generate_order_number()
        order = WorkOrder(
            order_number=order_number,
            user_id=user_id,
            order_type=order_type,
            fault_description=fault_description,
            serial_number=serial_number,
            contact_info=contact_info,
            device_id=device_id,
            conversation_id=conversation_id,
        )
        self.db.add(order)
        await self.db.flush()

        # 自动添加创建备注
        note = WorkOrderNote(
            work_order_id=order.id,
            operator_id=user_id,
            content="工单已创建",
            action_type="note",
        )
        self.db.add(note)
        await self.db.flush()
        await self.db.refresh(order)
        return order

    async def get(self, order_id: int) -> WorkOrder | None:
        r = await self.db.execute(
            select(WorkOrder)
            .where(WorkOrder.id == order_id)
            .options(selectinload(WorkOrder.notes)) #selectinload 会自动在当前查询后追加一条 SELECT ... WHERE id IN (...) 的语句，
            # 一次性将关联的 notes 数据加载到内存中，避免后续访问时的多次数据库查询
        )
        return r.scalar_one_or_none()

    async def delete(self, order_id: int) -> bool:
        """删除工单及其关联的备注"""
        from sqlalchemy import delete as sql_delete
        # 先删备注
        await self.db.execute(
            sql_delete(WorkOrderNote).where(WorkOrderNote.work_order_id == order_id)
        )
        # 再删工单
        result = await self.db.execute(
            sql_delete(WorkOrder).where(WorkOrder.id == order_id)
        )
        await self.db.flush()
        return result.rowcount > 0

    async def list_by_user(self, user_id: int, skip: int = 0, limit: int = 20) -> list[WorkOrder]:
        r = await self.db.execute(
            select(WorkOrder)
            .where(WorkOrder.user_id == user_id)
            .order_by(WorkOrder.created_at.desc())
            .offset(skip).limit(limit)
        )
        return list(r.scalars().all())

    async def list_all(
        self, skip: int = 0, limit: int = 20, status: str | None = None,
        order_type: str | None = None, keyword: str | None = None,
    ) -> tuple[list[WorkOrder], int]:
        """返回 (工单列表, 总数)"""
        stmt = select(WorkOrder)
        count_stmt = select(func.count(WorkOrder.id))

        if status:
            stmt = stmt.where(WorkOrder.status == status)
            count_stmt = count_stmt.where(WorkOrder.status == status)
        if order_type:
            stmt = stmt.where(WorkOrder.order_type == order_type)
            count_stmt = count_stmt.where(WorkOrder.order_type == order_type)
        if keyword:
            like_pattern = f"%{keyword}%"
            kw_filter = WorkOrder.order_number.ilike(like_pattern) | WorkOrder.fault_description.ilike(like_pattern)
            stmt = stmt.where(kw_filter)
            count_stmt = count_stmt.where(kw_filter)

        # 获取总数
        total_r = await self.db.execute(count_stmt)
        total = total_r.scalar() or 0

        # 获取列表
        stmt = stmt.order_by(WorkOrder.created_at.desc()).offset(skip).limit(limit)
        r = await self.db.execute(stmt)
        return list(r.scalars().all()), total

    async def update_status(
        self,
        order_id: int,
        status: str,
        operator_id: int,
        resolution: str | None = None,
        assigned_to: int | None = None,
        note: str | None = None,
    ) -> WorkOrder | None:
        values: dict = {"status": status}
        if resolution is not None:
            values["resolution"] = resolution
        if assigned_to is not None:
            values["assigned_to"] = assigned_to

        await self.db.execute(
            update(WorkOrder).where(WorkOrder.id == order_id).values(**values)
        )

        # 记录状态变更备注
        note_content = note or f"状态变更为: {status}"
        if resolution:
            note_content += f"\n解决方案: {resolution}"
        db_note = WorkOrderNote(
            work_order_id=order_id,
            operator_id=operator_id,
            content=note_content,
            action_type="status_change",
        )
        self.db.add(db_note)
        await self.db.flush()

        return await self.get(order_id)

    async def add_note(
        self, order_id: int, operator_id: int, content: str, action_type: str = "note"
    ) -> WorkOrderNote:
        note = WorkOrderNote(
            work_order_id=order_id,
            operator_id=operator_id,
            content=content,
            action_type=action_type,
        )
        self.db.add(note)
        await self.db.flush()
        return note

    # ---- 辅助方法 ----

    async def get_device_model(self, device_id: int | None) -> str | None:
        """根据 device_id 获取设备型号"""
        if not device_id:
            return None
        r = await self.db.execute(
            select(Device.model_number).where(Device.id == device_id)
        )
        return r.scalar_one_or_none()

    async def get_user_name(self, user_id: int | None) -> str:
        """根据 user_id 获取用户名（简单实现）"""
        if not user_id:
            return "系统"
        from app.models.auth import User
        r = await self.db.execute(
            select(User.username).where(User.id == user_id)
        )
        name = r.scalar_one_or_none()
        return name or f"用户{user_id}"

    async def build_timeline(self, notes: list[WorkOrderNote]) -> list[dict]:
        """将 notes 转换为前端期望的 timeline 格式"""
        timeline = []
        for note in notes:
            operator_name = await self.get_user_name(note.operator_id)
            timeline.append({
                "status": self._extract_status_from_note(note),
                "note": note.content,
                "operator": operator_name,
                "created_at": note.created_at,
            })
        return timeline

    def _extract_status_from_note(self, note: WorkOrderNote) -> str | None:
        """从备注内容中提取状态"""
        if note.action_type == "status_change":
            match = re.search(r"状态变更为:\s*(\w+)", note.content)
            if match:
                return match.group(1)
        return None

    async def get_conversation_summary(self, conversation_id: int | None) -> str | None:
        """获取对话摘要（优先 LLM 生成，回退到简单截取）"""
        if not conversation_id:
            return None
        r = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        messages = list(r.scalars().all())
        if not messages:
            return None

        # 尝试 LLM 生成摘要
        try:
            summary = await self.generate_conversation_summary(conversation_id)
            if summary:
                return summary
        except Exception as e:
            logger.warning(f"LLM 对话摘要生成失败，回退到简单模式: {e}")

        # 回退：取最后几条消息
        return await self._fallback_summary(messages[-5:])

    async def _fallback_summary(self, messages: list) -> str:
        """简单的对话摘要回退"""
        lines = []
        for msg in messages:
            role_label = "用户" if msg.role == "user" else "助手"
            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            lines.append(f"{role_label}: {content}")
        return "\n".join(lines)

    # ---- 智能工单创建 ----

    async def extract_fields_from_conversation(self, conversation_id: int) -> dict:
        """从对话历史中调用 LLM 提取工单字段"""
        r = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        conv = r.scalar_one_or_none()
        if not conv:
            return {}

        # 格式化对话历史
        conversation_text = self._format_conversation(conv.messages or [])

        # 获取已知设备型号辅助推断
        known_models = await self._get_known_device_models()
        model_hint = ""
        if known_models:
            model_hint = f"\n已知设备型号列表（仅供参考，用户描述模糊时从中匹配最可能的型号）：\n{', '.join(known_models[:30])}\n"

        prompt = f"""从以下对话中提取工单信息，输出 JSON。不要编造信息，缺失字段输出 null。

提取字段：
- device_model: 设备型号（格式通常以 DS- 开头，如 DS-2CD2T47G2-L、DS-7608NI-K2/8P）
- serial_number: 设备序列号（S/N码，通常是纯数字编码或条形码编号，不是以 DS- 开头的型号）
- fault_description: 故障现象描述（一句话概括核心问题）
- contact_info: 联系方式（电话号码或邮箱）
- order_type: 工单类型（fault_repair=故障报修, general_inquiry=一般咨询, installation=安装问题, other=其他）

注意：device_model 和 serial_number 是两个不同的字段！
- 以 "DS-" 开头的是设备型号 → device_model
- 设备底部标签上的 S/N 码（纯数字或字母数字混合）才是序列号 → serial_number
- 如果用户只提供了一个编号，优先识别为 device_model

模糊描述推断规则：
- 如果用户用外观描述设备（如"黑色小摄像头"、"那个球机"、"门口的枪机"），尝试从已知型号列表中匹配最可能的型号
- 如果用户说"那个NVR"但没给型号，device_model 输出 null，不要猜测
- 如果能从上下文推断出型号（如用户之前提到过），填写推断的型号
{model_hint}
对话记录：
{conversation_text}

只输出 JSON，无其他文字：
{{"device_model": "xxx或null", "serial_number": "xxx或null", "fault_description": "xxx或null", "contact_info": "xxx或null", "order_type": "fault_repair"}}"""

        resp = await asyncio.to_thread(
            dashscope.Generation.call,
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            api_key=settings.DASHSCOPE_API_KEY,
        )

        try:
            raw = resp.output.text if resp.status_code == 200 and resp.output else ""
            result = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                logger.warning(f"工单字段提取输出不是有效JSON: {raw}")
                result = {}

        return result

    def check_completeness(self, fields: dict, order_type: str) -> list[str]:
        """校验必填字段完整度，返回缺失字段列表"""
        required = REQUIRED_FIELDS.get(order_type, REQUIRED_FIELDS["other"])
        missing = []
        for f in required:
            if f == "serial_number_or_device_model":
                # 序列号和型号满足其一即可
                if not fields.get("serial_number") and not fields.get("device_model"):
                    missing.append(f)
            elif not fields.get(f):
                missing.append(f)
        return missing

    def detect_conflicts(self, old_fields: dict, new_fields: dict) -> list[dict]:
        """检测新旧字段值的冲突，返回冲突列表

        每个冲突: {"field": str, "old_value": str, "new_value": str, "message": str}
        """
        conflicts = []
        compare_keys = ["device_model", "serial_number", "contact_info", "order_type"]

        for key in compare_keys:
            old_val = old_fields.get(key)
            new_val = new_fields.get(key)
            if old_val and new_val and old_val != new_val:
                label = FIELD_LABELS.get(key, key)
                conflicts.append({
                    "field": key,
                    "old_value": old_val,
                    "new_value": new_val,
                    "message": f"{label}：之前记录的是「{old_val}」，但您现在提到了「{new_val}」，以哪个为准？",
                })

        # fault_description 用 LLM 判断是否矛盾
        old_desc = old_fields.get("fault_description")
        new_desc = new_fields.get("fault_description")
        if old_desc and new_desc and old_desc != new_desc:
            conflicts.append({
                "field": "fault_description",
                "old_value": old_desc,
                "new_value": new_desc,
                "message": f"故障描述有变化：\n- 之前：「{old_desc}」\n- 现在：「{new_desc}」\n请确认最新的故障现象。",
            })

        return conflicts

    async def resolve_conflict(self, field: str, old_value: str, new_value: str, user_reply: str) -> str:
        """用 LLM 判断用户回复是选择了哪个值，还是提供了新值"""
        prompt = f"""用户在确认工单信息时有以下冲突：
- 字段：{FIELD_LABELS.get(field, field)}
- 旧值：{old_value}
- 新值：{new_value}
- 用户回复：{user_reply}

请判断用户的选择，只输出最终确认的值（直接输出值，不要其他文字）：
- 如果用户选择了旧值或新值之一，输出对应的那个值
- 如果用户提供了新的值，输出用户的新值
- 如果无法判断，输出新值"""

        result = await self._llm_call("qwen-turbo", prompt)
        return result.strip().strip('"').strip("'") or new_value

    async def generate_followup_question(
        self,
        missing_fields: list[str],
        extracted: dict | None = None,
        conflicts: list[dict] | None = None,
        conversation_history: str | None = None,
    ) -> str:
        """用 LLM 生成自然语言追问话术，综合考虑缺失字段、冲突和对话上下文"""
        if not missing_fields and not conflicts:
            return ""

        # 构建上下文
        context_parts = []
        if extracted:
            known = {k: v for k, v in extracted.items() if v}
            if known:
                context_parts.append(f"已收集到的信息：{json.dumps(known, ensure_ascii=False)}")

        if conflicts:
            conflict_text = "\n".join(f"- {c['message']}" for c in conflicts)
            context_parts.append(f"信息冲突：\n{conflict_text}")

        if missing_fields:
            missing_labels = [FIELD_LABELS.get(f, f) for f in missing_fields]
            context_parts.append(f"缺失字段：{', '.join(missing_labels)}")

        if conversation_history:
            context_parts.append(f"最近对话：\n{conversation_history}")

        context = "\n\n".join(context_parts) if context_parts else "无"

        # 有冲突时优先让用户确认冲突
        if conflicts:
            prompt = f"""你是海康威视售后助手，正在为用户创建工单。现在发现信息有冲突，需要向用户确认。

{context}

要求：
1. 友好地告知用户信息有冲突，请用户确认
2. 一次只确认一个最重要的冲突（优先设备型号 > 联系方式 > 故障描述）
3. 用简洁的自然语言，不要用编号列表
4. 语气亲切，像客服对话一样

只输出追问内容，无其他文字："""
        else:
            missing_desc = "、".join([FIELD_LABELS.get(f, f) for f in missing_fields])
            prompt = f"""你是海康威视售后助手，正在为用户创建工单。还缺少一些信息，需要向用户询问。

{context}

要求：
1. 用自然的对话方式询问缺失信息，不要机械地列出字段名
2. 一次问 1-2 个最关键的问题，不要一次问太多
3. 可以结合已有信息做关联询问（如有设备型号后问故障现象）
4. 语气亲切，像客服对话一样
5. 如果缺少联系方式，说明是为了售后网点联系

只输出追问内容，无其他文字："""

        result = await self._llm_call("qwen-turbo", prompt)
        return result.strip() if result.strip() else self._fallback_followup(missing_fields)

    def _fallback_followup(self, missing_fields: list[str]) -> str:
        """LLM 调用失败时的模板回退"""
        questions = []
        for f in missing_fields:
            q = FOLLOWUP_QUESTIONS.get(f)
            if q:
                questions.append(q)
        return "\n".join(questions) if questions else "还需要补充一些信息，请描述更多细节。"

    async def generate_conversation_summary(self, conversation_id: int | None) -> str | None:
        """用 LLM 生成对话摘要，用于工单关联的对话概要"""
        if not conversation_id:
            return None
        r = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        messages = list(r.scalars().all())
        if not messages:
            return None

        conversation_text = self._format_conversation(messages)
        prompt = f"""请将以下对话总结为一段简洁的工单摘要（3-5句话），包含：
- 用户的核心问题/需求
- 已确认的关键信息（设备型号、故障现象等）
- 当前进展状态

对话记录：
{conversation_text}

只输出摘要内容，无其他文字："""

        result = await self._llm_call("qwen-turbo", prompt)
        if result.strip():
            return result.strip()

        # 回退到简单摘要
        return await self._fallback_summary(messages)

    async def extract_from_message(self, message: str, known_models: list[str] | None = None) -> dict:
        """从单条用户消息中提取工单字段（增量提取），支持模糊描述推断"""
        model_hint = ""
        if known_models:
            model_hint = f"\n已知设备型号列表（仅供参考，用户描述模糊时从中匹配最可能的型号）：\n{', '.join(known_models[:30])}\n"

        prompt = f"""从以下用户消息中提取工单信息，输出 JSON。不要编造信息，缺失字段输出 null。

提取字段：
- device_model: 设备型号（通常以 DS- 开头）
- serial_number: 设备序列号（S/N码，纯数字或字母数字混合，不是 DS- 开头的型号）
- fault_description: 故障现象描述
- contact_info: 联系方式（电话号码或邮箱）
- order_type: 工单类型（fault_repair/general_inquiry/installation/other）
- confidence: 提取置信度（high/medium/low）

模糊描述推断规则：
- 如果用户用外观描述设备（如"黑色小摄像头"、"那个球机"、"门口的枪机"），尝试从已知型号列表中匹配最可能的型号
- 如果用户说"那个NVR"但没给型号，device_model 输出 null，不要猜测
- 如果能推断出型号，confidence 设为 low，并在 device_model 中填入推断的型号
- 如果用户明确给了型号（如 DS-2CD2042），confidence 设为 high
{model_hint}
用户消息：
{message}

只输出 JSON，无其他文字：
{{"device_model": "xxx或null", "serial_number": "xxx或null", "fault_description": "xxx或null", "contact_info": "xxx或null", "order_type": "fault_repair或null", "confidence": "high"}}"""

        raw = await self._llm_call("qwen-turbo", prompt)

        try:
            result = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            result = json.loads(match.group()) if match else {}

        # 移除 confidence 字段（不存入工单），只保留有值的字段
        result.pop("confidence", None)
        return {k: v for k, v in result.items() if v is not None}

    async def create_from_conversation(
        self, conversation_id: int, user_id: int
    ) -> tuple[WorkOrder | None, list[str], str | None]:
        """
        从对话自动创建工单的完整流程。
        返回: (工单对象, 缺失字段列表, 追问话术)
        - 如果信息完整，创建工单并返回 (order, [], None)
        - 如果信息不完整，返回 (None, missing_fields, followup_question)
        """
        # 1. 从对话中提取字段
        extracted = await self.extract_fields_from_conversation(conversation_id)
        if not extracted:
            return None, ["fault_description", "contact_info"], "抱歉，无法从对话中提取工单信息，请手动创建工单。"

        # 2. 确定工单类型
        order_type = extracted.get("order_type", "fault_repair")

        # 3. 校验完整度
        missing = self.check_completeness(extracted, order_type)

        if missing:
            followup = await self.generate_followup_question(missing, extracted=extracted)
            return None, missing, followup

        # 4. 创建工单
        order = await self.create(
            user_id=user_id,
            order_type=order_type,
            fault_description=extracted.get("fault_description"),
            serial_number=extracted.get("serial_number"),
            contact_info=extracted.get("contact_info"),
            device_model=extracted.get("device_model"),
            conversation_id=conversation_id,
        )
        logger.info(f"从对话 {conversation_id} 自动创建工单 {order.order_number}")
        return order, [], None

    # ---- 内部方法 ----

    async def _generate_order_number(self) -> str:
        """生成工单号：WO + 日期 + 4位序号"""
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"WO{today}"

        # 查询当天最大序号
        r = await self.db.execute(
            select(WorkOrder.order_number)
            .where(WorkOrder.order_number.like(f"{prefix}%"))
            .order_by(WorkOrder.order_number.desc())
            .limit(1)
        )
        last = r.scalar_one_or_none()

        if last:
            try:
                seq = int(last[-4:]) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1

        return f"{prefix}{seq:04d}"

    def _format_conversation(self, messages: list[Message]) -> str:
        """格式化对话历史为可读文本"""
        lines = []
        for msg in messages:
            role_label = "用户" if msg.role == "user" else "助手"
            lines.append(f"{role_label}: {msg.content}")
        return "\n".join(lines)

    async def _get_known_device_models(self) -> list[str]:
        """从数据库获取已知设备型号列表，用于辅助模糊描述推断"""
        r = await self.db.execute(select(Device.model_number))
        return [row[0] for row in r.all() if row[0]]

    async def _llm_call(self, model: str, prompt: str) -> str:
        """统一的 LLM 调用封装"""
        resp = await asyncio.to_thread(
            dashscope.Generation.call,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_key=settings.DASHSCOPE_API_KEY,
        )
        return resp.output.text if resp.status_code == 200 and resp.output else ""
