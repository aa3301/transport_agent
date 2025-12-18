from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class AskRequest(BaseModel):
    query: str = Field(..., min_length=1)

class SubscribeRequest(BaseModel):
    user_id: str
    bus_id: str
    stop_id: str
    notify_before_sec: int = 300
    policy: Optional[Dict[str, Any]] = None
    channel: str = "console"

class LocationUpdate(BaseModel):
    bus_id: str = Field(..., min_length=1)
    lat: float
    lon: float

class StatusUpdate(BaseModel):
    bus_id: str = Field(..., min_length=1)
    status: str
    message: Optional[str] = None
    speed_kmph: Optional[float] = None
