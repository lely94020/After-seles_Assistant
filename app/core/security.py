from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

security=HTTPBearer()

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

async def get_current_user_id(credentials:HTTPAuthorizationCredentials=Depends(security),)->int:
    payload=decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401,detail="令牌无效或已过期")
    return int(payload.get("sub"))