import asyncio
import json
import re
import time
import logging

import dashscope

from app.config import settings

logger = logging.getLogger(__name__)

INTENT_PROMPT = """你是海康威视售后技术支持的意图分类器。
  根据用户输入，输出 JSON 格式的意图分类结果。

  意图类别：
  - fault_diagnosis: 设备故障排查（离线、画面异常、配置故障、硬件故障等）
  - product_inquiry: 产品参数/功能/选型咨询
  - warranty_service: 保修查询或报修申请
  - sdk_integration: SDK/API/协议技术问题
  - unclear: 无法判断或闲聊

  要求：
  1. 如果用户消息中包含设备型号（如 DS-开头的编号），提取到 model_number 字段
  2. 如果用户消息中包含设备序列号（S/N码，格式如 C202301000001 或 DS7608NI20230815001），提取到 serial_number 字段
  3. 如果用户同时有多个意图（如"开不了机，顺便查保修"），标记 has_secondary_request 为 true 并给出 secondary_intent
  4. confidence 为 0~1 之间的数值

  示例1：
  用户："DS-2CD3T86 画面模糊怎么办"
  输出：{"primary_intent": "fault_diagnosis", "secondary_intent": null, "model_number": "DS-2CD3T86", "serial_number": null, "has_secondary_request": false, "confidence": 0.95}

  示例2：
  用户："我的 NVR 开不了机，顺便查查保修"
  输出：{"primary_intent": "fault_diagnosis", "secondary_intent": "warranty_service", "model_number": null, "serial_number": null, "has_secondary_request": true, "confidence": 0.90}

  示例3：
  用户："DS-7608N-K2 支持多少路回放"
  输出：{"primary_intent": "product_inquiry", "secondary_intent": null, "model_number": "DS-7608N-K2", "serial_number": null, "has_secondary_request": false, "confidence": 0.95}

  示例4：
  用户："帮我查一下序列号 C202301000001 的保修"
  输出：{"primary_intent": "warranty_service", "secondary_intent": null, "model_number": null, "serial_number": "C202301000001", "has_secondary_request": false, "confidence": 0.95}

  用户输入：{user_input}
  输出："""

class IntentService:

    @staticmethod
    async def classify(user_input:str)->dict:
        """意图分类"""
        t0=time.time()

        prompt=INTENT_PROMPT.replace("{user_input}",user_input)

        resp = await asyncio.to_thread(
            dashscope.Generation.call,
            model="qwen-turbo",
            messages=[{"role": "user", "content": prompt}],
            result_format="message",
            api_key=settings.DASHSCOPE_API_KEY,
        )

        latency_ms=int((time.time()-t0)*1000)
        logger.info(f"意图分类耗时{latency_ms}ms")

        if resp.status_code != 200:
            logger.warning(f"意图分类失败: {resp.message}，降级为 unclear")
            return {
                "primary_intent": "unclear",
                  "secondary_intent": None,
                  "model_number": None,
                  "serial_number": None,
                  "has_secondary_request": False,
                  "confidence": 0.0,
            }

        #提取JSON
        raw=resp.output.choices[0].message.content
        try:
            result=json.loads(raw)
        except json.JSONDecodeError:
            #尝试从文本中提取JSON
            match=re.search(r"\{.*\}",raw,re.DOTALL)
            if match:
                result=json.loads(match.group())
            else:
                logger.warning(f"意图分类输出不是有效JSON:{raw}")
                return {
                    "primary_intent":"unclear",
                    "secondary_intent": None,
                    "model_number": None,
                    "serial_number": None,
                    "has_secondary_request": False,
                    "confidence": 0.0,
                }

        return {
            "primary_intent":result.get("primary_intent","unclear"),
            "secondary_intent":result.get("secondary_intent"),
            "model_number":result.get("model_number"),
            "serial_number":result.get("serial_number"),
            "has_secondary_request":result.get("has_secondary_request",False),
            "confidence":result.get("confidence",0.0)
        }
