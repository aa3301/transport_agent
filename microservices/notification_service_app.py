"""
Notification Microservice (standalone FastAPI app).

Purpose:
- Manage user subscriptions to bus notifications
- (Later) publish notifications to RabbitMQ, track delivery, etc.

Run:
- uvicorn microservices.notification_service_app:app --host 0.0.0.0 --port 8003
"""
from fastapi import FastAPI, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional, List

from core.db import get_db_session
from core.response import ok
from services.subscription_service import subscription_service
from services.notification_service import notification_service  # for notify endpoints
import logging
import httpx

logger = logging.getLogger(__name__)

app = FastAPI(title="Notification Microservice", version="0.1")

AGENT_SERVICE_URL = "http://localhost:8001"

# --- Pydantic Models for Validation ---
class SubscribePayload(BaseModel):
	"""Payload for creating a new subscription."""
	user_id: str = Field(..., min_length=1, description="Unique identifier for the user")
	bus_id: str = Field(..., min_length=1, description="Identifier of the bus to track")
	stop_id: str = Field(..., min_length=1, description="Identifier of the stop")
	notify_before_sec: int = Field(300, ge=60, description="Seconds before arrival to notify")
	channel: str = Field("console", description="Notification channel (console, email, etc.)")
	policy: Optional[dict] = Field(None, description="Optional notification policy")

class NotifyPayload(BaseModel):
	"""Payload for sending a notification to a user (dev/debug)."""
	user_id: str = Field(..., min_length=1, description="User to notify")
	message: str = Field(..., min_length=1, description="Notification message")
	channel: str = Field("console", description="Notification channel (console, email, etc.)")

# NOTE: For now, we keep custom middlewares and auth commented out so you can
# test endpoints without interference. Later you can re‑enable them if needed.
# from core.logging import request_logging_middleware
# from core.exception_handlers import register_exception_handlers
# app.middleware("http")(request_logging_middleware)
# register_exception_handlers(app)

@app.get("/health")
async def health():
	"""Health check for notification service."""
	return ok({"service": "notification", "status": "ok"})

@app.post("/subscribe", status_code=201)
async def subscribe(
	payload: SubscribePayload,
	session: AsyncSession | None = Depends(get_db_session),
):
	"""
	Create a new subscription. NO AUTH for now.

	Behavior / Edge cases:
	- 201 Created: new subscription created successfully.
	- 409 Conflict: same (user_id, bus_id, stop_id) already exists.
	- 422: handled automatically by Pydantic if fields are missing/invalid.
	"""
	try:
		result = await subscription_service.add_subscription_db(
			session,
			user_id=payload.user_id,
			bus_id=payload.bus_id,
			stop_id=payload.stop_id,
			notify_before_sec=payload.notify_before_sec,
			policy=payload.policy,
			channel=payload.channel,
		)

		# subscription_service.add_subscription[_db] now returns a dict with status_code
		if isinstance(result, dict) and result.get("status_code") == 409:
			# Duplicate found
			raise HTTPException(status_code=409, detail=result.get("error", "Subscription already exists"))

		return ok(result)
	except HTTPException:
		# propagate application-level errors
		raise
	except Exception as e:
		logger.exception("Unhandled error in /subscribe: %s", e)
		return JSONResponse(
			status_code=500,
			content={"ok": False, "data": None, "error": {"code": "500", "message": "internal_server_error"}},
		)

@app.delete("/unsubscribe")
async def unsubscribe(
	user_id: str = Query(..., min_length=1),
	bus_id: str = Query(..., min_length=1),
	stop_id: str = Query(..., min_length=1),
	session: AsyncSession | None = Depends(get_db_session),
):
	"""
	Remove an existing subscription. NO AUTH for now.

	Behavior / edge cases:
	- 200 OK: subscription existed and was removed.
	- 404 Not Found: no such subscription.
	"""
	try:
		result = await subscription_service.remove_subscription_db(
			session, user_id=user_id, bus_id=bus_id, stop_id=stop_id
		)

		if isinstance(result, dict) and result.get("status_code") == 404:
			# Attempted to remove non-existent subscription
			raise HTTPException(status_code=404, detail=result.get("error", "Subscription not found"))

		return ok(result)
	except HTTPException:
		raise
	except Exception as e:
		logger.exception("Unhandled error in /unsubscribe: %s", e)
		return JSONResponse(
			status_code=500,
			content={"ok": False, "data": None, "error": {"code": "500", "message": "internal_server_error"}},
		)

