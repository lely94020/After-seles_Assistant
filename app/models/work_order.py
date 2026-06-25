import datetime
from sqlalchemy import BigInteger, String, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    device_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("devices.id"), nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"), nullable=True)

    order_type: Mapped[str] = mapped_column(
        String(20), nullable=False  # fault_repair | general_inquiry | installation | other
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending"  # pending | assigned | in_progress | completed | cancelled
    )

    fault_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    notes: Mapped[list["WorkOrderNote"]] = relationship(
        back_populates="work_order", order_by="WorkOrderNote.created_at"
    )


class WorkOrderNote(Base):
    __tablename__ = "work_order_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("work_orders.id"), nullable=False
    )
    operator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(
        String(20), nullable=False  # status_change | note | assignment | resolution
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    work_order: Mapped["WorkOrder"] = relationship(back_populates="notes")
