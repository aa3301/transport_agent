# models/plan.py
from pydantic import BaseModel
from typing import Any, Dict

class AgentPlan(BaseModel):
    user_id: str
    action: str
    params: Dict[str, Any]
    reason: str | None = None
