from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import settings
from app.api import auth, chat, conversations, work_orders, kb, device_info, evaluations, analytics

scheduler=AsyncIOScheduler()

async def _daily_scan():
    from app.database import async_session
    from app.services.kb_service import KbService
    async with async_session() as db:
        svc=KbService(db)
        result=await svc.scan_expired()
        print(f"过期扫描完成:{result}")

@asynccontextmanager    #用于将一个异步生成器函数转换成异步上下文管理器
async def lifespan(app:FastAPI):
    #向调度器添加一个定时任务，指定每天凌晨3点执行扫描任务
    scheduler.add_job(_daily_scan,"cron",hour=3,minute=0)
    scheduler.start()
    yield   #整个生命周期的分水岭，yield之前执行启动前的初始化逻辑，之后执行关闭后的清理逻辑
    scheduler.shutdown()
app = FastAPI(
    title="Hikvision After-sales Smart Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["对话"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["对话管理"])
app.include_router(work_orders.router, prefix="/api/v1/work-orders", tags=["工单"])
app.include_router(kb.router, prefix="/api/v1/kb", tags=["知识库"])
app.include_router(device_info.router, prefix="/api/v1/device-info", tags=["设备信息"])
app.include_router(evaluations.router, prefix="/api/v1/evaluations", tags=["质量评价"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["数据分析"])
