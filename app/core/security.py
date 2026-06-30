from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

security = HTTPBearer()

# bcrypt 加密器：同一段密码每次加密结果都不同（加了随机盐）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """签发 JWT 令牌，里面装着用户 ID 和过期时间"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """解码令牌，拿到里面的数据。如果过期或伪造，返回 None"""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.JWTError:
        return None


# ---- 当前用户 ----

@dataclass
class CurrentUser:
    id: int
    user_type: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    """从 JWT 中提取完整用户信息（id + user_type）"""
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    return CurrentUser(
        id=int(payload.get("sub")),
        user_type=payload.get("type", "end_user"),
    )


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """向后兼容：仅返回用户 ID"""
    user = await get_current_user(credentials)
    return user.id


# ---- 角色权限校验 ----

def require_role(*allowed_roles: str):
    """工厂函数：返回一个 FastAPI 依赖，校验当前用户是否在允许的角色列表中"""
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.user_type not in allowed_roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return _check