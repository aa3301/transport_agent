# API Gateway (Centralized Entry Point).
# - /ask                  -> agent_service (8001)
# - /driver/*, /admin/*   -> fleet_service (8002)

import logging
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from config.settings import settings
from core.response import ok
from core.exception_handlers import register_exception_handlers
from infra.redis_client import redis_client
from models.schemas import AskRequest, LocationUpdate, StatusUpdate, SubscribeRequest

logger = logging.getLogger(__name__)

# Optional gRPC clients (not required; HTTP fallback is default)
try:
    from api_gateway.grpc_client import FleetGRPCClient, AgentGRPCClient
    from transport_proto import transport_agent_pb2_grpc as rpc
except Exception:
    FleetGRPCClient = None
    AgentGRPCClient = None
    rpc = None

# Downstream service URLs
AGENT_SERVICE_URL = getattr(settings, "AGENT_SERVICE_URL", "http://localhost:8001")
FLEET_SERVICE_URL = getattr(settings, "FLEET_SERVICE_URL", "http://localhost:8002")
NOTIFICATION_SERVICE_URL = getattr(settings, "NOTIFICATION_SERVICE_URL", "http://localhost:8003")

app = FastAPI(title="Transport Agent API Gateway", version="0.2")

# CORS: allow Swagger / browsers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

register_exception_handlers(app)

grpc_fleet_client = None
grpc_agent_client = None


async def proxy_to_http(base_url: str, path: str, method: str, request: Request, body: bytes | None = None):
    """
    Generic HTTP proxy helper.
    - Forwards method, path, headers, and body to target service.
    - If target returns JSON, forward as JSON.
    - If target returns non-JSON (e.g. HTML error), forward raw text without crashing.
    """
    url = base_url.rstrip("/") + path
    # Start from incoming headers but drop hop-by-hop / content-length to avoid protocol errors
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        try:
            resp = await client.request(method, url, headers=headers, content=body)
        except httpx.RequestError as e:
            logger.error("[gateway] HTTP proxy request to %s failed: %s", url, e)
            return JSONResponse(status_code=503, content={"detail": "upstream_unavailable", "error": str(e)})

    text = resp.text or ""
    if text:
        try:
            data = resp.json()
            return JSONResponse(status_code=resp.status_code, content=data)
        except ValueError:
            logger.warning("[gateway] Non-JSON response from %s (status=%s)", url, resp.status_code)
            return Response(
                status_code=resp.status_code,
                content=text,
                media_type=resp.headers.get("content-type", "text/plain"),
            )
    else:
        return Response(status_code=resp.status_code, content=b"")


@app.on_event("startup")
async def startup():
    # Redis (optional)
    try:
        await redis_client.connect()
        logger.info("Connected to Redis")
    except Exception as e:
        logger.warning("Redis connect failed: %s", e)

    # gRPC clients (optional; HTTP fallback is default)
    global grpc_fleet_client, grpc_agent_client
    if FleetGRPCClient and rpc and hasattr(rpc, "FleetServiceStub"):
        try:
            grpc_fleet_client = FleetGRPCClient("localhost:50051")
            await grpc_fleet_client.connect()
            logger.info("Connected to Fleet gRPC server")
        except Exception as e:
            logger.warning("Fleet gRPC client connect failed: %s", e)
            grpc_fleet_client = None
    else:
        logger.warning("Fleet gRPC stubs not available; using HTTP fallback.")

    if AgentGRPCClient and rpc and hasattr(rpc, "AgentServiceStub"):
        try:
            grpc_agent_client = AgentGRPCClient("localhost:50052")
            await grpc_agent_client.connect()
            logger.info("Connected to Agent gRPC server")
        except Exception as e:
            logger.warning("Agent gRPC client connect failed: %s", e)
            grpc_agent_client = None
    else:
        logger.warning("Agent gRPC stubs not available; using HTTP fallback.")


@app.on_event("shutdown")
async def shutdown():
    try:
        await redis_client.disconnect()
    except Exception:
        pass


@app.get("/health")
async def health():
    return ok({"service": "gateway", "status": "ok"})


@app.get("/")
async def root():
    return {"message": "Transport Agent API Gateway. See /docs for API documentation."}


# -------------------
# /subscribe endpoints -> Notification Service (8003)
# -------------------


@app.post("/subscribe")
async def subscribe(req: SubscribeRequest, request: Request):
    """Proxy subscription creation to Notification Service (8003)."""
    body = req.json().encode("utf-8")
    return await proxy_to_http(NOTIFICATION_SERVICE_URL, "/subscribe", "POST", request=request, body=body)


@app.delete("/unsubscribe")
async def unsubscribe(user_id: str, bus_id: str, stop_id: str, request: Request):
    """Proxy unsubscribe to Notification Service (8003)."""
    path_with_query = f"/unsubscribe?user_id={user_id}&bus_id={bus_id}&stop_id={stop_id}"
    return await proxy_to_http(NOTIFICATION_SERVICE_URL, path_with_query, "DELETE", request=request)


# -------------------
# /ask -> Agent Service (8001)
# -------------------
@app.post("/ask")
async def ask(request: Request, req: AskRequest):
    """
    Proxy to Agent Service (8001) /ask.
    No auth. Returns only { "answer": "<natural language>" }.
    """
    if grpc_agent_client:
        try:
            resp = await grpc_agent_client.ask(req.query)
            return JSONResponse(status_code=200, content={"answer": resp.answer})
        except Exception:
            logger.exception("gRPC ask failed, falling back to HTTP")

    body = req.json().encode("utf-8") if req else None
    return await proxy_to_http(AGENT_SERVICE_URL, "/ask", "POST", request=request, body=body)


# -------------------
# Driver-facing fleet endpoints -> Fleet Service (8002)
# -------------------
@app.post("/driver/location")
async def driver_location(req: LocationUpdate, request: Request):
    """
    Proxy to Fleet Service (8002) /driver/location.
    """
    body = req.json().encode("utf-8")
    return await proxy_to_http(FLEET_SERVICE_URL, "/driver/location", "POST", request=request, body=body)


@app.post("/driver/status")
async def driver_status(req: StatusUpdate, request: Request):
    """
    Proxy to Fleet Service (8002) /driver/status.
    """
    body = req.json().encode("utf-8")
    return await proxy_to_http(FLEET_SERVICE_URL, "/driver/status", "POST", request=request, body=body)


@app.get("/driver/route")
async def driver_route(bus_id: str, request: Request):
    """
    Proxy to Fleet Service (8002) /driver/route.
    """
    path_with_query = f"/driver/route?bus_id={bus_id}"
    return await proxy_to_http(FLEET_SERVICE_URL, path_with_query, "GET", request=request)


# -------------------
# Admin-facing fleet endpoints -> Fleet Service (8002)
# -------------------
@app.get("/admin/fleet/overview")
async def admin_fleet_overview(request: Request):
    """
    Proxy to Fleet Service (8002) /admin/fleet/overview.
    """
    return await proxy_to_http(FLEET_SERVICE_URL, "/admin/fleet/overview", "GET", request=request)


@app.post("/admin/route/update")
async def admin_route_update(request: Request):
    """
    Proxy to Fleet Service (8002) /admin/route/update.
    """
    body = await request.body()
    return await proxy_to_http(FLEET_SERVICE_URL, "/admin/route/update", "POST", request=request, body=body)
