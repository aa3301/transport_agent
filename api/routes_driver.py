# api/routes_driver.py
from fastapi import APIRouter, HTTPException, Depends
from models.schemas import LocationUpdate, StatusUpdate
from core.response import ok
from core.db import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

# Optional DB-backed fleet service
try:
    from services.fleet_db_service import FleetDBService
except Exception:
    FleetDBService = None

# Optional RabbitMQ publisher
try:
    from infra.rabbitmq_client import rabbitmq_client
except Exception:
    rabbitmq_client = None

# Always import in-memory singleton; used as fallback and when DB off
from services.fleet_service import fleet_service

router = APIRouter()


@router.post("/location")
async def post_location(
    payload: LocationUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Driver updates GPS location for a bus.

    Request JSON (LocationUpdate):
    {
      "bus_id": "B1",
      "lat": 22.57,
      "lon": 88.36
    }

    Response JSON:
    {
      "ok": true,
      "data": {
        "status": "updated",
        "bus": {
          "bus_id": "B1",
          "lat": ...,
          "lon": ...,
          "route_id": "...",
          "status": "...",
          "status_message": "...",
          "speed_kmph": ...
        }
      }
    }
    """
    try:
        bus_id = payload.bus_id
        lat = payload.lat
        lon = payload.lon

        if bus_id is None or lat is None or lon is None:
            raise HTTPException(status_code=400, detail="bus_id, lat and lon are required")

        # Use DB-backed or in-memory based on config
        use_db = (
            settings.USE_DB
            and FleetDBService is not None
            and session is not None
            and not settings.MYSQL_ASYNC_URL.startswith("disabled")
        )

        if use_db:
            try:
                fs = FleetDBService(session)
                # DB version should persist location and speed if provided
                bus = await fs.update_bus_location(bus_id, lat, lon, speed_kmph=None)
            except Exception as e:
                logger.warning("DB update_bus_location failed (%s), falling back to in-memory", e)
                bus = fleet_service.update_bus_location(bus_id, lat, lon)
        else:
            bus = fleet_service.update_bus_location(bus_id, lat, lon)

        # Normalize returned bus for clients
        # For in-memory fleet_service, we know structure; for DB, accept dict/object
        if isinstance(bus, dict):
            normalized_bus = {
                "bus_id": bus_id,
                "lat": bus.get("lat"),
                "lon": bus.get("lon"),
                "route_id": bus.get("route_id"),
                "status": bus.get("status", "unknown"),
                "status_message": bus.get("status_message", ""),
                "speed_kmph": bus.get("speed_kmph", 0.0),
            }
        else:
            normalized_bus = {
                "bus_id": getattr(bus, "bus_id", bus_id),
                "lat": getattr(bus, "lat", None),
                "lon": getattr(bus, "lon", None),
                "route_id": getattr(bus, "route_id", None),
                "status": getattr(bus, "status", "unknown"),
                "status_message": getattr(bus, "status_message", ""),
                "speed_kmph": getattr(bus, "speed_kmph", 0.0),
            }

        # Publish event best-effort
        if rabbitmq_client:
            try:
                speed_val = float(normalized_bus.get("speed_kmph") or 0.0)
                logger.info("[routes_driver] Publishing bus_location to RabbitMQ: bus_id=%s, lat=%s, lon=%s, speed=%s",
                            bus_id, lat, lon, speed_val)
                await rabbitmq_client.publish_bus_location(bus_id, lat, lon, speed_val)
            except Exception as e:
                logger.warning("RabbitMQ publish_bus_location failed: %s", e)

        return ok({"status": "updated", "bus": normalized_bus})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("post_location failed for bus_id=%s payload=%s", getattr(payload, "bus_id", None), payload)
        raise HTTPException(status_code=500, detail="Internal server error while updating location")


@router.post("/status")
async def post_status(
    payload: StatusUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Driver updates bus status (on_time, delayed, breakdown, etc.).

    Request JSON (StatusUpdate):
    {
      "bus_id": "B1",
      "status": "delayed",
      "message": "Traffic jam near S2"
    }

    Response JSON:
    {
      "ok": true,
      "data": {
        "status": "updated",
        "bus_id": "B1",
        "new_status": "delayed",
        "message": "Traffic jam near S2"
      }
    }
    """
    try:
        bus_id = payload.bus_id
        if not bus_id:
            raise HTTPException(status_code=400, detail="bus_id is required")
        speed_val = payload.speed_kmph

        use_db = (
            settings.USE_DB
            and FleetDBService is not None
            and session is not None
            and not settings.MYSQL_ASYNC_URL.startswith("disabled")
        )
        bus = None

        if use_db:
            try:
                fs = FleetDBService(session)
                updated = await fs.update_bus_status(bus_id, payload.status, payload.message, speed_kmph=speed_val)
                if not updated:
                    raise HTTPException(status_code=404, detail="Bus not found")
                bus = updated
            except Exception as e:
                logger.warning("DB update_bus_status failed (%s), falling back to in-memory", e)
                use_db = False

        if not use_db:
            # Read from in-memory, then update the underlying store directly
            bus = fleet_service.get_bus_status(bus_id)
            if not bus:
                raise HTTPException(status_code=404, detail="Bus not found")
            # update in-memory source of truth
            raw_bus = fleet_service.buses.get(bus_id, {})
            raw_bus["status"] = payload.status
            if payload.message:
                raw_bus["status_message"] = payload.message
            if speed_val is not None:
                raw_bus["speed_kmph"] = float(speed_val)
            fleet_service.buses[bus_id] = raw_bus
            # also update the status dict we return
            bus["status"] = raw_bus["status"]
            bus["status_message"] = raw_bus.get("status_message", "")

        # Publish status change event best-effort
        if rabbitmq_client:
            try:
                logger.info("[routes_driver] Publishing bus_status to RabbitMQ: bus_id=%s, status=%s, message=%s",
                            bus_id, payload.status, payload.message or "")
                await rabbitmq_client.publish_bus_status(bus_id, payload.status, payload.message or "")
            except Exception as e:
                logger.warning("RabbitMQ publish_bus_status failed: %s", e)

        return ok({
            "status": "updated",
            "bus_id": bus_id,
            "new_status": payload.status,
            "message": payload.message,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("post_status failed for bus_id=%s payload=%s", getattr(payload, "bus_id", None), payload)
        raise HTTPException(status_code=500, detail="Internal server error while updating status")


@router.get("/route")
async def get_route(
    bus_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Fetch route info for a bus.

    Response JSON:
    {
      "ok": true,
      "data": {
        "bus": { ...bus status... },
        "route": {
          "stops": [
            {"stop_id": "S1", "name": "...", "lat": ..., "lon": ...},
            ...
          ]
        }
      }
    }
    """
    try:
        if not bus_id:
            raise HTTPException(status_code=400, detail="bus_id is required")

        use_db = (
            settings.USE_DB
            and FleetDBService is not None
            and session is not None
            and not settings.MYSQL_ASYNC_URL.startswith("disabled")
        )
        status = None
        route = None

        if use_db:
            try:
                fs = FleetDBService(session)
                status = await fs.get_bus_status(bus_id)
                if not status:
                    raise HTTPException(status_code=404, detail="Bus not found")
                rid = status.get("route_id") if isinstance(status, dict) else getattr(status, "route_id", None)
                route = await fs.get_route(rid) if rid else None
            except Exception as e:
                logger.warning("DB get_route failed (%s), falling back to in-memory", e)
                use_db = False

        if not use_db:
            status = fleet_service.get_bus_status(bus_id)
            if not status:
                raise HTTPException(status_code=404, detail="Bus not found")
            rid = status.get("route_id")
            route = fleet_service.get_route(rid) if rid else None

        return ok({"bus": status, "route": route})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_route failed for bus_id=%s", bus_id)
        raise HTTPException(status_code=500, detail="Internal server error while fetching route")
