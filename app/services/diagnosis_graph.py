import logging
from typing import Literal

import dashscope
from langgraph.graph import StateGraph,END
from langgraph.checkpoint.redis import RedisSaver
from typing import TypedDict,Annotated
import operator

from app.core.redis_client import get_redis
from app.config import settings

logger=logging.getLogger(__name__)

#State定义
class DiagnosisState(TypedDict):
    messages:Annotated[list,operator.add]   #消息追加
    key_facts:dict
    current_step:str    #当前节点名称
    diagnosis_plan:list[str]    #排查步骤列表
    step_index:int
    resolved:bool

#节点函数
DIAGNOSIS_SYSTEM_PROMPT="""你是海康威视售后故障诊断专家。你正在和设备运维人员逐步排查一个问题。
                                                                                 
  ## 当前已知信息                                                                
  {key_facts}
                                                                                 
  ## 排查计划                                                                    
  {plan}                                                                         
                                                                                 
  ## 当前步骤：第 {step} 步 / 共 {total} 步                                      
                                                                                 
  {step_instruction}                                                             
                                                                               
  请：                                                                           
  1. 仅引导当前这一步排查，不要跳到后续步骤                                    
  2. 用一个具体的问题询问用户，引导用户提供关键信息                              
  3. 引用知识库中的技术依据（如有）                                              
  4. 不要问用户已经回答过的问题（参考"已排查"/"已排除"）
"""

def _format_key_facts(state:DiagnosisState)->str:
    kf=state.get("key_facts",{})
    lines=[]
    for k,v in kf.items():
        if isinstance(v,list):  #判断v是否为列表
            lines.append(f"-{k}:{','.join(str(x)for x in v)}")
        else:
            lines.append(f"-{k}:{v}")
    return "\n".join(lines) if lines else "暂无"

async def intent_classify_node(state:DiagnosisState)->dict:
    """节点1:意图分类+问题分类（复用IntentService）"""
    from app.services.intent_service import IntentService
    #从 state 的 messages 列表中取出最后一条消息的 content 作为用户的当前输入 user_msg
    user_msg=state["messages"][-1]["content"] if state["messages"]else""

    result=await IntentService.classify(user_msg)

    #初始化key_facts
    kf=state.get("key_facts",{})
    if result.get("model_number"):
        kf["device_model"]=result["model_number"]
    kf["symptom"]=user_msg
    kf.setdefault("checked",[]) #确保列表存在，若不存在则初始化为空列表
    kf.setdefault("ruled_out",[])

    return {
        "key_facts":kf,
        "current_step":"intent_classify",
        "step_index":0,
        "resolved":False,
    }

async def generate_plan_node(state:DiagnosisState)->dict:
    """节点2:根据key_facts生成排查计划"""
    kf=state.get("key_facts",{})
    symptom=kf.get("symptom","")

    #调用LLM生成排查步骤列表
    import asyncio,dashscope

    prompt=f"""你是海康威视售后故障诊断专家。根据以下信息，生成一个3~5步的排查计划。      
  每个步骤是一句话描述，按从简单到复杂的顺序排列。                               
                                                                                 
  设备型号：{kf.get('device_model', '未知')}                                     
  故障现象：{symptom}                                                            
  已知信息：{_format_key_facts(state)}                                           
                                                                                 
  输出格式：每行一个步骤，用"1. 2. 3."编号。不要输出其他内容。
"""
    #使用 asyncio.to_thread 将同步的 dashscope.Generation.call转换为异步执行
    resp=await asyncio.to_thread(
        dashscope.Generation.call,
        model="qwen-turbo",
        messages=[{"role":"user","content":prompt}],
        api_key=settings.DASHSCOPE_API_KEY,
    )

    raw=resp.output.choices[0].message.content if resp.status_code==200 else ""
    #解析步骤
    import re
    steps=re.findall(r"\d+\.\s*(.+)",raw)   # 匹配出带编号的步骤内容
    if not steps:
        steps=["确认故障现象","检查设备连接状态","查看设备日志","逐步排除硬件故障","升级固件或联系技术支持"]

    return {
        "diagnosis_plan":steps,
        "step_index":0,
        "current_step":"generate_plan",
    }

async def ask_step_node(state:DiagnosisState)->dict:
    """节点3:向用户输出当前排查步骤的引导问题"""
    plan=state.get("diagnosis_plan",[])
    idx=state.get("step_index",0)
    if idx >= len(plan):
        return {"current_step":"ask_step","resolved":False}

    current_instruction=plan[idx]
    prompt=DIAGNOSIS_SYSTEM_PROMPT.format(
        key_facts=_format_key_facts(state),
        plan="\n".join(f"{i+1}.{s}" for i,s in enumerate(plan)),
        step=idx+1,
        total=len(plan),
        step_instruction=f"请引导用户执行：{current_instruction}",
    )
    # 这里 answer_node 只是退出了等待用户输入，并不调用 LLM
    # 实际调用由 qa_service 在收集用户反馈后的下一轮触发
    return {
        "current_step":"ask_step",
        "messages":[{"role":"system","content":prompt}],
    }

