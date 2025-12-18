import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient


# Ensure project root is on sys.path so `microservices.*` imports work
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


# Explicitly enable pytest-asyncio plugin for async tests/fixtures
pytest_plugins = ("pytest_asyncio",)


# We import the microservices as normal Python modules so the
# tests can call their endpoints in-memory without starting
# real HTTP servers.
from microservices.auth_service_app import app as auth_app
from microservices.agent_service_app import app as agent_app


@pytest_asyncio.fixture()
async def auth_client():
    """Async test client for the Auth microservice."""
    async with AsyncClient(app=auth_app, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture()
async def agent_client():
    """Async test client for the Agent microservice."""
    async with AsyncClient(app=agent_app, base_url="http://testserver") as ac:
        yield ac
