import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device_info import DeviceModelInfo, DeviceSerialNumber
from app.schemas.device_info import (
    DeviceModelInfoCreate,
    DeviceModelInfoUpdate,
    DeviceSerialNumberCreate,
    DeviceSerialNumberUpdate,
    DeviceQueryResponse,
    DeviceModelInfoResponse,
    DeviceSerialNumberResponse,
)

logger = logging.getLogger(__name__)


class DeviceInfoService:
    """设备信息查询服务 —— 保修查询流程的核心工具"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 型号 CRUD ─────────────────────────────────────────

    async def get_model_by_number(self, model_number: str) -> DeviceModelInfo | None:
        r = await self.db.execute(
            select(DeviceModelInfo).where(DeviceModelInfo.model_number == model_number)
        )
        return r.scalar_one_or_none()

    async def create_model(self, data: DeviceModelInfoCreate) -> DeviceModelInfo:
        obj = DeviceModelInfo(**data.model_dump())
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update_model(
        self, model_number: str, data: DeviceModelInfoUpdate
    ) -> DeviceModelInfo | None:
        obj = await self.get_model_by_number(model_number)
        if not obj:
            return None
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete_model(self, model_number: str) -> bool:
        obj = await self.get_model_by_number(model_number)
        if not obj:
            return False
        await self.db.delete(obj)
        await self.db.flush()
        return True

    async def search_models(self, keyword: str) -> list[DeviceModelInfo]:
        r = await self.db.execute(
            select(DeviceModelInfo).where(
                DeviceModelInfo.model_number.like(f"%{keyword}%")
            )
        )
        return list(r.scalars().all())

    async def get_firmware_versions(self, model_number: str) -> list[str] | None:
        obj = await self.get_model_by_number(model_number)
        if not obj:
            return None
        return obj.firmware_versions or []

    # ── 序列号 CRUD ────────────────────────────────────────

    async def get_serial_by_number(
        self, serial_number: str
    ) -> DeviceSerialNumber | None:
        r = await self.db.execute(
            select(DeviceSerialNumber).where(
                DeviceSerialNumber.serial_number == serial_number
            )
        )
        return r.scalar_one_or_none()

    async def create_serial(self, data: DeviceSerialNumberCreate) -> DeviceSerialNumber:
        obj = DeviceSerialNumber(**data.model_dump())
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update_serial(
        self, serial_number: str, data: DeviceSerialNumberUpdate
    ) -> DeviceSerialNumber | None:
        obj = await self.get_serial_by_number(serial_number)
        if not obj:
            return None
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    # ── 综合查询（工具调用入口）──────────────────────────────

    async def query_device_info(self, query: str) -> DeviceQueryResponse:
        """
        自动识别查询类型（序列号优先），返回型号信息 + 序列号信息 + 保修状态。
        """
        model_info = None
        serial_info = None
        warranty_status = None

        # 1. 先按序列号精确匹配
        serial = await self.get_serial_by_number(query)
        if serial:
            serial_info = self._serial_to_response(serial)
            # 关联查型号
            model = await self.get_model_by_number(serial.model_number)
            if model:
                model_info = self._model_to_response(model)
            warranty_status = self._compute_warranty_status(serial, model)
            return DeviceQueryResponse(
                model_info=model_info,
                serial_info=serial_info,
                warranty_status=warranty_status,
            )

        # 2. 按型号精确匹配
        model = await self.get_model_by_number(query)
        if model:
            return DeviceQueryResponse(
                model_info=self._model_to_response(model),
            )

        # 3. 模糊搜索型号
        models = await self.search_models(query)
        if models:
            return DeviceQueryResponse(
                model_info=self._model_to_response(models[0]),
            )

        # 未找到
        return DeviceQueryResponse()

    # ── 内部工具方法 ───────────────────────────────────────

    def _model_to_response(self, obj: DeviceModelInfo) -> DeviceModelInfoResponse:
        return DeviceModelInfoResponse.model_validate(obj)

    def _serial_to_response(self, obj: DeviceSerialNumber) -> DeviceSerialNumberResponse:
        return DeviceSerialNumberResponse.model_validate(obj)

    def _compute_warranty_status(
        self,
        serial: DeviceSerialNumber,
        model: DeviceModelInfo | None,
    ) -> dict | None:
        """计算保修状态，返回 {status, start_date, end_date, remaining_days}"""
        start = serial.warranty_start_date
        end = serial.warranty_end_date

        # 如果没有存 warranty_end_date，用 warranty_start_date + 模型保修月数推算
        if not end and start and model:
            from dateutil.relativedelta import relativedelta
            end = start + relativedelta(months=model.warranty_months)

        if not start and not end:
            return None

        today = date.today()
        if end:
            remaining = (end - today).days
            status = "active" if remaining > 0 else "expired"
        else:
            remaining = None
            status = "unknown"

        return {
            "status": status,
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end else None,
            "remaining_days": remaining,
        }


# ── LLM 工具定义 ──────────────────────────────────────────

DEVICE_QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "query_device_info",
        "description": (
            "查询海康威视设备的型号信息、序列号信息和保修状态。"
            "当用户询问设备参数、保修状态、是否在保、设备规格、固件版本等问题时调用此工具。"
            "输入可以是设备型号（如 DS-2CD2T47G2-L）或序列号（S/N码，如 C202301000001）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "设备型号或序列号，例如 'DS-7608NI-K2' 或 'C202301000001'"
                }
            },
            "required": ["query"]
        }
    }
}


async def execute_device_query_tool(arguments: dict, db) -> str:
    """执行 query_device_info 工具，返回 JSON 字符串结果。"""
    svc = DeviceInfoService(db)
    query = arguments.get("query", "")
    result = await svc.query_device_info(query)
    return result.model_dump_json()
