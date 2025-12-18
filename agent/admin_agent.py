# agent/admin_agent.py
from services.fleet_service import fleet_service
import logging

logger = logging.getLogger(__name__)

class AdminAgent:
    """
    AdminAgent monitors fleet health, route integrity, and other system-level metrics.
    """

    def __init__(self):
        self.alerts = []

    def check_fleet_health(self):
        """
        Simple health check over current fleet overview.
        This must be defensive: overview entries may be dicts or other shapes.
        """
        try:
            overview = fleet_service.fleet_overview()
        except Exception as e:
            logger.error("[AdminAgent] fleet_overview failed: %s", e)
            return

        if not isinstance(overview, list):
            # Nothing useful to do
            return

        for entry in overview:
            # Skip anything that is not a dict to avoid "'str' object has no attribute 'get'"
            if not isinstance(entry, dict):
                continue

            bus_id = entry.get("bus_id")
            status = entry.get("status", "unknown")
            status_msg = entry.get("status_message", "")

            # You can add simple logging or thresholds here if needed.
            if status != "on_time":
                logger.info(
                    "[AdminAgent] Bus %s has non-normal status: %s (%s)",
                    bus_id, status, status_msg
                )

        # No return value needed; this is a side-effect / logging method.
