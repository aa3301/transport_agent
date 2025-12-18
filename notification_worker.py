import asyncio
import json
import logging
import os
import aio_pika

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notification_worker")

async def handle_notification_message(message: aio_pika.IncomingMessage):
    """
    Callback for messages in 'notifications' queue.
    """
    async with message.process():
        try:
            body = message.body.decode("utf-8")
            payload = json.loads(body)
            logger.info("[worker] Received notification message: %s", payload)

            msg_type = payload.get("type")
            if msg_type != "notification":
                logger.info("[worker] Ignoring non-notification message type=%s", msg_type)
                return

            user_id = payload.get("user_id")
            text = payload.get("message")
            channel = payload.get("channel", "console")
            phone = payload.get("phone")  # <-- optional phone

            if not user_id or not text:
                logger.warning("[worker] Missing user_id or message in payload: %s", payload)
                return

            from tools import notifier
            logger.info(
                "[worker] Sending notification via notifier: user_id=%s, channel=%s, phone=%s, message=%s",
                user_id, channel, phone, text
            )
            # pass phone through; notifier can still fall back to default if None
            result = notifier.send_notification(user_id, text, channel, phone=phone)
            logger.info("[worker] notifier.send_notification result: %s", result)
        except Exception as e:
            logger.exception("[worker] Error handling notification message: %s", e)

async def main():
    logger.info("[worker] Connecting to RabbitMQ at %s", RABBITMQ_URL)
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    queue_name = "notifications"
    queue = await channel.declare_queue(queue_name, durable=True)
    logger.info("[worker] Waiting for messages in queue '%s'. Press Ctrl+C to exit.", queue_name)
    await queue.consume(handle_notification_message, no_ack=False)

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await connection.close()

if __name__ == "__main__":
    asyncio.run(main())
