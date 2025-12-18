from models.subscription import Subscription
from typing import Dict, List, Optional
import logging
from config.settings import settings
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

# Try to import DB-backed service (optional)
try:
    from services.subscription_db_service import SubscriptionDBService
except Exception:
    SubscriptionDBService = None

class SubscriptionService:
    def __init__(self):
        # legacy in-memory store for dev
        self.subscriptions: Dict[str, Subscription] = {}

    # --- synchronous (legacy) API kept for backward compatibility ---
    def add_subscription(self, sub: Subscription):
        """
        Add subscription to in-memory store.
        Returns dict with 'status_code' (201 created, 409 conflict).
        """
        key = f"{sub.user_id}:{sub.bus_id}:{sub.stop_id}"
        if key in self.subscriptions:
            logger.info("Duplicate subscription attempt: %s", key)
            return {
                "error": "Subscription already exists",
                "status_code": 409,
                "data": self.subscriptions[key].dict(),
            }
        self.subscriptions[key] = sub
        return {
            "message": "Subscribed successfully",
            "subscription": sub.dict(),
            "status_code": 201,
        }

    def remove_subscription(self, user_id: str, bus_id: str, stop_id: str):
        """
        Remove subscription from in-memory store.
        Returns dict with 'status_code' (200 ok, 404 not found).
        """
        key = f"{user_id}:{bus_id}:{stop_id}"
        if key in self.subscriptions:
            del self.subscriptions[key]
            return {"message": "Unsubscribed successfully", "status_code": 200}
        return {"error": "Subscription not found", "status_code": 404}

    def list_subscriptions(self) -> List[Subscription]:
        return list(self.subscriptions.values())

    # --- async DB-backed methods (new) ---
    async def add_subscription_db(self, session, user_id: str, bus_id: str, stop_id: str,
                                  notify_before_sec: int = 300, policy: dict | None = None, channel: str = "console"):
        # Create subscription object
        # Pydantic Subscription.policy expects a Policy, not None.
        # If policy is None, pass an empty dict so Pydantic uses its default Policy().
        normalized_policy = policy or {}
        sub = Subscription(
            user_id=user_id,
            bus_id=bus_id,
            stop_id=stop_id,
            notify_before_sec=notify_before_sec,
            policy=normalized_policy,
            channel=channel,
        )

        if (not settings.USE_DB) or settings.MYSQL_ASYNC_URL.startswith("disabled") or SubscriptionDBService is None or session is None:
            # DB disabled -> fallback to in-memory
            return self.add_subscription(sub)
        
        try:
            svc = SubscriptionDBService(session)
            # Note: Ideally SubscriptionDBService should also check for duplicates and raise/return accordingly.
            # Assuming it returns a dict similar to above or raises IntegrityError.
            return await svc.add_subscription(user_id, bus_id, stop_id,
                                              notify_before_sec=notify_before_sec, policy=policy, channel=channel)
        except (OperationalError, Exception) as e:
            logger.warning("DB add_subscription failed (%s), falling back to in-memory", e)
            return self.add_subscription(sub)

    async def remove_subscription_db(self, session, user_id: str, bus_id: str, stop_id: str):
        if (not settings.USE_DB) or settings.MYSQL_ASYNC_URL.startswith("disabled") or SubscriptionDBService is None or session is None:
            return self.remove_subscription(user_id, bus_id, stop_id)
        try:
            svc = SubscriptionDBService(session)
            return await svc.remove_subscription(user_id, bus_id, stop_id)
        except (OperationalError, Exception) as e:
            logger.warning("DB remove_subscription failed (%s), falling back", e)
            return self.remove_subscription(user_id, bus_id, stop_id)

    async def list_subscriptions_db(self, session, user_id: Optional[str] = None):
        if (not settings.USE_DB) or settings.MYSQL_ASYNC_URL.startswith("disabled") or SubscriptionDBService is None or session is None:
            return self.list_subscriptions()
        try:
            svc = SubscriptionDBService(session)
            return await svc.list_subscriptions(user_id=user_id)
        except (OperationalError, Exception) as e:
            logger.warning("DB list_subscriptions failed (%s), falling back", e)
            return self.list_subscriptions()

subscription_service = SubscriptionService()
