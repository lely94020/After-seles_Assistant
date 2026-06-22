import redis.asyncio as aioredis
from app.config import settings

_pool:aioredis.ConnectionPool|None=None

async def get_redis()->aioredis.Redis:
    global _pool
    if _pool is None:
        _pool=aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connection=10,
            decode_responses=True,
        )
    return aioredis.Redis(connection_pool=_pool)
