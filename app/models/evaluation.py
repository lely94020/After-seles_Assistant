import datetime
from sqlalchemy import BigInteger, String, DateTime, Text, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MessageEvaluation(Base):
    __tablename__ = "message_evaluations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("messages.id"), nullable=False, index=True)
    evaluator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    quality_label: Mapped[str] = mapped_column(
        Enum("accurate", "inaccurate", "incomplete", "hallucination"), nullable=False
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    message: Mapped["Message"] = relationship(back_populates="evaluations")
    evaluator: Mapped["User"] = relationship()
