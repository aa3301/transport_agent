"""
Async MySQL database engine and session management.

Purpose:
- Create SQLAlchemy async engine for MySQL with aiomysql driver
- Provide async session factory for dependency injection
- Provide Base declarative class for ORM models
- Support clean async/await patterns throughout services

Production notes:
- Use connection pooling with appropriate pool_size and max_overflow
- Monitor connection pool metrics in production
- Consider using async context managers for all DB operations
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config.settings import settings
import logging
from typing import AsyncGenerator, Optional  # <-- add Optional here

logger = logging.getLogger(__name__)

Base = declarative_base()

# When MYSQL_ASYNC_URL is "disabled", do not create an engine at all.
engine = None
async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None

if settings.MYSQL_ASYNC_URL and settings.MYSQL_ASYNC_URL != "disabled":
	# Normal DB case
	engine = create_async_engine(
		settings.MYSQL_ASYNC_URL,
		echo=settings.DEBUG,
		future=True,
	)
	async_session_maker = async_sessionmaker(
		engine, expire_on_commit=False, class_=AsyncSession
	)
	logger.info("Async DB engine created: %s", settings.MYSQL_ASYNC_URL)
else:
	logger.warning("MYSQL_ASYNC_URL is 'disabled' – DB engine will not be created; using in-memory fallbacks.")

async def get_db_session() -> AsyncGenerator[Optional[AsyncSession], None]:
	"""
	Yield an AsyncSession when DB is enabled; otherwise yield None so callers can
	fall back to in-memory services.
	"""
	if async_session_maker is None:
		# DB disabled
		yield None
		return

	async with async_session_maker() as session:
		try:
			yield session
		finally:
			await session.close()
