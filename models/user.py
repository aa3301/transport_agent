# models/user.py
from pydantic import BaseModel

class User(BaseModel):
    user_id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
