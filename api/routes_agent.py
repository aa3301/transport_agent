from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.response import ok
from core.db import get_db_session
from services.subscription_service import subscription_service
from services.notification_service import notification_service

router = APIRouter()

# ...existing /subscribe and /ask endpoints...

@router.post("/unsubscribe")
async def unsubscribe(
    user_id: str,
    bus_id: str,
    stop_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Unsubscribe a user from notifications for a bus/stop
    and log a notification entry (and SMS if channel='sms').
    """
    if not (user_id and bus_id and stop_id):
        raise HTTPException(status_code=400, detail="user_id, bus_id and stop_id are required")

    # Remove subscription (DB or in-memory)
    result = await subscription_service.remove_subscription_db(
        session=session,
        user_id=user_id,
        bus_id=bus_id,
        stop_id=stop_id,
    )
    status = result.get("status_code")
    if status == 404:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Best-effort unsubscribe confirmation notification
    msg = f"You have unsubscribed from alerts for Bus {bus_id} at stop {stop_id}."
    try:
        print(f"[routes_agent] unsubscribe: notifying user_id={user_id} bus_id={bus_id} stop_id={stop_id}")
        await notification_service.notify(user_id, msg, channel="sms")
        print(f"[routes_agent] unsubscribe: notification stored for user_id={user_id}")
    except Exception as e:
        print(f"[routes_agent] Failed to send unsubscribe notification: {e}")

    return ok({"message": "Unsubscribed successfully"})
