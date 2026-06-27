import datetime
from sqlalchemy import BigInteger, String, Integer, DateTime, Text, Boolean,ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

class Conversation(Base):
    __tablename__ = "conversations"

    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    user_id:Mapped[int]=mapped_column(BigInteger,nullable=False,index=True)
    title:Mapped[str]=mapped_column(String(200),default="新对话")

    #诊断状态（LangGraph checkpoint的tread_id就是conversation.id)
    status:Mapped[str]=mapped_column(
        String(20),default="active",    #active|resolved|timeout|escalated
    )
    intent:Mapped[str|None]=mapped_column(String(50),nullable=True)
    key_facts:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    step_index:Mapped[int]=mapped_column(Integer,default=0)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime,server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime,nullable=True)
    resolved_by_ai: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    messages:Mapped[list["Message"]]=relationship(back_populates="conversation",order_by="Message.created_at")

class Message(Base):
    __tablename__ = "messages"

    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    conversation_id:Mapped[int]=mapped_column(BigInteger,ForeignKey("conversations.id",ondelete="CASCADE"),nullable=False)
    role:Mapped[str]=mapped_column(String(20),nullable=False)
    content:Mapped[str]=mapped_column(Text,nullable=False)

    #此轮关联的元数据
    citations:Mapped[list|None]=mapped_column(JSON,nullable=True)
    confidence:Mapped[float|None]=mapped_column(nullable=True)
    intent:Mapped[str|None]=mapped_column(String(50),nullable=True)

    created_at:Mapped[datetime.datetime]=mapped_column(DateTime,server_default=func.now())

    conversation:Mapped["Conversation"]=relationship(back_populates="messages")
    evaluations:Mapped[list["MessageEvaluation"]]=relationship(back_populates="message")
