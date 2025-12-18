"""
Agent Microservice (standalone FastAPI app).

Purpose:
- Expose a clean /ask HTTP endpoint backed by the SupervisorAgent (Planner + tools + post-processing).
- Provide subscription management & /notifications/recent for notifications.
- Start the SupervisorAgent background loop (proactive notifications, health checks).
"""

import asyncio
import logging
from fastapi import FastAPI, HTTPException, Query
from core.response import ok
from models.schemas import AskRequest
from core.db import get_db_session
from config.settings import settings
from agent.supervisor_agent import SupervisorAgent
from services.notification_service import notification_service
from services.subscription_service import subscription_service
from models.subscription import Subscription

logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Microservice", version="0.1")

# Singleton supervisor (creates its own PlannerAgent, etc.)
supervisor = SupervisorAgent()


@app.on_event("startup")
async def startup_event():
    """
    Start background loops (proactive notifications, health checks).
    Runs exactly one loop in this process.
    """
    asyncio.create_task(supervisor.run_background_loops())


# ---------------------- Health ---------------------- #

@app.get("/health")
async def health():
    """Health check for agent service."""
    return ok({"service": "agent", "status": "ok"})


# ---------------------- /ask ---------------------- #

@app.post("/ask")
async def ask(payload: AskRequest):
    """
    Main Gen-AI entrypoint for agent service.
    Expects: {"query": "<user question>"}
    Returns: {"answer": "<natural language answer>"}
    """
    if not payload.query or not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    try:
        result = await supervisor.handle_user_query(payload.query)
        if not result:
            logger.error("SupervisorAgent returned no result for query=%s", payload.query)
            raise HTTPException(status_code=500, detail="Agent failed to produce an answer")

        if "error" in result:
            logger.error("SupervisorAgent error for query=%s: %s", payload.query, result["error"])
            raise HTTPException(status_code=500, detail="Agent failed to process the query")

        answer = result.get("answer") or "Sorry, I could not find an answer."
        return {"answer": answer}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled error in /ask for query=%s", payload.query)
        raise HTTPException(status_code=500, detail="internal_server_error")


# ---------------------- Subscriptions (8001) ---------------------- #

@app.post("/subscribe")
async def subscribe(sub: Subscription):
    """
    Subscribe a user to bus/stop notifications.
    Uses in-memory SubscriptionService (shared with NotificationAgent).
    Also sends a one-time confirmation notification on success.
    """
    try:
        # Always register in in-memory store (used by background loops)
        result = subscription_service.add_subscription(sub)
        status_code = result.get("status_code", 201)
        if status_code == 201:
            # Best-effort: also persist to DB if enabled
            if settings.USE_DB:
                try:
                    async for session in get_db_session():
                        if session is None:
                            break
                        # sub.policy is a Policy model; convert to dict for DB layer
                        policy_dict = getattr(sub.policy, "dict", lambda: {})()
                        await subscription_service.add_subscription_db(
                            session,
                            user_id=sub.user_id,
                            bus_id=sub.bus_id,
                            stop_id=sub.stop_id,
                            notify_before_sec=sub.notify_before_sec,
                            policy=policy_dict,
                            channel=sub.channel or "console",
                        )
                except Exception:
                    logger.exception("Failed to persist subscription to DB; continuing with in-memory only")

            # One-time confirmation message
            try:
                channel = sub.channel or "console"
                msg = (
                    f"You have subscribed to updates for Bus {sub.bus_id} at stop {sub.stop_id}. "
                    f"You will receive notifications when the bus is approaching."
                )
                await notification_service.notify(sub.user_id, msg, channel=channel)
            except Exception:
                logger.exception("Failed to send subscription confirmation for %s", sub.user_id)
            return ok(result.get("subscription"))
        elif status_code == 409:
            raise HTTPException(status_code=409, detail="Subscription already exists")
        else:
            raise HTTPException(status_code=500, detail="Failed to subscribe")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in /subscribe with data=%s", sub)
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.post("/unsubscribe")
async def unsubscribe(
    user_id: str = Query(...),
    bus_id: str = Query(...),
    stop_id: str = Query(...),
):
    """Unsubscribe a user from bus/stop notifications.

    This now removes the subscription from both the in-memory
    store (used by background loops) and, when DB is enabled,
    from the MySQL subscriptions table so you don't see stale
    rows when you query the DB.
    """
    try:
        # First remove from in-memory store
        result = subscription_service.remove_subscription(user_id, bus_id, stop_id)
        status_code = result.get("status_code", 200)
        if status_code == 200:
            # Best-effort: also remove from DB if enabled
            if settings.USE_DB:
                try:
                    async for session in get_db_session():
                        if session is None:
                            break
                        await subscription_service.remove_subscription_db(
                            session,
                            user_id=user_id,
                            bus_id=bus_id,
                            stop_id=stop_id,
                        )
                except Exception:
                    logger.exception("Failed to remove subscription from DB; continuing with in-memory only")
            return ok({"message": "Unsubscribed successfully"})
        elif status_code == 404:
            raise HTTPException(status_code=404, detail="Subscription not found")
        else:
            raise HTTPException(status_code=500, detail="Failed to unsubscribe")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in /unsubscribe for user_id=%s, bus_id=%s, stop_id=%s", user_id, bus_id, stop_id)
        raise HTTPException(status_code=500, detail="internal_server_error")


# ---------------------- Notifications (8001 source of truth) ---------------------- #

@app.get("/notifications/recent")
async def recent_notifications():
    """
    Recent notifications from this 8001 process.
    """
    return ok(notification_service.recent_notifications())