@app.get("/subscriptions")
async def list_subscriptions(
    user_id: Optional[str] = Query(None, description="Optional: filter by user_id"),
    session: AsyncSession | None = Depends(get_db_session),
):
    """
    List subscriptions. NO AUTH for now.

    Behavior:
    - 200 OK with list of subscriptions (normalized to list[dict]).
    - Optional filter by user_id (when DB is enabled later; for now, in-memory returns all).
    """
    try:
        # When DB is disabled, list_subscriptions_db() falls back to in-memory list_subscriptions()
        subs = await subscription_service.list_subscriptions_db(session, user_id=user_id)

        out: List[dict] = []
        for s in subs:
            # If it's a Pydantic/BaseModel-like object with .dict(), use that
            dict_method = getattr(s, "dict", None)
            if callable(dict_method):
                out.append(dict_method())
            elif isinstance(s, dict):
                out.append(s)
            else:
                # Best-effort conversion for other types (e.g. ORM objects)
                try:
                    out.append(dict(s))
                except Exception:
                    out.append({"value": str(s)})
        return ok(out)
    except Exception as e:
        logger.exception("Error listing subscriptions: %s", e)
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.post("/notify")
async def send_notification(
	payload: NotifyPayload,
):
	"""
	Send a notification to a user. NO AUTH for now.

	This is primarily for dev/testing:
	- Uses services.notification_service (which itself prefers RabbitMQ, then console).
	- Does not require DB or subscriptions to exist.
	"""
	try:
		result = await notification_service.notify(
			user_id=payload.user_id,
			message=payload.message,
			channel=payload.channel,
		)
		return ok(result)
	except Exception as e:
		logger.exception("Error sending notification: %s", e)
		raise HTTPException(status_code=500, detail="internal_server_error")

@app.get("/notifications/recent")
async def recent_notifications():
	"""
	Return the last 20 notifications recorded by NotificationService in this process.
	"""
	try:
		async with httpx.AsyncClient(timeout=2.0) as client:
			resp = await client.get(f"{AGENT_SERVICE_URL}/notifications/recent")
		if resp.status_code == 200:
			return resp.json()
		raise HTTPException(status_code=resp.status_code, detail="Agent service error")
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"Failed to fetch notifications from agent: {e}")

# NOTE:
# For now we do NOT register any startup/shutdown hooks dealing with DB engines
# or RabbitMQ, because DB is disabled (MYSQL_ASYNC_URL=disabled) and you want
# to test pure HTTP behavior. Later you can re‑add engine/RabbitMQ usage here.

# or: api/routes_notification.py, depending on your structure

from fastapi import APIRouter, Depends, HTTPException
from core.response import ok
from services.subscription_service import subscription_service
from models.subscription import Subscription

router = APIRouter()

@router.post("/subscribe")
async def subscribe(sub: Subscription):
    """
    Create a subscription in the shared in-memory SubscriptionService.
    """
    result = subscription_service.add_subscription(sub)
    # result has 'status_code' and data
    status_code = result.get("status_code", 201)
    if status_code == 201:
        return ok(result.get("subscription"))
    elif status_code == 409:
        raise HTTPException(status_code=409, detail="Subscription already exists")
    else:
        raise HTTPException(status_code=500, detail="Failed to subscribe")

@router.post("/unsubscribe")
async def unsubscribe(user_id: str, bus_id: str, stop_id: str):
    """
    Remove subscription from the same shared SubscriptionService.
    """
    result = subscription_service.remove_subscription(user_id, bus_id, stop_id)
    status_code = result.get("status_code", 200)
    if status_code == 200:
        return ok({"message": "Unsubscribed successfully"})
    elif status_code == 404:
        raise HTTPException(status_code=404, detail="Subscription not found")
    else:
        raise HTTPException(status_code=500, detail="Failed to unsubscribe")

@router.get("/subscriptions")
async def list_subscriptions():
    """
    Debug: list all in-memory subscriptions for this process.
    """
    subs = subscription_service.list_subscriptions()
    out = [s.dict() if hasattr(s, "dict") else s for s in subs]
    return ok(out)
