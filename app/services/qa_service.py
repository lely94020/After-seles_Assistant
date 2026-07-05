import json
import logging

from sqlalchemy import select, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.conversation import Message
from app.services.intent_service import IntentService
from app.services.hybrid_search_service import HybridSearchService
from app.services.llm_service import LLMService
from app.services.confidence_service import ConfidenceService
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

WARRANTY_SYSTEM_PROMPT = """你是海康威视售后技术支持专家，负责处理保修查询和报修相关问题。

规则：
1. 如果用户询问设备信息、保修状态、是否在保、设备规格、固件版本等问题，使用 query_device_info 工具查询
2. 根据工具返回的结构化数据，用自然语言为用户解释保修状态和设备信息
3. 保修状态说明：
   - active = 在保，告知剩余天数
   - expired = 已过保，建议联系售后或授权服务商
   - unknown = 无法确认，建议提供购买凭证
4. 如果工具返回为空（model_info 和 serial_info 都为 null），礼貌告知用户未查到该设备信息，建议核实型号或序列号
5. 使用 Markdown 格式输出，关键信息用**加粗**
6. 涉及报修时，引导用户补充故障描述和联系方式
7. 如需报修，提醒联系海康技术支持：400-800-5998
8. **严禁编造设备型号、序列号等信息。如果用户未提供设备信息，请直接询问用户需要报修的设备型号或序列号，不要调用工具**
"""


