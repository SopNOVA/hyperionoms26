from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class OntBase(BaseModel):
    gpon_sn: str
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    model: Optional[str] = None
    customer_id: Optional[int] = None
    olt_id: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class OntCreate(OntBase):
    pass


class OntRead(OntBase):
    id: int
    is_active: bool
    last_seen_at: Optional[datetime] = None
    created_at: datetime
    # populated in list for UI summaries (client name + for future status)
    customer_name: Optional[str] = None

    class Config:
        from_attributes = True
        extra = "allow"


class OntUpdate(BaseModel):
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    model: Optional[str] = None
    customer_id: Optional[int] = None
    olt_id: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
