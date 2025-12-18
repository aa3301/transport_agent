# services/notification_service.py
import logging
logger = logging.getLogger(__name__)

# Try to import RabbitMQ publisher; if not available, fallback to simple notifier tool
try:
    from infra.rabbitmq_client import rabbitmq_client
except Exception:
    rabbitmq_client = None

class NotificationService:
    def __init__(self):
        self.sent_notifications = []

    async def notify(self, user_id: str, message: str, channel: str = "console", phone: str | None = None):
        """
        Async notification send:
        - Preferred: publish to RabbitMQ (notification worker will deliver)
        - Fallback: use local notifier (console or Twilio).

        'phone' is optional; if provided, it is passed through to the worker/notifier.
        """
        if rabbitmq_client:
            try:
                logger.info(
                    "[NotificationService] Publishing to RabbitMQ: user=%s, channel=%s, phone=%s, message=%s",
                    user_id, channel, phone, message
                )
                ok = await rabbitmq_client.publish_notification(user_id, message, channel, phone=phone)  # <-- pass phone
                self.sent_notifications.append(
                    {"user_id": user_id, "message": message, "channel": channel, "published": ok}
                )
                print(f"[NotificationService] stored notification (RabbitMQ): {user_id} {channel} {message}")
                return {"published": ok}
            except Exception as e:
                logger.error("RabbitMQ publish failed: %s", e)
                # fall through to console/Twilio

        # fallback synchronous console/Twilio notifier
        try:
            from tools import notifier
            # tools.notifier already knows how to look up phone when None; we still pass it
            result = notifier.send_notification(user_id, message, channel, phone=phone)  # <-- pass phone
            self.sent_notifications.append(result)
            print(f"[NotificationService] stored notification (fallback): {result}")
            return result
        except Exception as e:
            logger.error("Console/Twilio notify failed: %s", e)
            print(f"[NotificationService] ERROR in notifier.send_notification: {e}")
            return {"error": str(e)}

    async def notify_all(self, message: str, channel: str = "console"):
        """Broadcast a notification to ALL users. Prefer RabbitMQ publish."""
        if rabbitmq_client:
            try:
                logger.info("[NotificationService] Broadcasting to RabbitMQ: channel=%s, message=%s", channel, message)
                ok = await rabbitmq_client.publish_notification("ALL", message, channel, phone=None)  # phone irrelevant
                self.sent_notifications.append(
                    {"user_id": "ALL", "message": message, "channel": channel, "published": ok}
                )
                return {"published": ok}
            except Exception as e:
                logger.error("RabbitMQ broadcast failed: %s", e)
        # fallback
        try:
            from tools import notifier
            result = notifier.send_notification("ALL", message, channel)
            self.sent_notifications.append(result)
            return result
        except Exception as e:
            logger.error("Console broadcast failed: %s", e)
            return {"error": str(e)}

    def recent_notifications(self):
        """Return the last 20 notifications; synchronous helper for compatibility."""
        return self.sent_notifications[-20:]

# singleton
notification_service = NotificationService()
