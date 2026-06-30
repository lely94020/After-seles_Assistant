from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings


def _key_func(request) -> str:
    """优先用 JWT 中的 user_id 做限流 key，否则用 IP"""
    if hasattr(request.state, "user_id") and request.state.user_id:
        return str(request.state.user_id)
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
    storage_uri=settings.REDIS_URL,
)
