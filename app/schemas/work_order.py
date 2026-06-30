from datetime import datetime
from pydantic import BaseModel, field_serializer

from app.core.data_mask import mask_contact_info


class WorkOrderCreate(BaseModel):
    order_type: str  # fault_repair | general_inquiry | installation | other
    fault_description: str | None = None
    serial_number: str | None = None
    contact_info: str | None = None
    device_model: str | None = None  # 前端传设备型号字符串，后端自动查找 device_id
    device_id: int | None = None
    conversation_id: int | None = None


class WorkOrderUpdate(BaseModel):
    status: str | None = None  # pending | assigned | in_progress | completed | cancelled
    resolution: str | None = None
    assigned_to: int | None = None
    note: str | None = None  # 前端传的备注信息


class WorkOrderNoteResponse(BaseModel):
    id: int
    operator_id: int
    content: str
    action_type: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkOrderTimelineItem(BaseModel):
    status: str | None = None
    note: str
    operator: str
    created_at: datetime | None = None


class WorkOrderResponse(BaseModel):
    id: int
    order_number: str
    user_id: int
    device_id: int | None = None
    device_model: str | None = None
    conversation_id: int | None = None
    order_type: str
    status: str
    fault_description: str | None = None
    serial_number: str | None = None
    contact_info: str | None = None
    assigned_to: str | None = None
    resolution: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    notes: list[WorkOrderNoteResponse] = []
    timeline: list[WorkOrderTimelineItem] = []
    conversation_summary: str | None = None

    model_config = {"from_attributes": True}

    @field_serializer("contact_info")
    @classmethod
    def _mask_contact(cls, v: str | None) -> str | None:
        return mask_contact_info(v)


class WorkOrderListResponse(BaseModel):
    id: int
    order_number: str
    user_id: int
    order_type: str
    status: str
    device_model: str | None = None
    fault_description: str | None = None
    serial_number: str | None = None
    contact_info: str | None = None
    assigned_to: str | None = None
    conversation_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_serializer("contact_info")
    @classmethod
    def _mask_contact(cls, v: str | None) -> str | None:
        return mask_contact_info(v)


class WorkOrderListResult(BaseModel):
    items: list[WorkOrderListResponse]
    total: int


class WorkOrderNoteCreate(BaseModel):
    content: str
    action_type: str = "note"  # status_change | note | assignment | resolution


class ExtractedFields(BaseModel):
    device_model: str | None = None
    serial_number: str | None = None
    fault_description: str | None = None
    contact_info: str | None = None
    order_type: str = "fault_repair"
