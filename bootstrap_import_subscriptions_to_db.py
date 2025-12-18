import asyncio
import logging

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from core.db import Base
from services.subscription_service import subscription_service
from services.subscription_db_service import SubscriptionDBService  # must exist and be importable

logger = logging.getLogger(__name__)


async def main():
    """
    One-time importer:
    - Reads legacy in-memory subscriptions from SubscriptionService.subscriptions
    - Inserts them into the MySQL 'subscriptions' table via SubscriptionDBService
    """
    db_url = settings.MYSQL_ASYNC_URL
    if not db_url or db_url.startswith("disabled"):
        raise RuntimeError(f"MYSQL_ASYNC_URL is not configured correctly: {db_url}")

    # Temporary async engine + sessionmaker just for bootstrap
    engine = create_async_engine(db_url, echo=False, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Grab current in-memory subscriptions
    inmem_subs = list(subscription_service.subscriptions.values())
    if not inmem_subs:
        print("[bootstrap-subscriptions] No in-memory subscriptions found; nothing to import.")
        await engine.dispose()
        return

    print(f"[bootstrap-subscriptions] Found {len(inmem_subs)} in-memory subscriptions; importing to DB...")

    async with async_session() as session:
        svc = SubscriptionDBService(session)
        for sub in inmem_subs:
            try:
                # sub is a Pydantic Subscription object
                data = sub.dict()
                user_id = data["user_id"]
                bus_id = data["bus_id"]
                stop_id = data["stop_id"]
                notify_before_sec = data.get("notify_before_sec", 300)
                policy = data.get("policy")
                channel = data.get("channel", "console")

                res = await svc.add_subscription(
                    user_id=user_id,
                    bus_id=bus_id,
                    stop_id=stop_id,
                    notify_before_sec=notify_before_sec,
                    policy=policy,
                    channel=channel,
                )
                if res.get("error"):
                    print(f"[bootstrap-subscriptions] Skipped {user_id}:{bus_id}:{stop_id} -> {res['error']}")
                else:
                    print(f"[bootstrap-subscriptions] Imported {user_id}:{bus_id}:{stop_id}")
            except Exception as e:
                logger.error("[bootstrap-subscriptions] Error importing %s: %s", sub, e)

    await engine.dispose()
    print("✅ Bootstrap import of in-memory subscriptions to DB completed.")


if __name__ == "__main__":
    asyncio.run(main())
