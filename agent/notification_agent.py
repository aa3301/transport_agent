# agent/notification_agent.py
from services.notification_service import notification_service
from services.subscription_service import subscription_service
from agent.decision_engine import DecisionEngine
import inspect
import asyncio
import math

class NotificationAgent:
    """
    Handles all notifications in real-time and stores logs.
    This agent is tolerant of both sync (legacy) and async DB-backed subscription services.
    """

    def __init__(self):
        self.logs = []

    async def notify_user(self, user_id: str, message: str, channel: str = "console"):
        """
        Notify a single user via NotificationService, preserving channel
        (e.g. console, sms).
        """
        # notification_service.notify is async in new implementation; call accordingly
        notify = getattr(notification_service, "notify", None)
        if inspect.iscoroutinefunction(notify):
            await notification_service.notify(user_id, message, channel=channel)
        else:
            # sync fallback
            notification_service.notify(user_id, message, channel)
        self.logs.append((user_id, message, channel))

    async def notify_all(self, message: str, channel: str = "console"):
        notify_all = getattr(notification_service, "notify_all", None)
        if inspect.iscoroutinefunction(notify_all):
            await notification_service.notify_all(message, channel=channel)
        else:
            notification_service.notify_all(message, channel)
        self.logs.append(("ALL", message, channel))

    async def check_subscriptions(self, session=None):
        """Legacy: just logs subscriptions. Kept for compatibility."""
        # If DB session provided, call DB-backed list; else fallback to legacy in-memory
        subs = []
        try:
            if session and hasattr(subscription_service, "list_subscriptions_db"):
                subs = await subscription_service.list_subscriptions_db(session)
            else:
                # legacy sync call
                subs = subscription_service.list_subscriptions()
            for sub in subs:
                # For now, just log pending reminders
                user_id = getattr(sub, "user_id", sub.get("user_id") if isinstance(sub, dict) else None)
                bus_id = getattr(sub, "bus_id", sub.get("bus_id") if isinstance(sub, dict) else None)
                print(f"[NotificationAgent] Checking reminder for {user_id} on {bus_id}")
        except Exception as e:
            print(f"[NotificationAgent] check_subscriptions error: {e}")
        return subs

    def log_event(self, event_type: str, message: str):
        print(f"[NotificationAgent][{event_type}] {message}")

    # ---------------- NEW: proactive ETA-based notifications ----------------
    async def process_subscriptions(self, engine: DecisionEngine, session=None):
        """
        Check all subscriptions and send notifications when bus ETA to the
        subscribed stop is within notify_before_sec.

        NOTE:
        - To avoid resource exhaustion, we limit how many subs we process per cycle
          and add a small delay between each to avoid socket bursts.
        """
        subs = []
        try:
            svc = subscription_service  # <-- use the singleton directly
            if session and hasattr(svc, "list_subscriptions_db"):
                subs = await svc.list_subscriptions_db(session)
            else:
                subs = svc.list_subscriptions()
        except Exception as e:
            print(f"[NotificationAgent] process_subscriptions: failed to load subscriptions: {e}")
            return

        if not subs:
            return

        # Limit number of processed subscriptions per cycle to avoid overload
        MAX_PER_CYCLE = 20
        subs = subs[:MAX_PER_CYCLE]

        for idx, sub in enumerate(subs):
            try:
                # Support both Pydantic Subscription object and dict shape
                user_id = getattr(sub, "user_id", None) or (sub.get("user_id") if isinstance(sub, dict) else None)
                bus_id = getattr(sub, "bus_id", None) or (sub.get("bus_id") if isinstance(sub, dict) else None)
                stop_id = getattr(sub, "stop_id", None) or (sub.get("stop_id") if isinstance(sub, dict) else None)
                notify_before = getattr(sub, "notify_before_sec", None) or (
                    sub.get("notify_before_sec") if isinstance(sub, dict) else None
                )
                channel = getattr(sub, "channel", None) or (sub.get("channel") if isinstance(sub, dict) else "console")
                #                  ^^^^^^^^^^^^^^^^^^^^^  NEW: read channel

                if not user_id or not bus_id or not stop_id:
                    continue  # skip malformed subscription

                try:
                    notify_before = int(notify_before) if notify_before is not None else 300
                except Exception:
                    notify_before = 300

                # Ask DecisionEngine for ETA in a structured prompt
                # Use a fixed English prompt so the agent focuses on tools, not language.
                query = f"ETA for Bus {bus_id} to reach stop {stop_id}?"
                engine_result = await engine.ask(query)
                eta_sec = None
                for tr in engine_result.get("tool_results", []):
                    step = tr.get("step") or {}
                    if step.get("tool") == "eta" and isinstance(tr.get("result"), dict):
                        eta_res = tr["result"]
                        eta_sec = eta_res.get("eta_sec") or eta_res.get("eta")
                        break

                if eta_sec is None:
                    continue  # cannot compute ETA, skip for now

                try:
                    eta_sec = int(eta_sec)
                except Exception:
                    continue

                # If ETA is within threshold, send notification
                if 0 <= eta_sec <= notify_before:
                    minutes = max(1, eta_sec // 60)
                    msg = (
                        f"Bus {bus_id} is expected to reach stop {stop_id} in about "
                        f"{minutes} minute{'s' if minutes != 1 else ''}."
                    )
                    # pass the channel through (console/sms)
                    await self.notify_user(user_id, msg, channel=channel)
                    self.log_event("NotifyETA", f"Notified {user_id} for {bus_id}->{stop_id} ETA={eta_sec}s")

                # Tiny delay to avoid opening too many sockets in a tight loop
                await asyncio.sleep(0.1)

            except Exception as e:
                print(f"[NotificationAgent] process_subscriptions error for sub={sub}: {e}")
