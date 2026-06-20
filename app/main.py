from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import auth, chat, conversations, work_orders, kb

app = FastAPI(title="Hikvision After-sales Smart Assistant", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["对话"])
# app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["对话管理"])
# app.include_router(work_orders.router, prefix="/api/v1/work_orders", tags=["工单"])
app.include_router(kb.router, prefix="/api/v1/kb", tags=["知识库"])
