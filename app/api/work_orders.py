import json
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import get_current_user_id
from app.schemas.work_order import (
    WorkOrderCreate,
    WorkOrderUpdate,
    WorkOrderResponse,
    WorkOrderListResponse,
    WorkOrderListResult,
    WorkOrderNoteCreate,
    WorkOrderNoteResponse,
    WorkOrderTimelineItem,
)
from app.services.work_order_service import WorkOrderService

router = APIRouter()


@router.post("", response_model=WorkOrderResponse)
async def create_work_order(
    body: WorkOrderCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """手动创建工单"""
    svc = WorkOrderService(db)
    order = await svc.create(
        user_id=user_id,
        order_type=body.order_type,
        fault_description=body.fault_description,
        serial_number=body.serial_number,
        contact_info=body.contact_info,
        device_model=body.device_model,
        device_id=body.device_id,
        conversation_id=body.conversation_id,
    )
    await db.commit()
    return await _build_order_response(svc, order)


@router.get("", response_model=WorkOrderListResult)
async def list_work_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str | None = None,
    order_type: str | None = None,
    keyword: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取工单列表（支持筛选 + 分页）"""
    svc = WorkOrderService(db)
    skip = (page - 1) * page_size
    orders, total = await svc.list_all(
        skip=skip, limit=page_size, status=status, order_type=order_type, keyword=keyword
    )

    items = []
    for o in orders:
        device_model = await svc.get_device_model(o.device_id)
        assigned_name = await svc.get_user_name(o.assigned_to) if o.assigned_to else None
        items.append(WorkOrderListResponse(
            id=o.id,
            order_number=o.order_number,
            user_id=o.user_id,
            order_type=o.order_type,
            status=o.status,
            device_model=device_model,
            fault_description=o.fault_description,
            serial_number=o.serial_number,
            contact_info=o.contact_info,
            assigned_to=assigned_name,
            conversation_id=o.conversation_id,
            created_at=o.created_at,
            updated_at=o.updated_at,
        ))

    return WorkOrderListResult(items=items, total=total)


@router.get("/my", response_model=list[WorkOrderListResponse])
async def list_my_work_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的工单列表"""
    svc = WorkOrderService(db)
    orders = await svc.list_by_user(user_id=user_id, skip=skip, limit=limit)
    items = []
    for o in orders:
        device_model = await svc.get_device_model(o.device_id)
        assigned_name = await svc.get_user_name(o.assigned_to) if o.assigned_to else None
        items.append(WorkOrderListResponse(
            id=o.id,
            order_number=o.order_number,
            user_id=o.user_id,
            order_type=o.order_type,
            status=o.status,
            device_model=device_model,
            fault_description=o.fault_description,
            serial_number=o.serial_number,
            contact_info=o.contact_info,
            assigned_to=assigned_name,
            conversation_id=o.conversation_id,
            created_at=o.created_at,
            updated_at=o.updated_at,
        ))
    return items


@router.get("/{order_id}", response_model=WorkOrderResponse)
async def get_work_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取工单详情（含 timeline）"""
    svc = WorkOrderService(db)
    order = await svc.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="工单不存在")
    return await _build_order_response(svc, order)


@router.put("/{order_id}/status", response_model=WorkOrderResponse)
async def update_work_order_status(
    order_id: int,
    body: WorkOrderUpdate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """更新工单状态"""
    svc = WorkOrderService(db)
    order = await svc.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="工单不存在")

    if not body.status:
        raise HTTPException(status_code=400, detail="status 不能为空")

    updated = await svc.update_status(
        order_id=order_id,
        status=body.status,
        operator_id=user_id,
        resolution=body.resolution,
        assigned_to=body.assigned_to,
        note=body.note,
    )
    await db.commit()
    return await _build_order_response(svc, updated)


@router.post("/{order_id}/notes", response_model=WorkOrderNoteResponse)
async def add_work_order_note(
    order_id: int,
    body: WorkOrderNoteCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """添加工单备注"""
    svc = WorkOrderService(db)
    order = await svc.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="工单不存在")

    note = await svc.add_note(
        order_id=order_id,
        operator_id=user_id,
        content=body.content,
        action_type=body.action_type,
    )
    await db.commit()
    return WorkOrderNoteResponse.model_validate(note)


@router.post("/from-conversation/{conv_id}")
async def create_work_order_from_conversation(
    conv_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """从对话自动创建工单（信息提取 → 完整度校验 → 创建或追问）"""
    svc = WorkOrderService(db)
    order, missing, followup = await svc.create_from_conversation(conv_id, user_id)

    if order:
        await db.commit()
        resp = await _build_order_response(svc, order)
        return {
            "created": True,
            "order": resp.model_dump(mode="json"),
            "missing_fields": [],
            "followup_question": None,
        }
    else:
        return {
            "created": False,
            "order": None,
            "missing_fields": missing,
            "followup_question": followup,
        }


async def _build_order_response(svc: WorkOrderService, order) -> WorkOrderResponse:
    """构建工单详情响应，补充 device_model、timeline、conversation_summary"""
    device_model = await svc.get_device_model(order.device_id)
    timeline_data = await svc.build_timeline(order.notes or [])
    assigned_name = await svc.get_user_name(order.assigned_to) if order.assigned_to else None
    conv_summary = await svc.get_conversation_summary(order.conversation_id)

    return WorkOrderResponse(
        id=order.id,
        order_number=order.order_number,
        user_id=order.user_id,
        device_id=order.device_id,
        device_model=device_model,
        conversation_id=order.conversation_id,
        order_type=order.order_type,
        status=order.status,
        fault_description=order.fault_description,
        serial_number=order.serial_number,
        contact_info=order.contact_info,
        assigned_to=assigned_name,
        resolution=order.resolution,
        created_at=order.created_at,
        updated_at=order.updated_at,
        notes=[WorkOrderNoteResponse.model_validate(n) for n in (order.notes or [])],
        timeline=[WorkOrderTimelineItem(**t) for t in timeline_data],
        conversation_summary=conv_summary,
    )
