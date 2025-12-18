"""
Notification delivery worker.

Purpose:
- Consume notification messages from RabbitMQ queue
- Deliver notifications via configured channels (console, email, SMS, webhook)
- Implement retry logic and error handling
- Run as a separate process (scale horizontally)

Usage:
- python -m workers.notification_worker

Production notes:
- Run multiple worker instances for load distribution
- Implement exponential backoff for retries
- Track delivery metrics (success rate, latency)
- Implement dead-letter queue for undeliverable messages
"""
import asyncio
import logging
import json
from infra.rabbitmq_client import rabbitmq_client
from config.settings import settings

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class NotificationDeliveryWorker:
    """Worker to deliver notifications from RabbitMQ queue."""
    
    def __init__(self):
        self.delivered = 0
        self.failed = 0
    
    async def deliver(self, notification: dict) -> bool:
        """
        Deliver a single notification.
        
        Args:
            notification: {user_id, message, channel, timestamp}
            
        Returns:
            True if delivered, False otherwise
        """
        user_id = notification.get("user_id")
        message = notification.get("message")
        channel = notification.get("channel", "console")
        
        try:
            if channel == "console":
                # Log to console
                logger.info(f"[NOTIFICATION] {user_id}: {message}")
                self.delivered += 1
                return True
            
            elif channel == "email":
                # TODO: integrate email service (SendGrid, Mailgun, etc.)
                logger.warning(f"Email delivery not yet implemented: {user_id}")
                return False
            
            elif channel == "sms":
                # TODO: integrate SMS service (Twilio, AWS SNS, etc.)
                logger.warning(f"SMS delivery not yet implemented: {user_id}")
                return False
            
            elif channel == "webhook":
                # TODO: call webhook URL (fetch from user profile)
                logger.warning(f"Webhook delivery not yet implemented: {user_id}")
                return False
            
            else:
                logger.error(f"Unknown channel: {channel}")
                return False
        
        except Exception as e:
            logger.error(f"Delivery failed for {user_id}: {e}")
            self.failed += 1
            return False
    
    async def run(self):
        """
        Start consuming and delivering notifications.
        Call this in a separate asyncio task or process.
        """
        logger.info("Notification worker started")
        
        # Connect to RabbitMQ
        await rabbitmq_client.connect()
        
        try:
            # Consume from queue
            await rabbitmq_client.consume_notifications(self.deliver)
        except KeyboardInterrupt:
            logger.info("Worker interrupted")
        finally:
            await rabbitmq_client.disconnect()
            logger.info(f"Worker stopped. Delivered: {self.delivered}, Failed: {self.failed}")

async def main():
    """Entry point for running the worker."""
    worker = NotificationDeliveryWorker()
    await worker.run()

if __name__ == "__main__":
    # Run worker: python -m workers.notification_worker
    asyncio.run(main())
