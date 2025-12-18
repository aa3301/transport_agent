# services/fleet_service.py
import json
import os
import logging

logger = logging.getLogger(__name__)

class FleetService:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.buses = {}
        self.routes = {}

        buses_file = os.path.join(data_dir, "buses.json")
        routes_file = os.path.join(data_dir, "routes.json")

        if os.path.exists(buses_file):
            try:
                with open(buses_file, "r", encoding="utf-8") as f:
                    self.buses = json.load(f)
            except Exception as e:
                logger.error("Failed to load buses.json: %s", e)
                self.buses = {}

        if os.path.exists(routes_file):
            try:
                with open(routes_file, "r", encoding="utf-8") as f:
                    self.routes = json.load(f)
            except Exception as e:
                logger.error("Failed to load routes.json: %s", e)
                self.routes = {}

        if not isinstance(self.buses, dict):
            self.buses = {}
        if not isinstance(self.routes, dict):
            self.routes = {}

    # ------------- BUS -------------
    def get_bus_status(self, bus_id: str):
        """Return a single bus status dict or None."""
        bus = self.buses.get(bus_id)
        if not bus:
            return None
        return {
            "bus_id": bus_id,
            "status": bus.get("status", "unknown"),
            "status_message": bus.get("status_message", "No status available"),
            "lat": bus.get("lat"),
            "lon": bus.get("lon"),
            "route_id": bus.get("route_id"),
            "speed_kmph": bus.get("speed_kmph", 20.0),
        }

    def update_bus_location(self, bus_id: str, lat: float, lon: float):
        """Update bus lat/lon in memory."""
        bus = self.buses.get(bus_id) or {}
        bus["lat"] = lat
        bus["lon"] = lon
        self.buses[bus_id] = bus
        return bus

    # ------------- ROUTE -------------
    def get_route(self, route_id: str):
        return self.routes.get(route_id)

    def update_route(self, route_id: str, new_stops: list[dict]):
        self.routes[route_id] = {"stops": new_stops}
        return self.routes[route_id]

    # ------------- ADMIN -------------
    def fleet_overview(self):
        """Return list of buses with current location + route."""
        overview = []
        for bus_id, bus in self.buses.items():
            if not isinstance(bus, dict):
                continue
            route_id = bus.get("route_id")
            route = self.get_route(route_id) if route_id else None
            overview.append({
                "bus_id": bus_id,
                "lat": bus.get("lat"),
                "lon": bus.get("lon"),
                "route_id": route_id,
                "status": bus.get("status", "unknown"),
                "status_message": bus.get("status_message", ""),
                "route": route,
            })
        return overview

# singleton
fleet_service = FleetService()
