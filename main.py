"""
Main FastAPI application (entrypoint).

Responsibilities:
- Wire API routers (user/driver/admin)
- Register centralized exception handlers
- Provide middleware: request-id logging, simple rate limiting (placeholder)
- Add health / readiness endpoints
- Initialize DB models on startup (if MYSQL_ASYNC_URL configured)
Notes:
- Rate limiter here is a simple in-memory version for development. Replace with Redis (or a gateway) for production.
- Logging is basic; integrate with structured logger (structlog / JSON logs) and a log sink in prod.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time
import uvicorn

# routers
from api import routes_user, routes_driver, routes_admin  # ensure package imports work
from core.exception_handlers import register_exception_handlers
from core.response import ok
from core.logging import request_logging_middleware
from core.rate_limiter import RateLimiterMiddleware

# DB scaffolding (async SQLAlchemy)
from core.db import engine, Base

app = FastAPI(title="Transport Agent API (gateway/local)", version="0.1")

# CORS - adjust origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers from your api package
app.include_router(routes_user.router, prefix="", tags=["user"])
app.include_router(routes_driver.router, prefix="/driver", tags=["driver"])
app.include_router(routes_admin.router, prefix="/admin", tags=["admin"])

# Register centralized exception handlers
register_exception_handlers(app)

# Add request logging middleware (adds X-Request-ID header and logs)
app.middleware("http")(request_logging_middleware)

# Add (placeholder) rate limiter middleware instance
app.add_middleware(RateLimiterMiddleware, calls=120, per_seconds=60)  # 120 reqs per 60s per key (dev)

# Health endpoints
@app.get("/health")
async def health():
    """Simple health endpoint used by load balancers and orchestrators."""
    return ok({"status": "ok"})

@app.get("/ready")
async def ready():
    """Readiness: check DB connectivity if configured."""
    try:
        # attempt a tiny DB interaction if engine configured
        if engine:
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
        return ok({"ready": True})
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False, "data": None, "error": {"code": "db_unreachable", "message": "DB unavailable"}})

# Startup: create DB tables if Base is configured and MYSQL_ASYNC_URL is set.
@app.on_event("startup")
async def on_startup():
    """
    On startup:
    - Create DB tables (development convenience). In production use Alembic migrations instead.
    """
    try:
        # create tables if using SQLAlchemy async engine & Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        # Do not crash the process for missing DB during local dev; log for ops
        print("Warning: DB initialization failed on startup (ok for local dev):", e)

if __name__ == "__main__":
    # Run with: python main.py for local dev. For production use uvicorn/gunicorn with workers.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
