"""
Fleet Microservice (standalone FastAPI app).

Run:
- uvicorn microservices.fleet_service_app:app --host 0.0.0.0 --port 8002
"""
from fastapi import FastAPI
from core.response import ok
from api import routes_driver, routes_admin
from services.fleet_service import fleet_service
import asyncio
import logging

from config.settings import settings
from core.db import get_db_session
try:
    from services.fleet_db_service import FleetDBService
except Exception:
    FleetDBService = None

logger = logging.getLogger(__name__)
# ...existing optional DB imports if needed...
# from config.settings import settings
# from services.fleet_db_service import FleetDBService
# try:
#     from services.fleet_db_service import FleetDBService
# except Exception:
#     FleetDBService = None

app = FastAPI(title="Fleet Microservice", version="0.1")

# Mount routers with clear prefixes
app.include_router(routes_driver.router, prefix="/driver", tags=["driver"])
app.include_router(routes_admin.router, prefix="/admin", tags=["admin"])


@app.on_event("startup")
async def start_background_location_updater():
    """Background task to gently move bus locations every minute.

    This is only for local testing so that your agentic tools
    always see changing lat/lon without you having to click the
    driver location form manually.
    """

    async def _update_loop():
        while True:
            try:
                use_db = (
                    settings.USE_DB
                    and FleetDBService is not None
                    and not settings.MYSQL_ASYNC_URL.startswith("disabled")
                )

                if use_db:
                    # First, read the current fleet snapshot using one session
                    buses: list[dict] = []
                    async for session in get_db_session():
                        if session is None:
                            break
                        fs = FleetDBService(session)
                        buses = await fs.fleet_overview()
                        break

                    # Then, perform location updates using a *new* session so
                    # that we don't mix a read transaction with write
                    # transactions on the same AsyncSession (which caused
                    # "A transaction is already begun on this Session." errors).
                    if buses:
                        async for session in get_db_session():
                            if session is None:
                                break
                            fs = FleetDBService(session)
                            for b in buses:
                                lat = b.get("lat")
                                lon = b.get("lon")
                                if lat is None or lon is None:
                                    continue
                                new_lat = float(lat) + 0.0005
                                new_lon = float(lon) + 0.0005
                                # keep speed if present, default to 30
                                speed = float(b.get("speed_kmph") or 30.0)
                                await fs.update_bus_location(b["bus_id"], new_lat, new_lon, speed_kmph=speed)
                            break
                    logger.debug("Auto-updated bus locations in DB for testing")
                else:
                    # Fallback: update in-memory buses.json representation only
                    for bus_id, bus in list(fleet_service.buses.items()):
                        if not isinstance(bus, dict):
                            continue
                        lat = bus.get("lat")
                        lon = bus.get("lon")
                        if lat is None or lon is None:
                            continue
                        new_lat = float(lat) + 0.0005
                        new_lon = float(lon) + 0.0005
                        fleet_service.update_bus_location(bus_id, new_lat, new_lon)
                    logger.debug("Auto-updated in-memory bus locations for testing")
            except Exception:
                logger.exception("Background bus location updater failed once; continuing")
            await asyncio.sleep(60)

    asyncio.create_task(_update_loop())

@app.get("/health")
async def health():
    """Health check for fleet service."""
    return ok({"service": "fleet", "status": "ok"})

@app.get("/bus/status")
async def get_bus_status(bus_id: str):
    """
    Simple bus status endpoint (no DB, no auth).
    Returns 404 if bus_id not found in in-memory fleet_service.
    """
    status = fleet_service.get_bus_status(bus_id)
    if not status:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Bus not found")
    return ok(status)

# NOTE:
# All other endpoints (driver/location, driver/status, driver/route,
# admin/fleet/overview, admin/route/update) now live ONLY in:
# - api/routes_driver.py   (under prefix /driver)
# - api/routes_admin.py    (under prefix /admin)
# Remove any duplicate @app.get("/admin/fleet/overview") or @app.post("/driver/location")
# that were previously in this file.
