import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.diagnosis_graph import build_diagnosis_graph
from app.services.conversation_service import ConversationService
from app.services.qa_service import QAService

logger=logging.getLogger(__name__)

#全局缓存编译好的graph（避免每次请求重新编译）
_graph=None

async def _get_graph():
    global _graph
    if _graph is None:
        _graph=await build_diagnosis_graph()
    return _graph

class DiagnosisService:
    """诊断流程编排：LangGraph状态机+QA引擎"""

    def __init__(self,db:AsyncSession):
        self.db=db
        self.conv_svc=ConversationService(db)
        self.qa_svc=QAService(db)

    async def run_diagnosis_step(
            self,
            conversation_id:int,
            user_input:str,
            user_id:int,
    )->dict:
        """执行一轮诊断。如果会话不存在，自动创建新会话"""

        #获取会话
        conv=await self.conv_svc.get(conversation_id)
        if not conv:
            return await self._first_turn(conversation_id,user_input,user_id)

        #保存用户消息
        await self.conv_svc.add_message(conv.id,"user",user_input)

        #从 MySQL 加载诊断状态
        key_facts=conv.key_facts or {}
        step_index=conv.step_index or 0
        diagnosis_plan=key_facts.get("_diagnosis_plan",[])

        graph=await _get_graph()
        config={"configurable":{"thread_id":str(conv.id)}}

        # 检查是否有 checkpoint：有则更新状态后从中断点恢复，无则传完整历史从头跑
        state_before=await graph.aget_state(config)
        if state_before:
            # aupdate_state 追加本轮用户消息 → ainvoke(None) 从中断点恢复执行 process_feedback
            await graph.aupdate_state(
                config,
                {"messages":[{"role":"user","content":user_input}]}
            )
            result=await graph.ainvoke(None, config)
        else:
            input_messages=[{"role":m.role,"content":m.content} for m in (conv.messages or [])]
            result=await graph.ainvoke(
                {"messages":input_messages,"key_facts":key_facts,
                 "diagnosis_plan":diagnosis_plan,"step_index":step_index,
                 "current_step":"intent_classify","resolved":False},
                config
            )

        #同步状态回MySQL
        kf=result.get("key_facts",{})
        kf["_diagnosis_plan"]=result.get("diagnosis_plan",[])
        await self.conv_svc.update_key_facts(conv.id,kf)
        await self.conv_svc.update_step(conv.id,result.get("step_index",0))

        current_node=result.get("current_step","")

        #提取本轮新增的 assistant 消息（排除 checkpoint 中已有的历史消息）
        skip_count=len(state_before.values.get("messages",[])) + 1 if state_before else 0
        last_assistant_msg=""
        for msg in reversed(result.get("messages",[])[skip_count:]):
            if msg.get("role")=="assistant":
                last_assistant_msg=msg["content"]
                break

        if not last_assistant_msg:
            last_assistant_msg=self._build_guidance_message(result)

        #保存assistant消息
        await self.conv_svc.add_message(conv.id,"assistant",last_assistant_msg)

        #判断是否结束
        if result.get("resolved"):
            await self.conv_svc.close(conv.id,"resolved")
        elif result.get("current_step")=="escalate":
            await self.conv_svc.close(conv.id,"escalated")

        return {
            "conversation_id":conv.id,
            "answer":last_assistant_msg,
            "status":conv.status,
            "step_index":result.get("step_index",0),
            "total_steps":len(result.get("diagnosis_plan",[])),
            "key_facts":result.get("key_facts",{}),
        }

    async def _first_turn(self,conversation_id:int,user_input:str,user_id)->dict:
        """首次对话：用QA引擎出第一轮回答，同时初始化LangGraph state"""

        # 先用 QA 引擎生成初始回答
        qa_result=await self.qa_svc.answer(user_input)

        # 创建会话
        conv = await self.conv_svc.create(
            user_id=user_id,
            title=user_input[:50],
        )

        # 保存用户消息
        await self.conv_svc.add_message(conv.id, "user", user_input)

        # 如果意图是故障诊断，初始化 LangGraph state 并生成排查计划
        if qa_result["intent"]["primary"] == "fault_diagnosis":
            graph = await _get_graph()
            config = {"configurable": {"thread_id": str(conv.id)}}

            input_state = {
                "messages": [
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": qa_result["answer"]},
                ],
                "key_facts": {
                    "device_model": qa_result["intent"].get("model_number"),
                    "symptom": user_input,
                    "checked": [],
                    "ruled_out": [],
                },
                "current_step": "intent_classify",
                "diagnosis_plan": [],
                "step_index": 0,
                "resolved": False,
            }

            result = await graph.ainvoke(input_state, config)

            # 将 diagnosis_plan 持久化到 key_facts
            kf = result.get("key_facts", {})
            kf["_diagnosis_plan"] = result.get("diagnosis_plan", [])
            await self.conv_svc.update_key_facts(conv.id, kf)

        # 保存 assistant 回答
        await self.conv_svc.add_message(
            conv.id, "assistant", qa_result["answer"],
            citations=qa_result.get("citations", []),
            confidence=qa_result.get("confidence"),
            intent=qa_result["intent"].get("primary"),
        )

        return {
            "conversation_id": conv.id,
            "answer": qa_result["answer"],
            "status": "active",
            "key_facts": {"symptom": user_input},
        }

    def _build_guidance_message(self, state: dict) -> str:
        plan = state.get("diagnosis_plan", [])
        idx = state.get("step_index", 0)
        if idx < len(plan):
            return f"### 排查第 {idx + 1}步\n\n{plan[idx]}\n\n请告诉我检查结果。"
        return "诊断已完成，请确认问题是否解决。"
