"""
RabbitMQ client for async task queues and event publishing.

Purpose:
- Publish events (bus location updates, delays, breakdowns) to RabbitMQ
- Consume notifications from queue and deliver to users
- Support multiple consumers for horizontal scaling

Events:
- notification.delivery: user notifications (from agent/services)
- bus.location.updated: driver sends GPS update
- bus.delayed: fleet service marks bus as delayed
- bus.breakdown: fleet service marks bus as broken down

Production notes:
- Use message acknowledgment for reliability (no message loss)
- Implement dead-letter queues (DLQ) for failed messages
- Monitor queue depth and consumer lag
- Use durable queues and persistent messages
"""
import os
import json
import asyncio
import logging
from typing import Optional

import aio_pika  # async RabbitMQ client

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

class RabbitMQClient:
    """
    Simple async RabbitMQ publisher client.

    Queues used:
      - notifications  : for user notifications (OTP, ETA, subscribe/unsubscribe, etc.)
      - bus_location   : for bus location updates (future analytics/consumers)
      - bus_status     : for bus status updates
    """
    def __init__(self, url: str):
        self.url = url
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        # We use separate queues with the same channel
        self._notifications_queue_name = "notifications"
        self._bus_location_queue_name = "bus_location"
        self._bus_status_queue_name = "bus_status"

    async def _ensure_connection(self):
        """
        Lazily connect to RabbitMQ and open a channel.
        """
        if self._connection and not self._connection.is_closed:
            return
        logger.info("[RabbitMQClient] Connecting to %s", self.url)
        self._connection = await aio_pika.connect_robust(self.url)
        self._channel = await self._connection.channel()
        # Ensure queues exist (idempotent)
        await self._channel.declare_queue(self._notifications_queue_name, durable=True)
        await self._channel.declare_queue(self._bus_location_queue_name, durable=True)
        await self._channel.declare_queue(self._bus_status_queue_name, durable=True)
        logger.info("[RabbitMQClient] Connected and queues declared")

    async def publish_notification(self, user_id: str, message: str, channel: str = "console", phone: str | None = None):
        """
        Publish a notification event to the 'notifications' queue.

        Payload shape:
        {
          "type": "notification",
          "user_id": "...",
          "message": "...",
          "channel": "sms|console|...",
          "phone": "+91..." | null
        }
        """
        await self._ensure_connection()
        assert self._channel is not None
        payload = {
            "type": "notification",
            "user_id": user_id,
            "message": message,
            "channel": channel,
            "phone": phone,
        }
        body = json.dumps(payload).encode("utf-8")
        logger.info("[RabbitMQClient] Publishing notification: %s", payload)
        await self._channel.default_exchange.publish(
            aio_pika.Message(
                body=body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=self._notifications_queue_name,
        )
        return True

    async def publish_bus_location(self, bus_id: str, lat: float, lon: float, speed_kmph: float = 0.0):
        """
        Publish bus location event to 'bus_location' queue.
        """
        await self._ensure_connection()
        assert self._channel is not None
        payload = {
            "type": "bus_location",
            "bus_id": bus_id,
            "lat": float(lat),
            "lon": float(lon),
            "speed_kmph": float(speed_kmph),
        }
        body = json.dumps(payload).encode("utf-8")
        logger.info("[RabbitMQClient] Publishing bus_location: %s", payload)
        await self._channel.default_exchange.publish(
            aio_pika.Message(body=body, content_type="application/json", delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=self._bus_location_queue_name,
        )
        return True

    async def publish_bus_status(self, bus_id: str, status: str, message: str = ""):
        """
        Publish bus status event to 'bus_status' queue.
        """
        await self._ensure_connection()
        assert self._channel is not None
        payload = {
            "type": "bus_status",
            "bus_id": bus_id,
            "status": status,
            "message": message or "",
        }
        body = json.dumps(payload).encode("utf-8")
        logger.info("[RabbitMQClient] Publishing bus_status: %s", payload)
        await self._channel.default_exchange.publish(
            aio_pika.Message(body=body, content_type="application/json", delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=self._bus_status_queue_name,
        )
        return True

# Singleton instance, used by other services
rabbitmq_client = RabbitMQClient(RABBITMQ_URL)
