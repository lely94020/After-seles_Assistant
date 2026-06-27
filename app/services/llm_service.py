import asyncio
import json
import logging
from typing import AsyncGenerator, Callable, Awaitable

import dashscope

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是海康威视售后技术支持专家。请根据以下检索到的知识库内容回答用户问题。

规则：
1.仅基于提供的知识库内容回答，不要编造信息
2.每个关键事实后标注引用来源编号，如[1]、[2]
3.如果知识库内容不足以回答问题，诚实说明“当前知识库信息有限，建议联系技术支持”
4.涉及强电、防爆、高空等安全操作时，开头附加 ⚠️ 安全提示
5.回答最后列出“参考文档”清单

输出格式：
-使用Markdown格式
-如有操作步骤，使用有序列表
-如有参数表，使用表格
"""


def _build_prompt(query: str, retrieved_docs: list[dict]) -> str:
    """
    将用户的原始查询 (query) 和检索到的背景文档 (retrieved_docs) 组合，
    构建出给大模型的 Prompt，同时提取出引用信息 (refs)
    """
    context_parts = []
    refs = []
    for i, doc in enumerate(retrieved_docs, 1):
        context_parts.append(f"[{i}] {doc['content']}")
        refs.append({
            "index": i,
            "chunk_id": doc["chunk_id"],
            "document_id": doc["document_id"],
            "parent_title": doc.get("parent_title", "")
        })

    context = "\n\n---\n\n".join(context_parts)
    return f"# 检索到的知识库内容\n\n{context}\n\n# 参考编号映射\n{json.dumps(refs, ensure_ascii=False)}\n\n# 用户问题\n\n{query}", refs


class LLMService:
    """大模型回答生成服务"""

    MODEL = "qwen-max"

    @staticmethod
    async def generate(
            query: str,
            retrieved_docs: list[dict],
    ) -> tuple[str, list[dict]]:
        """非流式生成回答，返回（回答文本，引用列表）"""
        prompt, refs = _build_prompt(query, retrieved_docs)

        resp = await asyncio.to_thread(
            dashscope.Generation.call,
            model=LLMService.MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            api_key=settings.DASHSCOPE_API_KEY,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"大模型调用失败：{resp.message}")

        answer = resp.output.text
        return answer, refs

    @staticmethod
    async def generate_stream(
            query: str,
            retrieved_docs: list[dict],
    ) -> AsyncGenerator[str, None]:
        prompt, refs = _build_prompt(query, retrieved_docs)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        async for token in LLMService._stream_llm(messages):
            yield token

        # 最后推送引用信息
        yield json.dumps({"citations": refs}, ensure_ascii=False)

    # ── 工具调用支持 ───────────────────────────────────────

    @staticmethod
    async def generate_with_tools(
        query: str,
        retrieved_docs: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, dict], Awaitable[str]],
        system_prompt: str | None = None,
    ) -> tuple[str, list[dict], list[dict]]:
        """
        非流式工具调用循环（最多 3 轮）。
        返回 (answer_text, citations, tool_call_log)。
        tool_executor 签名: async (tool_name, arguments) -> str
        """
        prompt, refs = _build_prompt(query, retrieved_docs)
        sys_prompt = system_prompt or SYSTEM_PROMPT
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt},
        ]
        tool_log = []
        MAX_TOOL_ROUNDS = 3

        for round_idx in range(MAX_TOOL_ROUNDS):
            resp = await asyncio.to_thread(
                dashscope.Generation.call,
                model=LLMService.MODEL,
                messages=messages,
                tools=tools,
                api_key=settings.DASHSCOPE_API_KEY,
            )

            if resp.status_code != 200:
                raise RuntimeError(f"大模型调用失败：{resp.message}")

            choice = resp.output.choices[0]
            assistant_msg = choice.message

            # 无 tool_calls → 最终回答
            try:
                has_tool_calls = bool(assistant_msg.tool_calls)
            except (KeyError, AttributeError):
                has_tool_calls = False
            if not has_tool_calls:
                logger.info(f"工具调用完成，共 {round_idx} 轮工具调用")
                return assistant_msg.content or "", refs, tool_log

            # 有 tool_calls → 追加 assistant 消息并执行工具
            messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": assistant_msg.tool_calls,
            })

            for tc in assistant_msg.tool_calls:
                func_name = tc["function"]["name"]
                func_args = json.loads(tc["function"]["arguments"])
                logger.info(f"LLM 请求工具调用: {func_name}({func_args})")

                result = await tool_executor(func_name, func_args)
                logger.info(f"工具 {func_name} 返回 {len(result)} 字符")

                tool_log.append({
                    "name": func_name,
                    "arguments": func_args,
                    "result": result,
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        # 超过最大轮数，返回当前内容
        logger.warning(f"工具调用达到最大轮数 {MAX_TOOL_ROUNDS}")
        return assistant_msg.content or "", refs, tool_log

    @staticmethod
    async def generate_stream_with_tools(
        query: str,
        retrieved_docs: list[dict],
        tools: list[dict],
        tool_executor: Callable[[str, dict], Awaitable[str]],
        system_prompt: str | None = None,
        status_message: str = "正在查询设备信息...\n\n",
    ) -> AsyncGenerator[str, None]:
        """
        流式工具调用。
        Phase 1: 非流式检测 tool_calls
        Phase 2: 如果有 tool_calls → yield status → 执行工具
        Phase 3: 流式生成最终回答
        如果无 tool_calls: 直接流式生成
        最后 yield 一个 JSON citations 字符串。
        """
        prompt, refs = _build_prompt(query, retrieved_docs)
        sys_prompt = system_prompt or SYSTEM_PROMPT
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt},
        ]

        # Phase 1: 非流式调用检测 tool_calls
        resp = await asyncio.to_thread(
            dashscope.Generation.call,
            model=LLMService.MODEL,
            messages=messages,
            tools=tools,
            api_key=settings.DASHSCOPE_API_KEY,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"大模型调用失败：{resp.message}")

        choice = resp.output.choices[0]
        assistant_msg = choice.message

        try:
            has_tool_calls = bool(assistant_msg.tool_calls)
        except (KeyError, AttributeError):
            has_tool_calls = False
        if has_tool_calls:
            # Phase 2: yield status + 执行工具
            yield status_message

            messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": assistant_msg.tool_calls,
            })

            for tc in assistant_msg.tool_calls:
                func_name = tc["function"]["name"]
                func_args = json.loads(tc["function"]["arguments"])
                logger.info(f"LLM 请求工具调用: {func_name}({func_args})")

                result = await tool_executor(func_name, func_args)
                logger.info(f"工具 {func_name} 返回 {len(result)} 字符")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # Phase 3: 流式生成最终回答
            async for token in LLMService._stream_llm(messages):
                yield token

        else:
            # 无 tool_calls → 直接流式生成
            async for token in LLMService._stream_llm(messages):
                yield token

        yield json.dumps({"citations": refs}, ensure_ascii=False)

    @staticmethod
    async def _stream_llm(messages: list[dict]) -> AsyncGenerator[str, None]:
        """内部流式生成辅助，从消息列表流式输出 token。"""
        queue: asyncio.Queue = asyncio.Queue()

        def _run():
            try:
                responses = dashscope.Generation.call(
                    model=LLMService.MODEL,
                    messages=messages,
                    stream=True,
                    incremental_output=True,
                    api_key=settings.DASHSCOPE_API_KEY,
                )
                for chunk in responses:
                    if chunk.status_code == 200 and chunk.output:
                        # DashScope 工具调用后，text 可能为 None，内容在 choices[0].message.content
                        text = chunk.output.text
                        if not text and chunk.output.choices:
                            text = chunk.output.choices[0].message.content
                        if text:
                            queue.put_nowait(("token", text))
                queue.put_nowait(("done", None))
            except Exception as e:
                queue.put_nowait(("error", str(e)))

        task = asyncio.create_task(asyncio.to_thread(_run))

        while True:
            try:
                msg_type, payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                if msg_type == "done":
                    break
                elif msg_type == "error":
                    raise RuntimeError(payload)
                elif msg_type == "token":
                    yield payload
            except asyncio.TimeoutError:
                raise RuntimeError("大模型调用超时")

        await task