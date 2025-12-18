"""
Request logging middleware.

- Adds X-Request-ID header (UUID4) to each response and request.state.
- Logs method, path, status, latency and request-id.
- Replace prints with structured logger (e.g., structlog / python-json-logger) in production.
"""
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send
import time
import uuid
from typing import Callable

async def request_logging_middleware(request: Request, call_next: Callable):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as exc:
        # ensure the exception is returned as 500 (exception handlers will wrap)
        raise
    latency = (time.time() - start) * 1000.0
    # Add header to response
    response.headers["X-Request-ID"] = request_id
    # Basic logging - replace with structured logs in production
    print(f"[request] id={request_id} method={request.method} path={request.url.path} status={response.status_code} latency_ms={latency:.2f}")
    return response
