"""
Async Kafka producer helper using aiokafka.

Purpose:
- Publish high-volume bus location/status events to Kafka topics
- Use alongside RabbitMQ (RabbitMQ for tasks, Kafka for streaming and replay)
"""
import asyncio
import json
import logging
from aiokafka import AIOKafkaProducer
from config.settings import settings

logger = logging.getLogger(__name__)

class KafkaClient:
    def __init__(self, bootstrap_servers: str = None):
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BROKERS
        self.producer: AIOKafkaProducer | None = None

    async def connect(self):
        try:
            self.producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap_servers)
            await self.producer.start()
            logger.info("Connected to Kafka brokers: %s", self.bootstrap_servers)
        except Exception as e:
            logger.error("Kafka connect failed: %s", e)
            self.producer = None

    async def disconnect(self):
        if self.producer:
            await self.producer.stop()

    async def publish(self, topic: str, value: dict):
        if not self.producer:
            logger.warning("Kafka producer not available")
            return False
        try:
            await self.producer.send_and_wait(topic, json.dumps(value).encode("utf-8"))
            return True
        except Exception as e:
            logger.error("Kafka publish error: %s", e)
            return False

# global client
kafka_client = KafkaClient()
