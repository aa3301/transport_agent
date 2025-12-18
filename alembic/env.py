"""
Alembic migration environment.

Purpose:
- Configure automatic migration detection using SQLAlchemy models
- Support both online (DB connected) and offline (generate SQL) migrations

Usage:
- alembic revision --autogenerate -m "Add users table"
- alembic upgrade head
- alembic downgrade -1
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import Base
from config.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL script)."""
    url = settings.MYSQL_ASYNC_URL
    # Replace async driver with sync for migration script generation
    url = url.replace("mysql+aiomysql://", "mysql+pymysql://")
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    """Helper to run migrations with connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    """Run migrations in 'online' mode (async)."""
    # Replace async driver with sync for SQLAlchemy migration support
    url = settings.MYSQL_ASYNC_URL.replace("mysql+aiomysql://", "mysql+pymysql://")
    
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = url
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)
    
    await connectable.dispose()

def run_migrations_online() -> None:
    """Run migrations online (with active DB connection)."""
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
