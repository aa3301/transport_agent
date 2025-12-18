import logging
import os

logger = logging.getLogger(__name__)

# Optional Twilio integration
try:
    from twilio.rest import Client as TwilioClient

    TWILIO_SID = os.getenv("TWILIO_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM = os.getenv("TWILIO_FROM", "")  # your Twilio phone number, e.g. "+12025550123"

    twilio_client = (
        TwilioClient(TWILIO_SID, TWILIO_AUTH_TOKEN)
        if TWILIO_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM
        else None
    )
except Exception:
    twilio_client = None


def send_notification(user_id: str, message: str, channel: str = "console", phone: str | None = None):
    """
    Send a notification to the user via the requested channel.

    - console: print to stdout (dev only)
    - sms: if Twilio configured, send real SMS; else simulate via console

    `phone` should be a full E.164 number, e.g. "+919748331232".
    """
    print(f"[notifier] send_notification called: user_id={user_id}, channel={channel}, phone={phone}, message={message}")
    if channel == "sms":
        # Prefer caller's phone; only fallback is for dev/testing.
        target_phone = phone or os.getenv("DEFAULT_SMS_PHONE", "")

        if not target_phone:
            # As a very last resort, keep your own number here for debug only.
            target_phone = "+919748331232"

        if twilio_client:
            try:
                twilio_client.messages.create(
                    to=target_phone,
                    from_=TWILIO_FROM,
                    body=message,
                )
                logger.info("[SMS][Twilio] To %s (%s): %s", user_id, target_phone, message)
                return {"user_id": user_id, "message": message, "channel": "sms", "published": True}
            except Exception as e:
                logger.error("[SMS][Twilio FAILED] To %s (%s): %s (error=%s)", user_id, target_phone, message, e)

        # Fallback: console SMS simulation
        banner = "=" * 60
        logger.info("[SMS][FALLBACK] To %s (%s): %s", user_id, target_phone, message)
        print(banner)
        print(f"[SMS][FALLBACK] To {user_id} ({target_phone}): {message}")
        print(banner)
        return {"user_id": user_id, "message": message, "channel": "sms", "published": False}

    # Default console notification
    logger.info("[NOTIFY] To %s (%s): %s", user_id, channel, message)
    print(f"[NOTIFY] To {user_id} ({channel}): {message}")
    return {"user_id": user_id, "message": message, "channel": channel, "published": False}
