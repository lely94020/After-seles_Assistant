import datetime
from sqlalchemy import BigInteger, String, Integer, DateTime, Enum, JSON, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DeviceModelInfo(Base):
    """设备型号详细信息（产品级）"""
    __tablename__ = "device_model_info"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    product_series: Mapped[str | None] = mapped_column(String(100))
    product_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    specifications: Mapped[dict | None] = mapped_column(JSON)
    wiring_diagram: Mapped[str | None] = mapped_column(String(500))
    firmware_versions: Mapped[list | None] = mapped_column(JSON)
    knowledge_base_docs: Mapped[list | None] = mapped_column(JSON)
    warranty_months: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(
        Enum("active", "discontinued", "legacy", name="device_model_status_enum"),
        default="active",
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP"
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP"
    )


class DeviceSerialNumber(Base):
    """设备序列号信息（单机级，跟踪保修）"""
    __tablename__ = "device_serial_numbers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    serial_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    model_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    purchase_date: Mapped[datetime.date | None] = mapped_column(Date)
    purchase_channel: Mapped[str | None] = mapped_column(String(100))
    warranty_start_date: Mapped[datetime.date | None] = mapped_column(Date)
    warranty_end_date: Mapped[datetime.date | None] = mapped_column(Date)
    customer_info: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        Enum("active", "returned", "scrapped", name="device_serial_status_enum"),
        default="active",
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP"
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP"
    )