class QAService:
    """智能问答引擎主编排器"""

    # 05e 文档 3.1 节：意图 → 路由映射
    # 故障诊断路由到 RAG + 引导（多轮诊断后续单独模块实现）
    # 模糊意图路由到追问澄清

    def __init__(self, db: AsyncSession):
        self.db = db
        self.hybrid_search = HybridSearchService(db)

    async def answer(self, question: str) -> dict:
        """完整问答流水线：意图 → 检索 → 生成 → 评估"""

        # 意图分类
        intent = await IntentService.classify(question)
        logger.info(f"意图：{intent['primary_intent']},型号：{intent.get('model_number')}")

        # 模糊意图：直接返回追问
        if intent["primary_intent"] == "unclear":
            return self._clarify_response(question)
        #保修/报修->查设备信息
        if intent["primary_intent"]=="warranty_service":
            return await self._handle_warranty(intent)
        #SDK集成->限定SDK文档类型检索
        if intent["primary_intent"]=="sdk_integration":
            return await self._handle_sdk(intent,question)

        # 混合检索
        retrieved = await self.hybrid_search.search(
            query=question,
            model_number=intent.get("model_number"),
            top_k=10
        )
        logger.info(f"检索到{len(retrieved)}条文档")

        # 检索为空 → 拒绝调用 LLM，直接返回安全话术
        if not retrieved:
            return self._empty_retrieval_response(intent["primary_intent"])

        # 大模型生成
        answer_text, citations = await LLMService.generate(question, retrieved)

        # 构建业务上下文
        business_context = await self._build_business_context(question, intent, retrieved)

        # 置信度评估
        confidence_result = await ConfidenceService.evaluate(
            answer=answer_text,
            retrieved_docs=retrieved,
            business_context=business_context,
            db=self.db,
        )

        final_answer = confidence_result["safe_answer"]

        # 故障诊断意图：附加上引导提示，提示用户可以继续追问
        if intent["primary_intent"] == "fault_diagnosis":
            final_answer += "\n\n---\n> 🔍如需进一步排查，请告诉我更多信息（如设备指示灯状态、NVR是否有报警等），我可以逐步帮你定位问题。"

        # 次意图处理
        if intent.get("has_secondary_request") and intent.get("secondary_intent"):
            if intent["secondary_intent"] == "warranty_service":
                model = intent.get("model_number", "您的设备")
                final_answer += f"\n\n> 📋 关于保修查询：如需查询 {model}的保修状态，请提供设备序列号（S/N码）。"

        return {
            "answer": final_answer,
            "confidence": confidence_result["confidence"],
            "disposition": confidence_result["disposition"],
            "intent": {
                "primary": intent["primary_intent"],
                "secondary": intent.get("secondary_intent"),
                "model_number": intent.get("model_number"),
            },
            "citations": citations,
            "retrieval_count": len(retrieved),
        }

    async def answer_stream(self, question: str, user_id: int | None = None, conversation_id: int | None = None):
            """流式问答：先完成检索，再流式输出生成结果"""

            # 保修对话的后续消息：收集工单信息 → 创建工单
            if conversation_id:
                conv_svc = ConversationService(self.db)
                conv = await conv_svc.get(conversation_id)
                if conv and conv.key_facts and conv.key_facts.get("_intent") == "warranty_service":
                    async for event in self._handle_warranty_followup(conv, question, user_id):
                        yield event
                    return

            # ① 意图分类
            intent = await IntentService.classify(question)

            if intent["primary_intent"] == "unclear":
                response = self._clarify_response(question)
                yield {"token": response["answer"], "done": False}
                yield {"token": "", "done": True,
                       "confidence": 0.0, "disposition": "refuse",
                       "citations": [], "intent": {"primary": "unclear"}}
                return

            # 保修/报修 → 查设备信息 + 流式回答 + 创建保修对话
            if intent["primary_intent"] == "warranty_service":
                async for event in self._handle_warranty_stream(intent, user_id, question):
                    yield event
                return

            # SDK 集成 → 限定 SDK 文档检索 + 流式回答
            if intent["primary_intent"] == "sdk_integration":
                async for event in self._handle_sdk_stream(intent, question):
                    yield event
                return

            # ② 混合检索
            retrieved = await self.hybrid_search.search(
                query=question,
                model_number=intent.get("model_number"),
                top_k=10,
            )

            # 检索为空 → 拒绝调用 LLM，直接返回安全话术
            if not retrieved:
                response = self._empty_retrieval_response(intent["primary_intent"])
                yield {"token": response["answer"], "done": False}
                yield {"token": "", "done": True,
                       "confidence": 0.0, "disposition": "refuse",
                       "citations": [], "intent": {"primary": intent["primary_intent"]}}
                return

            # ③ 流式生成
            all_tokens = ""
            citations = []
            async for chunk in LLMService.generate_stream(question, retrieved):
                import json
                if chunk.startswith('{"citations"'):
                    citations_data = json.loads(chunk)
                    citations = citations_data.get("citations", [])
                else:
                    all_tokens += chunk
                    yield {"token": chunk, "done": False}

            # 故障诊断意图：创建会话 + 立即生成排查计划 + 输出第一步引导
            conversation_id = None
            if intent["primary_intent"] == "fault_diagnosis":
                conv_svc = ConversationService(self.db)
                conv = await conv_svc.create(
                    user_id=user_id or 1,
                    title=question[:50],
                    intent="fault_diagnosis",
                )
                conversation_id = conv.id

                # 保存用户消息
                await conv_svc.add_message(conv.id, "user", question)

                # 保存 AI 回答（流式结束后再补 citations）
                await conv_svc.add_message(
                    conv.id, "assistant", all_tokens,
                    citations=citations,
                    intent="fault_diagnosis",
                )

                # 立即运行 LangGraph 生成排查计划
                from app.services.diagnosis_service import _get_graph
                graph = await _get_graph()
                config = {"configurable": {"thread_id": str(conv.id)}}

                input_state = {
                    "messages": [
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": all_tokens},
                    ],
                    "key_facts": {
                        "device_model": intent.get("model_number"),
                        "symptom": question,
                        "checked": [],
                        "ruled_out": [],
                    },
                    "current_step": "intent_classify",
                    "diagnosis_plan": [],
                    "step_index": 0,
                    "resolved": False,
                }

                try:
                    result = await graph.ainvoke(input_state, config)

                    # 同步状态到 MySQL（将 diagnosis_plan 也持久化到 key_facts）
                    kf = result.get("key_facts", {})
                    kf["_diagnosis_plan"] = result.get("diagnosis_plan", [])
                    await conv_svc.update_key_facts(conv.id, kf)
                    await conv_svc.update_step(conv.id, result.get("step_index", 0))

                    # 从排查计划生成引导问题
                    plan = result.get("diagnosis_plan", [])
                    idx = result.get("step_index", 0)
                    if plan and idx < len(plan):
                        guidance = (
                            f"\n\n---\n> 🔍 已为您生成排查计划（共{len(plan)}步），"
                            f"请先执行第1步：\n>\n> **{plan[0]}**\n>\n> 请告诉我检查结果。"
                        )
                    else:
                        guidance = (
                            "\n\n---\n> 🔍 已为您创建故障诊断会话，请告诉我更多信息"
                            "（如设备指示灯状态、错误提示等），我会逐步帮您定位问题。"
                        )
                except Exception as e:
                    logger.warning(f"LangGraph 初始化失败: {e}")
                    guidance = (
                        "\n\n---\n> 🔍 已为您创建故障诊断会话，请告诉我更多信息"
                        "（如设备指示灯状态、错误提示等），我会逐步帮您定位问题。"
                    )

                all_tokens += guidance
                yield {"token": guidance, "done": False}

            # 次意图处理
            if intent.get("has_secondary_request") and intent.get("secondary_intent"):
                if intent["secondary_intent"] == "warranty_service":
                    model = intent.get("model_number", "您的设备")
                    secondary = f"\n\n> 📋 关于保修查询：如需查询 {model}的保修状态，请提供设备序列号（S/N码）。"
                    all_tokens += secondary
                    yield {"token": secondary, "done": False}

            # ④ 生成完成后做置信度评估
            business_context = await self._build_business_context(question, intent, retrieved)
            confidence_result = await ConfidenceService.evaluate(
                answer=all_tokens,
                retrieved_docs=retrieved,
                business_context=business_context,
                db=self.db,
            )

            done_event = {
                "token": "",
                "done": True,
                "confidence": confidence_result["confidence"],
                "disposition": confidence_result["disposition"],
                "citations": citations,
                "intent": {
                    "primary": intent["primary_intent"],
                    "secondary": intent.get("secondary_intent"),
                    "model_number": intent.get("model_number"),
                },
            }
            if conversation_id:
                done_event["conversation_id"] = conversation_id
            yield done_event

    async def _check_device_exists(self, model_number: str | None) -> bool:
        """检查型号是否在设备信息表中存在"""
        if not model_number:
            return False
        r = await self.db.execute(
            select(Device.id).where(Device.model_number == model_number)
        )
        return r.scalar_one_or_none() is not None

    async def _build_business_context(
        self, question: str, intent: dict, retrieved: list[dict]
    ) -> dict:
        high_risk_keywords = ["强电", "高压", "220V", "380V", "防爆", "高空", "PoE供电", "拆机"]
        return {
            "model_hit": any("keyword" in d.get("sources", []) for d in retrieved),
            "is_high_risk": any(kw in question for kw in high_risk_keywords),
            "device_exists": await self._check_device_exists(intent.get("model_number")),
            "historical_resolve_rate":await self.get_historical_resolve_rate(intent.get("primary_intent", "")),
        }

    async def _handle_warranty(self, intent: dict) -> dict:
        """保修查询：LLM 工具调用 → 查询设备信息 → 生成回答"""
        from app.services.device_info_service import DEVICE_QUERY_TOOL, execute_device_query_tool

        model = intent.get("model_number")
        serial_number = intent.get("serial_number")

        # 工具执行器闭包
        async def tool_executor(tool_name: str, arguments: dict) -> str:
            if tool_name == "query_device_info":
                return await execute_device_query_tool(arguments, self.db)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        # 检索知识库中的保修政策文档
        retrieved = await self.hybrid_search.search(
            query="保修政策 保修期限 售后服务",
            model_number=model,
            top_k=5,
        )

        # LLM 工具调用：仅当用户提供了设备信息时才查询
        if model or serial_number:
            full_answer, citations, tool_log = await LLMService.generate_with_tools(
                query=f"用户查询保修信息，型号={model or '未提供'}，序列号={serial_number or '未提供'}",
                retrieved_docs=retrieved,
                tools=[DEVICE_QUERY_TOOL],
                tool_executor=tool_executor,
                system_prompt=WARRANTY_SYSTEM_PROMPT,
            )
        else:
            full_answer = "您好！感谢您联系海康威视售后技术支持。请问您需要报修什么设备？"
            citations = []
            tool_log = []

        # 置信度评估（幻觉控制）
        business_context = await self._build_business_context(
            f"保修查询 {model}", intent, retrieved
        )
        confidence_result = await ConfidenceService.evaluate(
            answer=full_answer,
            retrieved_docs=retrieved,
            business_context=business_context,
            db=self.db,
        )

        return {
            "answer": confidence_result["safe_answer"],
            "confidence": confidence_result["confidence"],
            "disposition": confidence_result["disposition"],
            "intent": {"primary": "warranty_service", "model_number": model},
            "citations": citations,
            "retrieval_count": len(retrieved),
        }

    async def _handle_sdk(self, intent: dict, question: str) -> dict:
        """SDK 集成：检索 SDK 相关文档库，回答 + 附代码示例引导"""
        model = intent.get("model_number")

        # 检索时强调 SDK 文档类型
        retrieved = await self.hybrid_search.search(
            query=question,
            model_number=model,
            top_k=10,
        )

        if not retrieved:
            return self._empty_retrieval_response("sdk_integration")

        answer_text, citations = await LLMService.generate(
            query=f"用户询问 SDK/API 集成问题：{question}。"
                  f"请从检索到的 SDK 文档中给出技术回答，"
                  f"如有代码示例请格式化展示，如无可跳过。",
            retrieved_docs=retrieved,
        )

        business_context = await self._build_business_context(question,intent, retrieved)
        confidence_result = await ConfidenceService.evaluate(
            answer=answer_text,
            retrieved_docs=retrieved,
            business_context=business_context,
            db=self.db,
        )

        final_answer = confidence_result["safe_answer"]
        final_answer += (
            "\n\n> 📦 如需完整的 SDK文档包，请访问海康开放平台下载最新版本。\n"
            "> 如涉及特定型号的接口差异，建议参考该型号的开发手册。"
        )

        return {
            "answer": final_answer,
            "confidence": confidence_result["confidence"],
            "disposition": confidence_result["disposition"],
            "intent": {"primary": "sdk_integration", "model_number": model},
            "citations": citations,
            "retrieval_count": len(retrieved),
        }

    async def _handle_warranty_stream(self, intent: dict, user_id: int | None = None, question: str = ""):
        """保修查询流式版：LLM 工具调用 → 查询设备信息 → 回答 + 创建保修对话 + 追问工单信息"""
        from app.services.device_info_service import DEVICE_QUERY_TOOL, execute_device_query_tool

        model = intent.get("model_number")
        serial_number = intent.get("serial_number")

        # 工具执行器闭包
        async def tool_executor(tool_name: str, arguments: dict) -> str:
            if tool_name == "query_device_info":
                return await execute_device_query_tool(arguments, self.db)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        # 检索保修政策文档
        retrieved = await self.hybrid_search.search(
            query="保修政策 保修期限 售后服务",
            model_number=model,
            top_k=5,
        )

        # LLM 工具调用：仅当用户提供了设备信息时才查询，避免 LLM 幻觉编造
        all_tokens = ""
        citations = []
        if model or serial_number:
            async for chunk in LLMService.generate_stream_with_tools(
                query=question,
                retrieved_docs=retrieved,
                tools=[DEVICE_QUERY_TOOL],
                tool_executor=tool_executor,
                system_prompt=WARRANTY_SYSTEM_PROMPT,
                status_message="正在查询设备信息...\n\n",
            ):
                if chunk.startswith('{"citations"'):
                    citations_data = json.loads(chunk)
                    citations = citations_data.get("citations", [])
                else:
                    all_tokens += chunk
                    yield {"token": chunk, "done": False}
        else:
            all_tokens = "您好！感谢您联系海康威视售后技术支持。请问您需要报修什么设备？"
            yield {"token": all_tokens, "done": False}

        # 置信度评估
        business_context = await self._build_business_context(
            f"保修查询 {model}", intent, retrieved
        )
        confidence_result = await ConfidenceService.evaluate(
            answer=all_tokens,
            retrieved_docs=retrieved,
            business_context=business_context,
            db=self.db,
        )

        # 创建保修对话，追问缺失信息
        conversation_id = None
        if user_id:
            conv_svc = ConversationService(self.db)
            conv = await conv_svc.create(
                user_id=user_id,
                title=f"保修/报修 - {model or serial_number or '未知设备'}",
                intent="warranty_service",
            )
            conversation_id = conv.id

            # 从初始问题提取字段并保存
            from app.services.work_order_service import WorkOrderService
            wo_svc = WorkOrderService(self.db)
            initial_fields = await wo_svc.extract_from_message(question)
            if model and not initial_fields.get("device_model"):
                initial_fields["device_model"] = model
            if serial_number and not initial_fields.get("serial_number"):
                initial_fields["serial_number"] = serial_number

            await conv_svc.update_key_facts(conv.id, {
                "_intent": "warranty_service",
                "device_model": model,
                "_extracted_fields": initial_fields,
            })

            await conv_svc.add_message(conv.id, "user", question)
            await conv_svc.add_message(
                conv.id, "assistant", all_tokens,
                citations=citations,
                intent="warranty_service",
            )

            # 追问缺失的工单信息
            followup = (
                "\n\n---\n> 📋 如需为您创建报修工单，请补充以下信息：\n"
                "> 1. 设备序列号（S/N 码）\n"
                "> 2. 故障现象描述\n"
                "> 3. 您的联系方式\n"
                ">\n> 请一次性提供，我会自动为您生成工单。"
            )
            all_tokens += followup
            yield {"token": followup, "done": False}

        done_event = {
            "token": "",
            "done": True,
            "confidence": confidence_result["confidence"],
            "disposition": confidence_result["disposition"],
            "citations": citations,
            "intent": {"primary": "warranty_service", "model_number": model},
        }
        if conversation_id:
            done_event["conversation_id"] = conversation_id
        yield done_event

    async def _handle_warranty_followup(self, conv, question: str, user_id: int | None = None):
        """保修对话后续：增量提取 → 冲突检测 → 完整度校验 → 创建工单或追问"""
        from app.services.work_order_service import WorkOrderService
        from app.schemas.work_order import WorkOrderResponse

        conv_svc = ConversationService(self.db)
        await conv_svc.add_message(conv.id, "user", question)

        wo_svc = WorkOrderService(self.db)
        kf = conv.key_facts or {}
        extracted = kf.get("_extracted_fields", {})
        pending_conflicts = kf.get("_pending_conflicts", [])

        # 1. 如果有待确认的冲突，先处理冲突
        if pending_conflicts:
            conflict = pending_conflicts[0]  # 一次处理一个
            resolved_value = await wo_svc.resolve_conflict(
                conflict["field"], conflict["old_value"], conflict["new_value"], question
            )
            extracted[conflict["field"]] = resolved_value
            pending_conflicts = pending_conflicts[1:]  # 移除已处理的冲突

            kf["_extracted_fields"] = extracted
            kf["_pending_conflicts"] = pending_conflicts
            await conv_svc.update_key_facts(conv.id, kf)
        else:
            # 2. 从最新消息中增量提取（支持模糊描述推断）
            known_models = await wo_svc._get_known_device_models()
            new_fields = await wo_svc.extract_from_message(question, known_models=known_models)

            # 3. 与已有字段合并，不覆盖已有值
            for k, v in new_fields.items():
                if v and not extracted.get(k):
                    extracted[k] = v
            if kf.get("device_model") and not extracted.get("device_model"):
                extracted["device_model"] = kf["device_model"]

            # 4. 检测冲突
            conflicts = wo_svc.detect_conflicts(kf.get("_extracted_fields", {}), new_fields)
            if conflicts:
                kf["_pending_conflicts"] = conflicts
                kf["_extracted_fields"] = extracted
                await conv_svc.update_key_facts(conv.id, kf)

                # 用 LLM 生成冲突确认追问
                followup = await wo_svc.generate_followup_question(
                    missing_fields=[], extracted=extracted, conflicts=conflicts
                )
                await conv_svc.add_message(conv.id, "assistant", followup, intent="warranty_service")
                yield {"token": followup, "done": False}
                yield {
                    "token": "", "done": True,
                    "confidence": 0.8, "disposition": "direct",
                    "citations": [], "intent": {"primary": "warranty_service"},
                    "conversation_id": conv.id,
                }
                return

            # 无冲突，保存提取结果
            kf["_extracted_fields"] = extracted
            await conv_svc.update_key_facts(conv.id, kf)

        # 4.5 如果刚提取到序列号，通过 LLM 工具调用查询设备信息
        if extracted.get("serial_number") and not kf.get("_device_info_shown"):
            from app.services.device_info_service import DEVICE_QUERY_TOOL, execute_device_query_tool

            async def tool_executor(tool_name: str, arguments: dict) -> str:
                if tool_name == "query_device_info":
                    return await execute_device_query_tool(arguments, self.db)
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

            info_text, _, _ = await LLMService.generate_with_tools(
                query=f"用户提供了序列号 {extracted['serial_number']}，请查询该设备的保修状态并告知用户。",
                retrieved_docs=[],
                tools=[DEVICE_QUERY_TOOL],
                tool_executor=tool_executor,
                system_prompt=WARRANTY_SYSTEM_PROMPT,
            )

            kf["_device_info_shown"] = True
            await conv_svc.update_key_facts(conv.id, kf)
            await conv_svc.add_message(conv.id, "assistant", info_text, intent="warranty_service")
            yield {"token": info_text, "done": False}

        # 5. 完整度校验
        order_type = extracted.get("order_type", "fault_repair")
        missing = wo_svc.check_completeness(extracted, order_type)

        if missing:
            # 用 LLM 生成自然语言追问（带上下文）
            conv_messages = await self.db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .limit(5)
            )
            recent_msgs = list(conv_messages.scalars().all())
            recent_msgs.reverse()
            history_text = "\n".join(
                f"{'用户' if m.role == 'user' else '助手'}: {m.content[:80]}"
                for m in recent_msgs
            )

            followup = await wo_svc.generate_followup_question(
                missing_fields=missing, extracted=extracted,
                conversation_history=history_text
            )
            await conv_svc.add_message(conv.id, "assistant", followup, intent="warranty_service")

            yield {"token": followup, "done": False}
            yield {
                "token": "", "done": True,
                "confidence": 0.8, "disposition": "direct",
                "citations": [], "intent": {"primary": "warranty_service"},
                "conversation_id": conv.id,
            }
        else:
            # 6. 信息完整，创建工单
            order = await wo_svc.create(
                user_id=user_id or conv.user_id,
                order_type=order_type,
                fault_description=extracted.get("fault_description"),
                serial_number=extracted.get("serial_number"),
                contact_info=extracted.get("contact_info"),
                device_model=extracted.get("device_model"),
                conversation_id=conv.id,
            )
            await self.db.commit()
            order = await wo_svc.get(order.id)

            # 工单创建成功，关闭会话
            await conv_svc.close(conv.id, "resolved", resolved_by_ai=True)

            answer = (
                f"工单已自动创建！\n\n"
                f"- **工单号**：{order.order_number}\n"
                f"- **类型**：{order_type}\n"
                f"- **设备型号**：{extracted.get('device_model', '-')}\n"
                f"- **序列号**：{extracted.get('serial_number', '-')}\n"
                f"- **故障描述**：{extracted.get('fault_description', '-')}\n\n"
                f"售后人员将尽快与您联系，请保持电话畅通。"
            )
            await conv_svc.add_message(conv.id, "assistant", answer, intent="warranty_service")

            yield {"token": answer, "done": False}
            yield {
                "token": "", "done": True,
                "confidence": 0.95, "disposition": "direct",
                "citations": [], "intent": {"primary": "warranty_service"},
                "conversation_id": conv.id,
                "work_order": {
                    "created": True,
                    "order": WorkOrderResponse.model_validate(order).model_dump(mode="json"),
                },
            }

    async def _handle_sdk_stream(self, intent: dict, question: str):
        """SDK 集成流式版：检索 SDK 文档 + 流式生成 + 置信度评估"""
        model = intent.get("model_number")

        retrieved = await self.hybrid_search.search(
            query=question,
            model_number=model,
            top_k=10,
        )

        if not retrieved:
            response = self._empty_retrieval_response("sdk_integration")
            yield {"token": response["answer"], "done": False}
            yield {"token": "", "done": True,
                   "confidence": 0.0, "disposition": "refuse",
                   "citations": [], "intent": {"primary": "sdk_integration"}}
            return

        all_tokens = ""
        citations = []
        async for chunk in LLMService.generate_stream(
            query=f"用户询问 SDK/API 集成问题：{question}。"
                  f"请从检索到的 SDK 文档中给出技术回答，"
                  f"如有代码示例请格式化展示，如无可跳过。",
            retrieved_docs=retrieved,
        ):
            import json
            if chunk.startswith('{"citations"'):
                citations_data = json.loads(chunk)
                citations = citations_data.get("citations", [])
            else:
                all_tokens += chunk
                yield {"token": chunk, "done": False}

        # 附加引导
        guidance = (
            "\n\n> 📦 如需完整的 SDK 文档包，请访问海康开放平台下载最新版本。\n"
            "> 如涉及特定型号的接口差异，建议参考该型号的开发手册。"
        )
        all_tokens += guidance
        yield {"token": guidance, "done": False}

        business_context = await self._build_business_context(question, intent, retrieved)
        confidence_result = await ConfidenceService.evaluate(
            answer=all_tokens,
            retrieved_docs=retrieved,
            business_context=business_context,
            db=self.db,
        )

        yield {
            "token": "",
            "done": True,
            "confidence": confidence_result["confidence"],
            "disposition": confidence_result["disposition"],
            "citations": citations,
            "intent": {"primary": "sdk_integration", "model_number": model},
        }

    def _format_warranty_status(self, query_result, warranty_status: dict | None) -> str:
        """将序列号查询结果格式化为 markdown 保修状态卡片"""
        mi = query_result.model_info
        si = query_result.serial_info
        lines = ["## 设备保修查询结果\n"]
        if mi:
            lines.append(f"- **产品名称**：{mi.product_name or '-'}")
            lines.append(f"- **设备型号**：{mi.model_number}")
            lines.append(f"- **产品系列**：{mi.product_series or '-'}")
        if si:
            lines.append(f"- **序列号**：{si.serial_number}")
            lines.append(f"- **购买渠道**：{si.purchase_channel or '-'}")
            lines.append(f"- **购买日期**：{si.purchase_date or '-'}")
        if warranty_status:
            status_label = {"active": "在保", "expired": "已过期"}.get(
                warranty_status.get("status"), "未知"
            )
            lines.append(f"- **保修状态**：{status_label}")
            lines.append(f"- **保修起始**：{warranty_status.get('start_date', '-')}")
            lines.append(f"- **保修截止**：{warranty_status.get('end_date', '-')}")
            remaining = warranty_status.get("remaining_days")
            if remaining is not None:
                lines.append(f"- **剩余天数**：{remaining} 天")
        if mi and mi.firmware_versions:
            lines.append(f"- **固件版本**：{', '.join(mi.firmware_versions)}")
        if mi and mi.wiring_diagram:
            lines.append(f"- **接线图**：[下载]({mi.wiring_diagram})")
        return "\n".join(lines) + "\n\n"

    def _format_model_info(self, mi) -> str:
        """将型号查询结果格式化为 markdown 设备规格卡片"""
        lines = [f"## {mi.product_name or mi.model_number} 设备信息\n"]
        lines.append(f"- **型号**：{mi.model_number}")
        lines.append(f"- **产品系列**：{mi.product_series or '-'}")
        lines.append(f"- **类别**：{mi.category or '-'}")
        lines.append(f"- **保修期限**：{mi.warranty_months} 个月")
        if mi.wiring_diagram:
            lines.append(f"- **接线图**：[下载]({mi.wiring_diagram})")
        if mi.firmware_versions:
            lines.append(f"- **固件版本**：{', '.join(mi.firmware_versions)}")
        if mi.specifications:
            lines.append("\n**技术规格**：")
            for k, v in mi.specifications.items():
                lines.append(f"  - {k}：{v}")
        if mi.knowledge_base_docs:
            lines.append(f"\n**相关文档**：{', '.join(mi.knowledge_base_docs)}")
        return "\n".join(lines) + "\n\n"

    def _empty_retrieval_response(self, intent_primary: str) -> dict:
        """检索结果为空时拒绝调用 LLM，直接返回安全话术"""
        return {
            "answer": (
                "抱歉，当前知识库中暂无相关信息，无法为您提供准确回答。\n\n"
                "建议您：\n"
                "1. 联系海康技术支持获取专业指导\n"
                "2. 在官网提交工单获取一对一服务"
            ),
            "confidence": 0.0,
            "disposition": "refuse",
            "intent": {"primary": intent_primary},
            "citations": [],
            "retrieval_count": 0,
        }

    def _clarify_response(self, question: str) -> dict:
            return {
                "answer": "抱歉，我没有完全理解您的问题。请问您遇到的是：\n\n"
                          "1. **设备故障**问题（如离线、画面异常等）\n"
                          "2. **产品选型**咨询\n"
                          "3. **保修/报修**需求\n"
                          "4. **SDK/API 集成**问题\n\n"
                          "请提供更详细的信息（如果知道设备型号，请一并告知），我会更好地帮助您。",
                "confidence": 0.0,
                "disposition": "refuse",
                "intent": {"primary": "unclear"},
                "citations": [],
                "retrieval_count": 0,
            }

    async def record_feedback(self, question: str, intent: dict,resolved: bool):
        """用户对回答的反馈记录"""
        from app.models.qa_feedback import QAFeedback
        fb = QAFeedback(
            question=question,
            intent=intent.get("primary", ""),
            model_number=intent.get("model_number"),
            resolved=resolved,
        )
        self.db.add(fb)
        await self.db.flush()

    async def get_historical_resolve_rate(self, intent_type: str) ->float:
        """查询同类意图的历史 AI 解决率"""
        from sqlalchemy import func,Integer,cast
        from app.models.qa_feedback import QAFeedback

        r = await self.db.execute(
            select(
                func.count(),
                #cast() 是在生成SQL时，告诉数据库把指定字段临时转成目标类型，用于解决查询时类型不匹配的问题。
                func.sum(cast(QAFeedback.resolved,Integer))
            ).where(QAFeedback.intent == intent_type)
        )
        total, resolved = r.one()
        if not total:
            return 0.5  # 无数据 → 中性值
        return resolved / total