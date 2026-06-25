import logging

from sqlalchemy import select, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.services.intent_service import IntentService
from app.services.hybrid_search_service import HybridSearchService
from app.services.llm_service import LLMService
from app.services.confidence_service import ConfidenceService
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)


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

    async def _handle_warranty(self,intent:dict)->dict:
        """保修查询：查 Device 表获取保修信息，并检索知识库中保修政策"""
        model=intent.get("model_number")

        # 从 Device 表查设备信息
        from sqlalchemy import select
        from app.models.device import Device
        device_info = None
        if model:
            r = await self.db.execute(
                select(Device).where(Device.model_number == model)
            )
            device_info = r.scalar_one_or_none()

        # 同时检索知识库中的保修政策文档
        retrieved = await self.hybrid_search.search(
            query="保修政策 保修期限 售后服务",
            model_number=model,
            top_k=5,
        )
        answer_text, citations = await LLMService.generate(
            query=f"用户查询保修信息，型号={model or'未提供'}，请结合设备信息和检索到的保修政策回答",
            retrieved_docs=retrieved,
        )

        answer_parts=[]
        if device_info:
            answer_parts.append(
                f"## {device_info.product_name or model} 保修信息\n\n"
                f"- **型号**：{device_info.model_number}\n"
                f"- **保修期限**：{device_info.warranty_months} 个月\n"
                f"- **产品状态**：{device_info.status}\n"
            )
        else:
            answer_parts.append(
                f"## 保修查询\n\n"
                f"未查询到型号 {model} 的设备信息，请确认型号是否正确。\n" if model
                else "请提供设备型号，以便查询保修信息。\n"
            )

        answer_parts.append(
            "\n如需报修，请提供设备序列号（S/N 码），"
            "或直接联系海康技术支持：400-800-5998。"
        )

        full_answer = "\n".join(answer_parts)

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
            "intent":{"primary":"warranty_service","model_number":model},
            "citations":citations,
            "retrieval_count":len(retrieved),
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
        """保修查询流式版：查设备信息 + 回答 + 创建保修对话 + 追问工单信息"""
        model = intent.get("model_number")

        from sqlalchemy import select
        from app.models.device import Device
        device_info = None
        if model:
            r = await self.db.execute(
                select(Device).where(Device.model_number == model)
            )
            device_info = r.scalar_one_or_none()

        # 先推设备基本信息
        if device_info:
            header = (
                f"## {device_info.product_name or model} 保修信息\n\n"
                f"- **型号**：{device_info.model_number}\n"
                f"- **保修期限**：{device_info.warranty_months} 个月\n"
                f"- **产品状态**：{device_info.status}\n\n"
            )
        else:
            header = (
                f"## 保修查询\n\n"
                f"未查询到型号 {model} 的设备信息，请确认型号是否正确。\n\n" if model
                else "请提供设备型号，以便查询保修信息。\n\n"
            )
        yield {"token": header, "done": False}

        # 检索保修政策 + 流式生成
        retrieved = await self.hybrid_search.search(
            query="保修政策 保修期限 售后服务",
            model_number=model,
            top_k=5,
        )

        all_tokens = header
        citations = []
        async for chunk in LLMService.generate_stream(
            query=f"用户查询保修信息，型号={model or '未提供'}，请结合设备信息和检索到的保修政策回答",
            retrieved_docs=retrieved,
        ):
            import json
            if chunk.startswith('{"citations"'):
                citations_data = json.loads(chunk)
                citations = citations_data.get("citations", [])
            else:
                all_tokens += chunk
                yield {"token": chunk, "done": False}

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
                title=f"保修/报修 - {model or '未知型号'}",
            )
            conversation_id = conv.id

            # 从初始问题提取字段并保存
            from app.services.work_order_service import WorkOrderService
            wo_svc = WorkOrderService(self.db)
            initial_fields = await wo_svc.extract_from_message(question)
            if model and not initial_fields.get("device_model"):
                initial_fields["device_model"] = model

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
        """保修对话后续：增量提取工单信息 → 校验 → 创建工单或继续追问"""
        from app.services.work_order_service import WorkOrderService
        from app.schemas.work_order import WorkOrderResponse

        conv_svc = ConversationService(self.db)
        await conv_svc.add_message(conv.id, "user", question)

        wo_svc = WorkOrderService(self.db)

        # 从最新消息中增量提取（只提取新信息）
        new_fields = await wo_svc.extract_from_message(question)

        # 与已有字段合并，不覆盖已有值
        kf = conv.key_facts or {}
        extracted = kf.get("_extracted_fields", {})
        for k, v in new_fields.items():
            if v and not extracted.get(k):
                extracted[k] = v
        # 设备型号也合并
        if kf.get("device_model") and not extracted.get("device_model"):
            extracted["device_model"] = kf["device_model"]

        # 保存提取结果到 key_facts
        kf["_extracted_fields"] = extracted
        await conv_svc.update_key_facts(conv.id, kf)

        order_type = extracted.get("order_type", "fault_repair")
        missing = wo_svc.check_completeness(extracted, order_type)

        if missing:
            # 信息不完整，继续追问
            followup = wo_svc.generate_followup_question(missing)
            await conv_svc.add_message(conv.id, "assistant", followup, intent="warranty_service")

            yield {"token": followup, "done": False}
            yield {
                "token": "",
                "done": True,
                "confidence": 0.8,
                "disposition": "direct",
                "citations": [],
                "intent": {"primary": "warranty_service"},
                "conversation_id": conv.id,
            }
        else:
            # 信息完整，创建工单
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

            # 重新加载工单（含 notes 关联），避免异步懒加载报错
            order = await wo_svc.get(order.id)

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
                "token": "",
                "done": True,
                "confidence": 0.95,
                "disposition": "direct",
                "citations": [],
                "intent": {"primary": "warranty_service"},
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