from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import CurrentUser, require_role
from app.services.analytics_service import AnalyticsService

router = APIRouter()

# 所有分析端点仅限客服主管和知识库管理员访问
_ADMIN_DEP = Depends(require_role("cs_manager", "kb_admin"))


@router.get("/overview")
async def overview(
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """概览统计"""
    svc = AnalyticsService(db)
    return await svc.get_overview()


@router.get("/quality-distribution")
async def quality_distribution(
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """质量标签分布"""
    svc = AnalyticsService(db)
    return await svc.get_quality_distribution()


@router.get("/knowledge-gaps")
async def knowledge_gaps(
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """知识库缺口分析"""
    svc = AnalyticsService(db)
    return await svc.get_knowledge_gaps()


@router.get("/prompt-suggestions")
async def prompt_suggestions(
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """Prompt 优化建议"""
    svc = AnalyticsService(db)
    return await svc.get_prompt_suggestions()


@router.get("/top-questions")
async def top_questions(
    days: int = Query(30),
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """高频问题 TOP N"""
    svc = AnalyticsService(db)
    return await svc.get_top_questions(days=days)


@router.get("/intent-distribution")
async def intent_distribution(
    days: int = Query(30),
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """意图分类分布"""
    svc = AnalyticsService(db)
    return await svc.get_intent_distribution(days=days)


@router.get("/resolution-trend")
async def resolution_trend(
    days: int = Query(30),
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """AI 解决率 / 转人工率趋势"""
    svc = AnalyticsService(db)
    return await svc.get_resolution_trend(days=days)


@router.get("/coverage-heatmap")
async def coverage_heatmap(
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """知识库覆盖率"""
    svc = AnalyticsService(db)
    return await svc.get_coverage_heatmap()


@router.get("/model-fault-rate")
async def model_fault_rate(
    days: int = Query(30),
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """各型号故障率统计"""
    svc = AnalyticsService(db)
    return await svc.get_model_fault_rate(days=days)


@router.get("/satisfaction-trend")
async def satisfaction_trend(
    days: int = Query(30),
    user: CurrentUser = _ADMIN_DEP,
    db: AsyncSession = Depends(get_db),
):
    """用户满意度走势"""
    svc = AnalyticsService(db)
    return await svc.get_satisfaction_trend(days=days)
