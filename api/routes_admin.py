from fastapi import APIRouter, HTTPException, Depends, Body
from core.response import ok
from core.db import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from config.settings import settings

# Optional DB-backed fleet service
try:
    from services.fleet_db_service import FleetDBService
except Exception:
    FleetDBService = None

from services.fleet_service import fleet_service

router = APIRouter()

# Admin auth disabled for now
def require_admin():
    return {"user_id": "demo", "role": "admin"}


@router.get("/fleet/overview")
async def fleet_overview(session: AsyncSession = Depends(get_db_session)):
    """
    Admin: view all buses and their current locations / routes.

    For now, always use in-memory fleet_service so that admin sees the same
    live data that driver/location and driver/status update and that the AI uses.
    """
    try:
        # If you want DB overview later, you can re-enable it here with a safe fallback.
        return ok(fleet_service.fleet_overview())
    except Exception as e:
        print(f"[routes_admin] Unexpected error in fleet_overview: {e}")
        # last-resort: return empty list, but do NOT 500
        return ok([])  # last-resort: empty list


@router.post("/route/update")
async def route_update(
    route_id: str = Body(..., embed=True),
    stops: list[dict] = Body(..., embed=True),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Admin: update or create a route definition.

    Request JSON:
    {
      "route_id": "R1",
      "stops": [
        { "stop_id": "S1", "name": "...", "lat": 22.57, "lon": 88.36 },
        ...
      ]
    }

    This updates both the DB (if enabled) and the in-memory FleetService,
    so DecisionEngine and /ask see the new stop coordinates.
    """
    if not route_id or not isinstance(stops, list) or not stops:
        raise HTTPException(status_code=400, detail="route_id and non-empty stops list are required")

    use_db = (
        getattr(settings, "USE_DB", False)
        and FleetDBService is not None
        and session is not None
        and not getattr(settings, "MYSQL_ASYNC_URL", "disabled").startswith("disabled")
    )
    updated = None
    if use_db:
        try:
            fs = FleetDBService(session)
            updated = await fs.update_route(route_id, stops)
        except Exception as e:
            print(f"[routes_admin] DB update_route failed ({e}), falling back to in-memory")

    # Always update in-memory singleton too, so /ask & overview see consistent data
    mem_updated = fleet_service.update_route(route_id, stops)

    return ok({"message": f"Route {route_id} updated", "db": updated, "memory": mem_updated})
