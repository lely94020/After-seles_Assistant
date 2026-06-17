import  datetime
from sqlalchemy import BigInteger,String,Integer,DateTime,Enum,JSON
from sqlalchemy.orm import Mapped,mapped_column

from app.database import Base

class Device(Base):
    __tablename__ = "device"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    product_series: Mapped[str | None] = mapped_column(String(100))
    product_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    specifications: Mapped[dict | None] = mapped_column(JSON)
    warranty_months: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(
        Enum("active", "discontinued", "legacy", name="device_status_enum"),
        default="active",
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")