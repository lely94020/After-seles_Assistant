from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.auth import User
from app.models.conversation import Conversation, Message
from app.models.work_order import WorkOrder
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.core.security import create_access_token, decode_access_token, get_current_user, CurrentUser

router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    user_service: UserService = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await user_service.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    access_token = create_access_token(
        data={"sub": str(user.id), "type": user.user_type},
        expires_delta=timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    # 审计：登录
    audit = AuditService(db)
    await audit.log(user_id=user.id, action="login", resource_type="auth")
    await db.commit()
    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


@router.post("/register", response_model=TokenResponse)
async def register(
    req: RegisterRequest,
    user_service: UserService = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await user_service.create_user(req)
    access_token = create_access_token(
        data={"sub": str(user.id), "type": user.user_type},
        expires_delta=timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    )
    # 审计：注册
    audit = AuditService(db)
    await audit.log(user_id=user.id, action="register", resource_type="auth")
    await db.commit()
    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


# 用户刷新页面后，令牌还在浏览器里，前端需要调用这个接口来获取当前用户的信息
@router.get("/me", response_model=UserResponse)
async def get_me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_service: UserService = Depends(),
) -> UserResponse:
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    user_id = int(payload.get("sub"))
    user = await user_service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserResponse.model_validate(user)


@router.post("/consent")
async def record_privacy_consent(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """记录用户隐私政策同意时间"""
    await db.execute(
        update(User).where(User.id == user.id).values(privacy_consent_at=datetime.utcnow())
    )
    await db.commit()
    return {"ok": True, "consented_at": datetime.utcnow().isoformat()}


@router.delete("/me/data")
async def delete_my_data(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户数据删除（匿名化处理，保留结构数据用于统计）"""
    from sqlalchemy import select

    # 1. 匿名化对话 key_facts 和消息内容
    convs = await db.execute(
        select(Conversation.id).where(Conversation.user_id == user.id)
    )
    conv_ids = [row[0] for row in convs.fetchall()]
    if conv_ids:
        await db.execute(
            update(Conversation)
            .where(Conversation.id.in_(conv_ids))
            .values(key_facts={})
        )
        await db.execute(
            update(Message)
            .where(Message.conversation_id.in_(conv_ids))
            .values(content="[已删除]")
        )

    # 2. 匿名化工单敏感字段
    await db.execute(
        update(WorkOrder)
        .where(WorkOrder.user_id == user.id)
        .values(contact_info=None, serial_number=None)
    )

    # 3. 清除用户个人信息
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(email=None, phone=None, company_name=None)
    )

    # 审计：数据删除
    audit = AuditService(db)
    await audit.log(user_id=user.id, action="data_delete", resource_type="user", resource_id=str(user.id))
    await db.commit()
    return {"ok": True, "message": "个人数据已匿名化处理"}