async def process_feedback_node(state:DiagnosisState)->dict:
    """节点4:处理用户反馈，更新key_facts，判断下一步"""
    from app.services.llm_service import LLMService

    #取最后一条用户信息作为反馈
    user_feedback=""
    for msg in reversed(state.get("messages",[])):
        if msg.get("role")=="user":
            user_feedback=msg["content"]
            break

    kf = state.get("key_facts",{})

    #用LLM从用户反馈中提取关键信息更新key_facts
    extract_prompt=f"""从以下用户反馈中提取关键诊断信息，更新JSON。不要编造。
    当前已记录：
    {_format_key_facts(state)}
    用户反馈：{user_feedback}
    请返回JSON（只返回JSON，无其他文字）：
    {{
        "update_key_facts":{{"key":"value"}},
        "append_checked":["已确认的事实"],
        "append_ruled_out":["已排除的可能"],
        "is_resolved":False,
        "resolution":""
    }}
"""
    import asyncio,json
    resp=await asyncio.to_thread(
        dashscope.Generation.call,
        model="qwen-turbo",
        messages=[{"role":"user","content":extract_prompt}],
        api_key=settings.DASHSCOPE_API_KEY
    )

    try:
        raw=resp.output.choices[0].message.content
        parsed=json.loads(raw)if raw else {}
    except json.JSONDecodeError:
        parsed={}

    #更新key_facts
    if parsed.get("update_key_facts"):
        kf.update(parsed["update_key_facts"])
    checked=kf.get("checked",[])

    if parsed.get("append_checked"):
        checked.extend(parsed["append_checked"])
    ruled_out=kf.get("ruled_out",[])
    if parsed.get("append_ruled_out"):
        ruled_out.extend(parsed["append_ruled_out"])
    kf["checked"]=checked
    kf["ruled_out"]=ruled_out

    return {
        "key_facts":kf,
        "resolved":parsed.get("is_resolved",False),
        "current_step":"process_feedback"
    }

def route_after_feedback(state:DiagnosisState)->Literal["continue","resolve","escalate"]:
    """条件路由：根据用户反馈决定下一步"""
    if state.get("resolved"):
        return "resolve"

    plan=state.get("diagnosis_plan",[])
    idx=state.get("step_index",0)

    if idx+1>len(plan):
        return "escalate"   #所有步骤执行完还没解决->转人工

    return "continue"

async def resolve_node(state:DiagnosisState)->dict:
    """节点5:给出最终解决方案"""
    return {
        "current_step":"resolve",
        "resolved":True,
        "messages":[{
            "role":"assistant",
            "content":"##诊断完成\n\n"
            "根据排查过程，问题已定位。以下是完整的诊断结论和建议方案。\n\n"
            f"##关键发现\n{_format_key_facts(state)}\n\n"
            "如有后续问题，欢迎随时咨询。"
        }],
    }

async def escalate_node(state:DiagnosisState)->dict:
    """节点6:转人工+建议创建工单"""
    return{
        "current_step":"escalate",
        "resolved":False,
        "messages":[{
            "role":"assistant",
            "content":"##建议转人工处理\n\n"
            "经过多轮排查，自动诊断未能完全定位问题。建议您：\n\n"  
            "**联系海康技术支持**：400-800-5998\n"                 
            f"### 排查摘要\n{_format_key_facts(state)}"
        }],
    }

#-------构建Graph----------
async def build_diagnosis_graph():
    """构建并返回编译后的诊断图(带Redis checkpoint)"""
    redis_client=await get_redis()

    #创建RedisSaver用于checkpoint持久化
    saver=RedisSaver(redis_client)

    graph=StateGraph(DiagnosisState)
    graph.add_node("intent_classify", intent_classify_node) #意图分类，识别用户输入的核心意图
    graph.add_node("generate_plan", generate_plan_node) #生成计划，根据意图制定排查或解决的步骤计划
    graph.add_node("ask_step", ask_step_node)   #询问步骤，向用户提出具体的排查问题或引导操作
    graph.add_node("process_feedback", process_feedback_node)   #处理反馈，接收并分析用户的回复
    graph.add_node("resolve", resolve_node)     #解决，当问题确认解决时执行的操作
    graph.add_node("escalate", escalate_node)   #升级，当系统无法解决或超出范围时，转交人工处理

    graph.set_entry_point("intent_classify")
    graph.add_edge("intent_classify","generate_plan")
    graph.add_edge("generate_plan","ask_step")
    graph.add_conditional_edges(
        "process_feedback",
        route_after_feedback,
        {
            "continue":"ask_step",
            "resolve":"resolve",
            "escalate":"escalate",
        },
    )
    graph.add_edge("ask_step","process_feedback")
    graph.add_edge("resolve",END)
    graph.add_edge("escalate",END)

    return graph.compile(checkpointer=saver)