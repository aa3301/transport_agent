import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import settings
from core.db import Base  # Base is already defined here
from models import db_models  # noqa: F401 ensure models are imported so tables are registered


async def main():
    """
    One-time script to create all tables in the configured MySQL database.
    Uses a temporary async engine built from settings.MYSQL_ASYNC_URL.
    """
    db_url = settings.MYSQL_ASYNC_URL
    if not db_url or db_url.startswith("disabled"):
        raise RuntimeError(f"MYSQL_ASYNC_URL is not configured correctly: {db_url}")

    engine = create_async_engine(db_url, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("✅ Database schema created/updated successfully.")


if __name__ == "__main__":
    asyncio.run(main())
