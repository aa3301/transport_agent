"""
Simple rate limiter middleware (in-memory).

- Not suitable for multi-instance production.
- Replace with Redis-based limiter (sliding window / token bucket) or use API Gateway rate-limiting.
- Usage: app.add_middleware(RateLimiterMiddleware, calls=120, per_seconds=60)
"""
import time
import asyncio
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse

class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, calls: int = 60, per_seconds: int = 60):
        super().__init__(app)
        self.calls = calls
        self.per_seconds = per_seconds
        self._buckets = {}  # key -> [timestamps]
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        # Identify client: prefer authenticated user id, fallback to client IP
        user = getattr(request.state, "user", None)
        if user and isinstance(user, dict) and user.get("user_id"):
            key = f"user:{user['user_id']}"
        else:
            # fallback to client host
            client = request.client.host if request.client else "anon"
            key = f"ip:{client}"

        now = time.time()
        async with self._lock:
            timestamps = self._buckets.get(key, [])
            # drop expired timestamps
            window_start = now - self.per_seconds
            timestamps = [ts for ts in timestamps if ts > window_start]
            if len(timestamps) >= self.calls:
                # over limit
                retry_after = int(timestamps[0] + self.per_seconds - now) if timestamps else self.per_seconds
                return JSONResponse(status_code=429, content={"ok": False, "data": None, "error": {"code": "rate_limited", "message": f"Rate limit exceeded. Retry after {retry_after} seconds"}})
            timestamps.append(now)
            self._buckets[key] = timestamps
        # proceed to handler
        return await call_next(request)
