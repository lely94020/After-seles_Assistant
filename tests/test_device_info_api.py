import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock

from app.models.device_info import DeviceModelInfo, DeviceSerialNumber
from app.database import Base
from app.services.device_info_service import DeviceInfoService
from app.schemas.device_info import (
    DeviceModelInfoCreate,
    DeviceSerialNumberCreate,
    DeviceQueryRequest
)

# 创建独立的FastAPI应用用于测试
from fastapi import FastAPI, Depends
from app.database import get_db
from app.api.v1.device_info import router as device_info_router

test_app = FastAPI(title="Test App")
test_app.include_router(device_info_router, prefix="/api/v1", tags=["device-info"])

# 创建测试数据库引擎
SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

engine = create_async_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# 重写依赖项
async def override_get_db():
    async with TestingSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


test_app.dependency_overrides[get_db] = override_get_db

client = TestClient(test_app)


@pytest.fixture(scope="module", autouse=True)
async def setup_database():
    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    # 清理数据库
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestDeviceInfoAPI:
    """测试设备信息查询功能API"""

    def test_create_device_model(self):
        """测试创建设备型号信息"""
        payload = {
            "model_number": "DS-2CD2T86G1-I8",
            "product_series": "EasyIP 3.0",
            "product_name": "筒型网络摄像机",
            "category": "网络摄像机",
            "specifications": {
                "sensor": "1/2.7\" CMOS",
                "resolution": "8MP",
                "ir_distance": "30m",
                "power_supply": "DC12V/POE"
            },
            "wiring_diagram": "http://example.com/wiring/ds-2cd2t86g1-i8.pdf",
            "firmware_versions": ["V5.7.0", "V5.7.1", "V5.7.2"],
            "knowledge_base_docs": ["doc_camera_setup", "doc_troubleshooting"],
            "warranty_months": 24
        }

        response = client.post("/api/v1/device-info/models", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["model_number"] == "DS-2CD2T86G1-I8"
        assert data["product_name"] == "筒型网络摄像机"

    def test_get_device_model(self):
        """测试获取设备型号信息"""
        response = client.get("/api/v1/device-info/models/DS-2CD2T86G1-I8")
        assert response.status_code == 200
        data = response.json()
        assert data["model_number"] == "DS-2CD2T86G1-I8"
        assert data["category"] == "网络摄像机"

    def test_create_device_serial_number(self):
        """测试创建设备序列号信息"""
        payload = {
            "serial_number": "C202301000001",
            "model_number": "DS-2CD2T86G1-I8",
            "purchase_date": "2023-01-15",
            "purchase_channel": "授权经销商",
            "warranty_start_date": "2023-01-15",
            "customer_info": {
                "name": "某公司",
                "contact": "张三",
                "phone": "13800138000"
            }
        }

        response = client.post("/api/v1/device-info/serials", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["serial_number"] == "C202301000001"
        assert data["model_number"] == "DS-2CD2T86G1-I8"

    def test_get_device_serial_number(self):
        """测试获取设备序列号信息"""
        response = client.get("/api/v1/device-info/serials/C202301000001")
        assert response.status_code == 200
        data = response.json()
        assert data["serial_number"] == "C202301000001"
        assert data["purchase_channel"] == "授权经销商"

    def test_query_device_by_model(self):
        """测试按型号查询设备信息"""
        payload = {
            "query": "DS-2CD2T86G1-I8"
        }

        response = client.post("/api/v1/device-info/query", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["model_info"]["model_number"] == "DS-2CD2T86G1-I8"
        assert data["model_info"]["product_name"] == "筒型网络摄像机"

    def test_query_device_by_serial_number(self):
        """测试按序列号查询设备信息"""
        payload = {
            "query": "C202301000001"
        }

        response = client.post("/api/v1/device-info/query", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["serial_info"]["serial_number"] == "C202301000001"
        assert data["model_info"]["model_number"] == "DS-2CD2T86G1-I8"

    def test_search_devices_by_model(self):
        """测试按型号模糊搜索设备"""
        # 首先创建另一个相似型号
        payload = {
            "model_number": "DS-2CD2T86G1-I8L",
            "product_series": "EasyIP 3.0",
            "product_name": "筒型网络摄像机带音频",
            "category": "网络摄像机",
            "specifications": {
                "sensor": "1/2.7\" CMOS",
                "resolution": "8MP",
                "audio": "支持",
                "ir_distance": "30m",
                "power_supply": "DC12V/POE"
            },
            "warranty_months": 24
        }

        response = client.post("/api/v1/device-info/models", json=payload)
        assert response.status_code == 200

        # 搜索相似型号
        response = client.get("/api/v1/device-info/models/search/DS-2CD2T86G1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2  # 至少有两个相似型号

    def test_get_firmware_versions(self):
        """测试获取固件版本列表"""
        response = client.get("/api/v1/device-info/models/DS-2CD2T86G1-I8/firmware")
        assert response.status_code == 200
        data = response.json()
        assert "V5.7.0" in data
        assert "V5.7.1" in data
        assert "V5.7.2" in data

    def test_update_device_model(self):
        """测试更新设备型号信息"""
        payload = {
            "product_name": "更新的筒型网络摄像机",
            "warranty_months": 36
        }

        response = client.put("/api/v1/device-info/models/DS-2CD2T86G1-I8", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["product_name"] == "更新的筒型网络摄像机"
        assert data["warranty_months"] == 36

    def test_update_device_serial_number(self):
        """测试更新设备序列号信息"""
        payload = {
            "purchase_channel": "官方直销"
        }

        response = client.put("/api/v1/device-info/serials/C202301000001", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["purchase_channel"] == "官方直销"


# 运行测试的辅助函数
if __name__ == "__main__":
    pytest.main([__file__])