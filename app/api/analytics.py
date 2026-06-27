from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.analytics_service import AnalyticsService

router = APIRouter()


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)):
    """概览统计"""
    svc = AnalyticsService(db)
    return await svc.get_overview()


@router.get("/quality-distribution")
async def quality_distribution(db: AsyncSession = Depends(get_db)):
    """质量标签分布"""
    svc = AnalyticsService(db)
    return await svc.get_quality_distribution()


@router.get("/knowledge-gaps")
async def knowledge_gaps(db: AsyncSession = Depends(get_db)):
    """知识库缺口分析"""
    svc = AnalyticsService(db)
    return await svc.get_knowledge_gaps()


@router.get("/prompt-suggestions")
async def prompt_suggestions(db: AsyncSession = Depends(get_db)):
    """Prompt 优化建议"""
    svc = AnalyticsService(db)
    return await svc.get_prompt_suggestions()
