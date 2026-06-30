from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import CurrentUser, get_current_user, require_role
from app.services.device_info_service import DeviceInfoService
from app.schemas.device_info import (
    DeviceModelInfoCreate,
    DeviceModelInfoUpdate,
    DeviceModelInfoResponse,
    DeviceSerialNumberCreate,
    DeviceSerialNumberUpdate,
    DeviceSerialNumberResponse,
    DeviceQueryRequest,
    DeviceQueryResponse,
)

router = APIRouter(prefix="/device-info", tags=["设备信息"])

# 读操作：所有已认证用户
_READ_DEP = Depends(get_current_user)
# 写操作：仅管理员
_WRITE_DEP = Depends(require_role("cs_manager", "kb_admin"))


# ── 设备型号 ──────────────────────────────────────────────

@router.post("/models", response_model=DeviceModelInfoResponse)
async def create_device_model(
    device_data: DeviceModelInfoCreate,
    user: CurrentUser = _WRITE_DEP,
    db: AsyncSession = Depends(get_db),
):
    """创建设备型号信息"""
    try:
        svc = DeviceInfoService(db)
        return await svc.create_model(device_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/models/{model_number}", response_model=DeviceModelInfoResponse)
async def get_device_model(
    model_number: str,
    user: CurrentUser = _READ_DEP,
    db: AsyncSession = Depends(get_db),
):
    """根据型号获取设备信息"""
    svc = DeviceInfoService(db)
    device = await svc.get_model_by_number(model_number)
    if not device:
        raise HTTPException(status_code=404, detail="Device model not found")
    return device


@router.put("/models/{model_number}", response_model=DeviceModelInfoResponse)
async def update_device_model(
    model_number: str,
    device_data: DeviceModelInfoUpdate,
    user: CurrentUser = _WRITE_DEP,
    db: AsyncSession = Depends(get_db),
):
    """更新设备型号信息"""
    svc = DeviceInfoService(db)
    device = await svc.update_model(model_number, device_data)
    if not device:
        raise HTTPException(status_code=404, detail="Device model not found")
    return device


@router.delete("/models/{model_number}")
async def delete_device_model(
    model_number: str,
    user: CurrentUser = _WRITE_DEP,
    db: AsyncSession = Depends(get_db),
):
    """删除设备型号信息"""
    svc = DeviceInfoService(db)
    if not await svc.delete_model(model_number):
        raise HTTPException(status_code=404, detail="Device model not found")
    return {"message": "Device model deleted successfully"}


@router.get("/models/search/{model_number}", response_model=list[DeviceModelInfoResponse])
async def search_devices_by_model(
    model_number: str,
    user: CurrentUser = _READ_DEP,
    db: AsyncSession = Depends(get_db),
):
    """根据型号模糊搜索设备"""
    svc = DeviceInfoService(db)
    return await svc.search_models(model_number)


@router.get("/models/{model_number}/firmware", response_model=list[str])
async def get_firmware_versions_by_model(
    model_number: str,
    user: CurrentUser = _READ_DEP,
    db: AsyncSession = Depends(get_db),
):
    """根据型号获取固件版本列表"""
    svc = DeviceInfoService(db)
    versions = await svc.get_firmware_versions(model_number)
    if not versions:
        raise HTTPException(status_code=404, detail="Firmware versions not found")
    return versions


# ── 设备序列号 ────────────────────────────────────────────

@router.post("/serials", response_model=DeviceSerialNumberResponse)
async def create_device_serial_number(
    serial_data: DeviceSerialNumberCreate,
    user: CurrentUser = _WRITE_DEP,
    db: AsyncSession = Depends(get_db),
):
    """创建设备序列号信息"""
    try:
        svc = DeviceInfoService(db)
        return await svc.create_serial(serial_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/serials/{serial_number}", response_model=DeviceSerialNumberResponse)
async def get_device_serial_number(
    serial_number: str,
    user: CurrentUser = _READ_DEP,
    db: AsyncSession = Depends(get_db),
):
    """根据序列号获取设备信息"""
    svc = DeviceInfoService(db)
    serial = await svc.get_serial_by_number(serial_number)
    if not serial:
        raise HTTPException(status_code=404, detail="Device serial number not found")
    return serial


@router.put("/serials/{serial_number}", response_model=DeviceSerialNumberResponse)
async def update_device_serial_number(
    serial_number: str,
    serial_data: DeviceSerialNumberUpdate,
    user: CurrentUser = _WRITE_DEP,
    db: AsyncSession = Depends(get_db),
):
    """更新设备序列号信息"""
    svc = DeviceInfoService(db)
    serial = await svc.update_serial(serial_number, serial_data)
    if not serial:
        raise HTTPException(status_code=404, detail="Device serial number not found")
    return serial


# ── 综合查询 ──────────────────────────────────────────────

@router.post("/query", response_model=DeviceQueryResponse)
async def query_device_info(
    query_data: DeviceQueryRequest,
    user: CurrentUser = _READ_DEP,
    db: AsyncSession = Depends(get_db),
):
    """查询设备信息，支持按型号或序列号查询"""
    svc = DeviceInfoService(db)
    result = await svc.query_device_info(query_data.query)
    if not result.model_info and not result.serial_info:
        raise HTTPException(status_code=404, detail="Device not found")
    return result
