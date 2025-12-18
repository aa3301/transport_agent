# agent/transport_agent.py
import asyncio
from agent.base_agent import BaseAgent
from services.subscription_service import subscription_service
from services.fleet_service import fleet_service
from services.notification_service import notification_service
from agent.decision_engine import DecisionEngine
from tools import eta_calculator


class TransportAgent(BaseAgent):
    def __init__(self, subscription_service, fleet_service):
        self.subscription_service = subscription_service
        self.fleet_service = fleet_service
        self.running = False
        self.engine = DecisionEngine()

    async def start_loop(self):
        self.running = True
        while self.running:
            await self.loop_once()
            await asyncio.sleep(120)

    async def loop_once(self):
        
        """Check bus statuses + ETA and trigger notifications."""
        print("[Agent] Loop running...")
        try:
            
            for bus_id, bus in self.fleet_service.buses.items():
                status = bus.get("status", "unknown")

                # 🚨 Notify if bus delayed or broken
                if status in ["delayed", "breakdown"]:
                    
                    notification_service.notify_all(
                        message=f"⚠️ Bus {bus_id} status: {status.upper()} - {bus.get('status_message', '')}"
                    )

                # ⏱️ Notify if ETA < 10 min for first stop
                if bus.get("route_id"):
                    route = self.fleet_service.get_route(bus["route_id"])
                    if route and route.get("stops"):
                        stop = route["stops"][0]  # demo: take first stop
                        stop_lat, stop_lon = stop["lat"], stop["lon"]

                        eta_sec = eta_calculator.calculate_eta_seconds(
                            bus["lat"], bus["lon"], stop_lat, stop_lon
                        )

                        if eta_sec < 600:  # less than 10 minutes
                            notification_service.notify_all(
                                message=f"⏱️ Bus {bus_id} will arrive soon (<10 min) at {stop['name']}"
                            )

        except Exception as e:
            print("[Agent] Event trigger error:", e)

    async def stop(self):
        self.running = False
