from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class OLTBase(BaseModel):
    name: str
    ip_address: str
    location: Optional[str] = None
    model: Optional[str] = None
    firmware: Optional[str] = None


class OLTCreate(OLTBase):
    pass


class OLTRead(OLTBase):
    id: int
    is_active: bool
    status: str = "UP"
    last_seen_at: Optional[datetime] = None
    last_ping_ms: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class OLTUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
