import asyncio
import json
from typing import AsyncGenerator

import dashscope

from app.config import settings

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

        answer = resp.output.choices[0].message.content
        return answer, refs

    @staticmethod
    async def generate_stream(
            query: str,
            retrieved_docs: list[dict],
    ) -> AsyncGenerator[str, None]:
        """流式生成回答，逐token yield"""
        #TODO:在 generate_stream 中，await Conversation.acall(...) 会一直阻塞，直到流式输出全部完成，
        # 期间通过回调收集所有 chunks。这意味着它并没有真正实现逐 token 的实时流式推送。调用方必须等模型全部生成完，才能开始遍历 yield。
        # 如果要实现真正的实时流式推送，应该使用 DashScope 提供的 async for 异步迭代器来逐块读取并 yield，而不是使用回调收集。
        prompt, refs = _build_prompt(query, retrieved_docs)

        responses = []

        def callback(chunk):
            responses.append(chunk)

        await asyncio.to_thread(
            dashscope.Generation.call,
            model=LLMService.MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            callback=callback,
            api_key=settings.DASHSCOPE_API_KEY,
        )

        full_answer = ""
        for r in responses:
            if r.status_code == 200:
                token = r.output.choices[0].message.content
                full_answer += token
                yield token

        yield json.dumps({"citations": refs}, ensure_ascii=False)
