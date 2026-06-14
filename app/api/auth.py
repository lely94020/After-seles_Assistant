from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.user_service import UserService
from app.core.security import create_access_token, decode_access_token

router = APIRouter()
security = HTTPBearer()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, user_service: UserService = Depends()) -> TokenResponse:
    user = await user_service.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=400001, detail="用户名或密码错误")
    access_token = create_access_token(
        data={"sub": str(user.id), "type": user.user_type},
        expires_delta=timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, user_service: UserService = Depends()) -> TokenResponse:
    user = await user_service.create_user(req)
    access_token = create_access_token(
        data={"sub": str(user.id), "type": user.user_type},
        expires_delta=timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    )
    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )

# 用户刷新页面后，令牌还在浏览器里，前端需要调用这个接口来获取当前用户的信息
@router.get("/me", response_model=UserResponse)
async def get_current_user(
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
