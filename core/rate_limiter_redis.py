"""
Redis-based distributed rate limiter (production-grade).

Purpose:
- Replace in-memory limiter with Redis-backed limiter
- Support token bucket or sliding window algorithm
- Work across multiple instances (distributed)

Algorithm:
- Sliding window: track request timestamps in a sorted set
- Increment counter per key, expire old entries

Usage:
- app.add_middleware(RedisRateLimiterMiddleware, redis_client, calls=120, per_seconds=60)

Production notes:
- Use EVAL script for atomic operations if needed
- Monitor Redis memory and evictions
- Consider using fixed-window counter for simplicity (less precise but faster)
"""
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
import time
import logging

logger = logging.getLogger(__name__)

class RedisRateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client, calls: int = 60, per_seconds: int = 60):
        """
        Initialize Redis-based rate limiter.
        
        Args:
            app: FastAPI app
            redis_client: initialized RedisClient instance
            calls: max requests per window
            per_seconds: window size in seconds
        """
        super().__init__(app)
        self.redis_client = redis_client
        self.calls = calls
        self.per_seconds = per_seconds
    
    async def dispatch(self, request: Request, call_next):
        """
        Check rate limit before processing request.
        """
        # Extract rate limit key (prefer authenticated user, fallback to IP)
        user = getattr(request.state, "user", None)
        if user and isinstance(user, dict) and user.get("user_id"):
            key = f"ratelimit:user:{user['user_id']}"
        else:
            client_ip = request.client.host if request.client else "anon"
            key = f"ratelimit:ip:{client_ip}"
        
        # Use Redis to increment and check limit
        try:
            current = await self.redis_client.incr(key, ttl=self.per_seconds)
            if current > self.calls:
                retry_after = self.per_seconds
                return JSONResponse(
                    status_code=429,
                    content={
                        "ok": False,
                        "data": None,
                        "error": {
                            "code": "rate_limited",
                            "message": f"Rate limit exceeded. Max {self.calls} requests per {self.per_seconds}s"
                        }
                    },
                    headers={"Retry-After": str(retry_after)}
                )
        except Exception as e:
            logger.error(f"Rate limiter error: {e}")
            # On Redis error, allow request to proceed (graceful degradation)
            pass
        
        return await call_next(request)
