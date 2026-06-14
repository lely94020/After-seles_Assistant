from fastapi import Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.auth import User,Role
from app.schemas.auth import RegisterRequest
from app.core.security import hash_password,verify_password

class UserService:
    def __init__(self,db:AsyncSession=Depends(get_db)):
        self.db=db

    async def get_by_username(self,username:str)->User|None:
        result = await self.db.execute(
            select(User).where(User.username==username)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self,user_id:int)->User|None:
        result=await self.db.execute(
            select(User).where(User.id==user_id)
        )
        return result.scalar_one_or_none()

    async def authenticate(self,username:str,password:str)->User|None:
        """"验证用户名和密码"""
        user=await self.get_by_username(username)
        if not user:
            return None
        if not verify_password(password,user.password_hash):
            return None
        if not user.is_active:
            return None
        return user

    async def create_user(self,req:RegisterRequest)->User:
        existing=await self.get_by_username(req.username)
        if existing:
            raise HTTPException(status_code=409,detail="用户名已存在")

        role_result=await self.db.execute(
            select(Role).where(Role.role_name==req.user_type)
        )
        role=role_result.scalar_one_or_none()
        if not role:
            raise HTTPException(status_code=400,detail=f"无效的用户类型：{req.user_type}")

        user=User(
            username=req.username,
            password_hash=hash_password(req.password),
            user_type=req.user_type,
            role_id=role.id,
            company_name=req.company_name,
            email=req.email,
            phone=req.phone
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        # flush   = 把 SQL 发给数据库，但不最终保存（还能回滚）
        # 我需要 flush 是因为想拿到数据库生成的 id。commit 在 get_db() 函数里自动做了
        return user