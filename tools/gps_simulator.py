# tools/gps_simulator.py
import random
import httpx

"""GPS helper used by the agent stack.

Order of data sources (most to least preferred):
1. Live Fleet HTTP service on port 8002 (/bus/status)
2. In-memory fleet_service (data/buses.json) for local testing

We deliberately removed the old hard-coded Mumbai coordinates so that
if the HTTP service is down, we still use the same coordinates as the
rest of the system instead of a bus thousands of kilometres away,
which was causing ETAs of 80+ hours.
"""

FLEET_SERVICE_URL = "http://localhost:8002"

try:
    # Optional import; used only for fallback when 8002 is not reachable.
    from services.fleet_service import fleet_service
except Exception:  # pragma: no cover - best‑effort fallback only
    fleet_service = None

def get_bus_location(bus_id: str):
    """
    GPS simulator for a bus:
    - First, try to get live status from Fleet service (8002) /bus/status.
    - If that fails, fallback to local mock + jitter.
    """
    # 1) Try fleet microservice via HTTP
    try:
        url = f"{FLEET_SERVICE_URL}/bus/status"
        resp = httpx.get(url, params={"bus_id": bus_id}, timeout=1.0)
        if resp.status_code == 200:
            data = resp.json()
            # Expect shape: {"ok": true, "data": {...status dict...}}
            status = data.get("data") or data
            if isinstance(status, dict):
                return {
                    "bus_id": status.get("bus_id", bus_id),
                    "lat": status.get("lat"),
                    "lon": status.get("lon"),
                    "speed_kmph": status.get("speed_kmph", 20.0),
                }
    except Exception:
        # silently fall back to local mock if 8002 unavailable
        pass

    # 2) Fallback: use in-memory fleet_service data + small jitter
    if fleet_service is not None:
        try:
            status = fleet_service.get_bus_status(bus_id)
            if isinstance(status, dict):
                lat = status.get("lat")
                lon = status.get("lon")
                speed = status.get("speed_kmph", 20.0)
                if lat is not None and lon is not None:
                    lat = float(lat) + random.uniform(-0.0005, 0.0005)
                    lon = float(lon) + random.uniform(-0.0005, 0.0005)
                    status["lat"] = round(lat, 6)
                    status["lon"] = round(lon, 6)
                status.setdefault("bus_id", bus_id)
                status.setdefault("speed_kmph", speed)
                return status
        except Exception:
            # If anything goes wrong here just fall through to None
            pass

    # 3) Ultimate fallback: no data
    return None
