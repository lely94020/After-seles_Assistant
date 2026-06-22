import datetime
from sqlalchemy import BigInteger,String,Boolean,DateTime,Text,func
from sqlalchemy.orm import Mapped,mapped_column

from app.database import Base

class QAFeedback(Base):
    __tablename__ = "qa_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )