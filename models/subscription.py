# models/subscription.py
from pydantic import BaseModel
from typing import Optional, Dict

class Policy(BaseModel):
    notify_once: bool = False
    delay_threshold: int = 900  # seconds, default 15min

class Subscription(BaseModel):
    user_id: str
    bus_id: str
    stop_id: str
    notify_before_sec: int = 300
    policy: Policy = Policy()
    channel: Optional[str] = "console"  # 'console' | 'email' | 'push'
