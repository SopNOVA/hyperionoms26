from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.schemas.ont import OntRead


class CustomerBase(BaseModel):
    name: str
    document: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    mac_address: Optional[str] = None
    gpon_sn: Optional[str] = None  # for quick matching / creation


class CustomerCreate(CustomerBase):
    olt_id: Optional[int] = None  # OLT to assign to the matched/created ONT for this client


class CustomerRead(CustomerBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Include linked ONTs for rich responses
    onts: List[OntRead] = []

    class Config:
        from_attributes = True


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    mac_address: Optional[str] = None
    gpon_sn: Optional[str] = None
    olt_id: Optional[int] = None  # to re-assign OLT to linked ONT(s)
