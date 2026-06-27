from datetime import datetime, date
from pydantic import BaseModel


# ── 设备型号 ──────────────────────────────────────────────

class DeviceModelInfoCreate(BaseModel):
    model_number: str
    product_series: str | None = None
    product_name: str | None = None
    category: str | None = None
    specifications: dict | None = None
    wiring_diagram: str | None = None
    firmware_versions: list[str] | None = None
    knowledge_base_docs: list[str] | None = None
    warranty_months: int = 24
    status: str = "active"


class DeviceModelInfoUpdate(BaseModel):
    product_series: str | None = None
    product_name: str | None = None
    category: str | None = None
    specifications: dict | None = None
    wiring_diagram: str | None = None
    firmware_versions: list[str] | None = None
    knowledge_base_docs: list[str] | None = None
    warranty_months: int | None = None
    status: str | None = None


class DeviceModelInfoResponse(BaseModel):
    id: int
    model_number: str
    product_series: str | None = None
    product_name: str | None = None
    category: str | None = None
    specifications: dict | None = None
    wiring_diagram: str | None = None
    firmware_versions: list[str] | None = None
    knowledge_base_docs: list[str] | None = None
    warranty_months: int
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── 设备序列号 ────────────────────────────────────────────

class DeviceSerialNumberCreate(BaseModel):
    serial_number: str
    model_number: str
    purchase_date: date | None = None
    purchase_channel: str | None = None
    warranty_start_date: date | None = None
    warranty_end_date: date | None = None
    customer_info: dict | None = None
    status: str = "active"


class DeviceSerialNumberUpdate(BaseModel):
    purchase_channel: str | None = None
    warranty_start_date: date | None = None
    warranty_end_date: date | None = None
    customer_info: dict | None = None
    status: str | None = None


class DeviceSerialNumberResponse(BaseModel):
    id: int
    serial_number: str
    model_number: str
    purchase_date: date | None = None
    purchase_channel: str | None = None
    warranty_start_date: date | None = None
    warranty_end_date: date | None = None
    customer_info: dict | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── 综合查询 ──────────────────────────────────────────────

class DeviceQueryRequest(BaseModel):
    query: str  # 型号或序列号


class DeviceQueryResponse(BaseModel):
    model_info: DeviceModelInfoResponse | None = None
    serial_info: DeviceSerialNumberResponse | None = None
    warranty_status: dict | None = None  # {status, start_date, end_date, remaining_days}
