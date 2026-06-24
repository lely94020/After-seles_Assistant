import logging
from datetime import datetime,timedelta
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation,Message
from app.core.redis_client import get_redis

logger=logging.getLogger(__name__)

SESSION_TTL_SECONDS=24*3600 #24小时

class ConversationService:
    def __init__(self,db:AsyncSession):
        self.db=db

    #---CRUD---
    async def create(self,user_id:int,title:str="新对话")->Conversation:
        conv=Conversation(user_id=user_id,title=title)
        self.db.add(conv)
        await self.db.flush()   #只同步状态但不提交事务。这一步是为了让数据库为 conv 生成自增的主键 id
        await self.db.refresh(conv)     #刷新，获取最新数据

        #Redis设置会话TTL
        redis=await get_redis()
        await redis.setex(f"session:{conv.id}",SESSION_TTL_SECONDS,"active")

        return conv

    async def get(self,conv_id:int)->Conversation|None:
        r=await self.db.execute(
            select(Conversation)
            .where(Conversation.id==conv_id)
            .options(selectinload(Conversation.messages))
        )
        return r.scalar_one_or_none()

    async def list_by_user(self,user_id:int,skip:int=0,limit:int=20)->list[Conversation]:
        r=await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id==user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(skip).limit(limit)
        )
        return list(r.scalars().all())

    #----消息管理----

    async def add_message(
            self,
            conv_id:int,
            role:str,
            content:str,
            citations:list|None=None,
            confidence:float|None=None,
            intent:str|None=None,
    )->Message:
        msg=Message(
            conversation_id=conv_id,
            role=role,
            content=content,
            citations=citations,
            confidence=confidence,
            intent=intent,
        )
        self.db.add(msg)

        #刷新会话TTL
        redis=await get_redis()
        await redis.expire(f"session:{conv_id}",SESSION_TTL_SECONDS)

        #更新conversation.updated_at
        conv=await self.db.get(Conversation,conv_id)
        if conv:
            conv.updated_at=datetime.now()

        await self.db.flush()
        return msg

    #----诊断状态----
    async def update_key_facts(self,conv_id:int,key_facts:dict)->None:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id==conv_id)
            .values(key_facts=key_facts)
        )

    async def update_step(self,conv_id:int,step_index:int)->None:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id==conv_id)
            .values(step_index=step_index)
        )

    async def close(self,conv_id:int,status:str="resolved")->None:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id==conv_id)
            .values(status=status,closed_at=datetime.now())
        )
        redis=await get_redis()
        await redis.delete(f"session:{conv_id}")
        await self._cleanup_checkpoint(redis, conv_id)

    #----删除对话----

    async def delete(self, conv_id: int) -> None:
        """硬删除对话：清理 Redis 会话 + checkpoint，删除 MySQL 中的对话和关联消息"""
        redis = await get_redis()
        await redis.delete(f"session:{conv_id}")
        await self._cleanup_checkpoint(redis, conv_id)

        # 先删消息（外键约束），再删对话
        await self.db.execute(
            delete(Message).where(Message.conversation_id == conv_id)
        )
        await self.db.execute(
            delete(Conversation).where(Conversation.id == conv_id)
        )
        await self.db.flush()

    #----会话超时扫描----
    async def scan_timeout_sessions(self)->int:
        """扫描超过30分钟无活动的active会话，标记为timeout并清理Redis checkpoint"""
        threshold=datetime.now()-timedelta(minutes=30)

        # 先查出超时会话的ID
        r=await self.db.execute(
            select(Conversation.id)
            .where(
                Conversation.status=="active",
                Conversation.updated_at<threshold,
            )
        )
        timeout_ids=[row[0]for row in r.all()]
        if not timeout_ids:
            return 0

        # 清理每个会话的 Redis checkpoint + session key
        redis=await get_redis()
        for conv_id in timeout_ids:
            await redis.delete(f"session:{conv_id}")
            await self._cleanup_checkpoint(redis, conv_id)

        # 批量更新 MySQL 状态
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id.in_(timeout_ids))
            .values(status="timeout",closed_at=datetime.now())
        )
        await self.db.flush()
        logger.info(f"超时清理：{len(timeout_ids)} 个会话已关闭，Redis checkpoint 已删除")
        return len(timeout_ids)

    @staticmethod
    async def _cleanup_checkpoint(redis,conv_id:int)->None:
        """删除 LangGraph AsyncRedisSaver 的 checkpoint 和 checkpoint_write 键"""
        thread_id=str(conv_id)
        # AsyncRedisSaver 键格式：checkpoint:{thread_id}:... 和 checkpoint_write:{thread_id}:...
        for prefix in ("checkpoint","checkpoint_write"):
            pattern=f"{prefix}:{thread_id}:*"
            async for key in redis.scan_iter(match=pattern,count=100):
                await redis.delete(key)