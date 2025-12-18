# core/singleton.py
from agent.supervisor_agent import SupervisorAgent
from agent.transport_agent import TransportAgent
from services.fleet_service import fleet_service
from services.subscription_service import subscription_service
from services.notification_service import notification_service

# Unified singleton registry
supervisor_agent = SupervisorAgent()
transport_agent = TransportAgent(subscription_service, fleet_service)

__all__ = [
    "supervisor_agent",
    "transport_agent",
    "fleet_service",
    "subscription_service",
    "notification_service"
]
