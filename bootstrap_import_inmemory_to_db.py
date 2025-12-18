import asyncio
import json
import os
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from core.db import Base
from models.db_models import Bus, Route  # only touch fleet data here


DATA_DIR = "data"
BUSES_FILE = os.path.join(DATA_DIR, "buses.json")
ROUTES_FILE = os.path.join(DATA_DIR, "routes.json")


async def import_routes(session: AsyncSession):
    """
    Import routes from routes.json into the 'routes' table.
    JSON shape (as used by FleetService):
        {
          "R1": { "stops": [ { "stop_id": "...", "name": "...", "lat": ..., "lon": ... }, ... ] },
          "R2": { ... }
        }
    """
    if not os.path.exists(ROUTES_FILE):
        print(f"[bootstrap] routes.json not found at {ROUTES_FILE}, skipping routes import.")
        return

    try:
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            routes_data = json.load(f)
        if not isinstance(routes_data, dict):
            print("[bootstrap] routes.json is not a dict; skipping.")
            return
    except Exception as e:
        print(f"[bootstrap] Failed to load routes.json: {e}")
        return

    from sqlalchemy.future import select

    for route_id, entry in routes_data.items():
        if not isinstance(entry, dict):
            continue
        stops = entry.get("stops") or []
        async with session.begin():
            # Find existing route by business key
            result = await session.execute(
                select(Route).where(Route.route_id == route_id)
            )
            route = result.scalar_one_or_none()
            if route:
                route.stops = stops
                route.updated_at = datetime.utcnow()
            else:
                route = Route(route_id=route_id, stops=stops)
                session.add(route)
        print(f"[bootstrap] Imported/updated route {route_id} with {len(stops)} stops.")


async def import_buses(session: AsyncSession):
    """
    Import buses from buses.json into the 'buses' table.
    JSON shape (as used by FleetService):
        {
          "B1": {
            "lat": ..., "lon": ..., "route_id": "R1",
            "status": "...", "status_message": "...", "speed_kmph": ...
          },
          "B2": { ... }
        }
    """
    if not os.path.exists(BUSES_FILE):
        print(f"[bootstrap] buses.json not found at {BUSES_FILE}, skipping buses import.")
        return

    try:
        with open(BUSES_FILE, "r", encoding="utf-8") as f:
            buses_data = json.load(f)
        if not isinstance(buses_data, dict):
            print("[bootstrap] buses.json is not a dict; skipping.")
            return
    except Exception as e:
        print(f"[bootstrap] Failed to load buses.json: {e}")
        return

    from sqlalchemy.future import select

    for bus_id, entry in buses_data.items():
        if not isinstance(entry, dict):
            continue

        lat = entry.get("lat")
        lon = entry.get("lon")
        route_id = entry.get("route_id")
        status = entry.get("status", "on_time")
        status_message = entry.get("status_message")
        speed_kmph = entry.get("speed_kmph", 0.0)

        async with session.begin():
            result = await session.execute(
                select(Bus).where(Bus.bus_id == bus_id)
            )
            bus = result.scalar_one_or_none()
            if bus:
                bus.lat = lat
                bus.lon = lon
                bus.route_id = route_id
                bus.status = status
                bus.status_message = status_message
                bus.speed_kmph = speed_kmph
                bus.updated_at = datetime.utcnow()
            else:
                bus = Bus(
                    bus_id=bus_id,
                    lat=lat,
                    lon=lon,
                    route_id=route_id,
                    status=status,
                    status_message=status_message,
                    speed_kmph=speed_kmph,
                )
                session.add(bus)
        print(f"[bootstrap] Imported/updated bus {bus_id} (route={route_id}).")


async def main():
    db_url = settings.MYSQL_ASYNC_URL
    if not db_url or db_url.startswith("disabled"):
        raise RuntimeError(f"MYSQL_ASYNC_URL is not configured correctly: {db_url}")

    # Temporary async engine + sessionmaker just for bootstrap
    engine = create_async_engine(db_url, echo=False, future=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Ensure tables exist (just in case)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        await import_routes(session)
        await import_buses(session)

    await engine.dispose()
    print("✅ Bootstrap import from in-memory JSON to DB completed.")


if __name__ == "__main__":
    asyncio.run(main())
