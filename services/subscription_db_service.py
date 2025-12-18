"""
DB-backed subscription service using async SQLAlchemy.

This is the Python/SQLAlchemy equivalent of using Sequelize models in Node.js:
- add_subscription  -> INSERT or fail on duplicate
- remove_subscription -> DELETE
- list_subscriptions -> SELECT (optionally filtered by user_id)

It is *only* used when:
- USE_DB=true
- MYSQL_ASYNC_URL is not "disabled"
- an AsyncSession is available
"""

from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from models.db_models import Subscription
import logging

logger = logging.getLogger(__name__)


class SubscriptionDBService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_subscription(
        self,
        user_id: str,
        bus_id: str,
        stop_id: str,
        notify_before_sec: int = 300,
        policy: Optional[Dict[str, Any]] = None,
        channel: str = "console",
    ) -> Dict[str, Any]:
        """
        Insert a subscription row. If a duplicate (user_id,bus_id,stop_id) exists
        we return a 409-style response, just like the in-memory service.

        This is similar to doing:
        INSERT INTO subscriptions (...) VALUES (...)
        with a UNIQUE (user_id,bus_id,stop_id) in SQL/Sequelize.
        """
        # First, check if subscription already exists (even if UNIQUE is commented out)
        try:
            stmt = (
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .where(Subscription.bus_id == bus_id)
                .where(Subscription.stop_id == stop_id)
                .where(Subscription.is_active == True)  # noqa: E712
            )
            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                logger.info("DB duplicate subscription: %s:%s:%s", user_id, bus_id, stop_id)
                return {
                    "error": "Subscription already exists",
                    "status_code": 409,
                    "data": self._to_dict(existing),
                }

            sub = Subscription(
                user_id=user_id,
                bus_id=bus_id,
                stop_id=stop_id,
                notify_before_sec=notify_before_sec,
                policy=policy,
                channel=channel,
                is_active=True,
            )
            self.session.add(sub)
            await self.session.commit()
            await self.session.refresh(sub)
            return {
                "message": "Subscribed successfully",
                "subscription": self._to_dict(sub),
                "status_code": 201,
            }
        except IntegrityError as ie:
            # If later you add UNIQUE(user_id,bus_id,stop_id) in DB, this will catch it
            await self.session.rollback()
            logger.warning("IntegrityError on add_subscription (%s)", ie)
            return {
                "error": "Subscription already exists",
                "status_code": 409,
            }
        except Exception as e:
            await self.session.rollback()
            logger.error("DB add_subscription error: %s", e)
            return {
                "error": "Internal error adding subscription",
                "status_code": 500,
            }

    async def remove_subscription(
        self,
        user_id: str,
        bus_id: str,
        stop_id: str,
    ) -> Dict[str, Any]:
        """Remove a subscription row from the DB.

        We *delete* the row instead of soft-deleting so that
        SELECT * FROM subscriptions in MySQL reflects only
        active subscriptions, which matches how you inspect
        the table during manual testing.
        """
        try:
            stmt = (
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .where(Subscription.bus_id == bus_id)
                .where(Subscription.stop_id == stop_id)
            )
            result = await self.session.execute(stmt)
            sub = result.scalar_one_or_none()
            if not sub:
                return {"error": "Subscription not found", "status_code": 404}
            # Hard delete so row disappears from the table
            await self.session.delete(sub)
            await self.session.commit()
            return {"message": "Unsubscribed successfully", "status_code": 200}
        except Exception as e:
            await self.session.rollback()
            logger.error("DB remove_subscription error: %s", e)
            return {"error": "Internal error removing subscription", "status_code": 500}

    async def list_subscriptions(
        self,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List active subscriptions. Optionally filter by user_id.

        Equivalent to:
        SELECT * FROM subscriptions WHERE is_active=1 [AND user_id = ?]
        """
        try:
            stmt = select(Subscription).where(Subscription.is_active == True)  # noqa: E712
            if user_id:
                stmt = stmt.where(Subscription.user_id == user_id)

            result = await self.session.execute(stmt)
            subs = result.scalars().all()
            return [self._to_dict(s) for s in subs]
        except Exception as e:
            logger.error("DB list_subscriptions error: %s", e)
            return []

    @staticmethod
    def _to_dict(sub: Subscription) -> Dict[str, Any]:
        """Convert ORM Subscription to dict compatible with Pydantic Subscription model."""
        return {
            "user_id": sub.user_id,
            "bus_id": sub.bus_id,
            "stop_id": sub.stop_id,
            "notify_before_sec": sub.notify_before_sec,
            "policy": sub.policy,
            "channel": sub.channel,
            "is_active": sub.is_active,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        }
