from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import get_current_active_technician
from app.models.olt import OLT
from app.models.ont import Ont
from app.models.ping_log import PingLog
from app.schemas.olt import OLTCreate, OLTRead, OLTUpdate
from datetime import datetime, timezone

from app.core.ping import robust_ping

router = APIRouter()


@router.get("/", response_model=List[OLTRead])
def list_olts(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = Query(None, description="Filter by UP/DOWN/DEGRADED"),
    current_user=Depends(get_current_active_technician),
):
    q = db.query(OLT)
    if status:
        q = q.filter(OLT.status == status.upper())
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=OLTRead, status_code=201)
def create_olt(olt_in: OLTCreate, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    if db.query(OLT).filter(OLT.ip_address == olt_in.ip_address).first():
        raise HTTPException(409, "OLT con esa IP ya existe")
    db_olt = OLT(**olt_in.model_dump())
    db.add(db_olt)
    db.commit()
    db.refresh(db_olt)
    return db_olt


@router.get("/{olt_id}", response_model=OLTRead)
def get_olt(olt_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    olt = db.query(OLT).filter(OLT.id == olt_id).first()
    if not olt:
        raise HTTPException(404, "OLT no encontrada")
    return olt


@router.put("/{olt_id}", response_model=OLTRead)
def update_olt(olt_id: int, olt_in: OLTUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    olt = db.query(OLT).filter(OLT.id == olt_id).first()
    if not olt:
        raise HTTPException(404, "OLT no encontrada")
    for k, v in olt_in.model_dump(exclude_unset=True).items():
        setattr(olt, k, v)
    db.add(olt)
    db.commit()
    db.refresh(olt)
    return olt


@router.get("/{olt_id}/clients")
def get_olt_clients(olt_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    """List clients (via their ONTs) attached to this OLT. If OLT down, they are impacted."""
    olt = db.query(OLT).filter(OLT.id == olt_id).first()
    if not olt:
        raise HTTPException(404, "OLT no encontrada")
    onts = db.query(Ont).filter(Ont.olt_id == olt_id).all()
    # Return enriched
    return {
        "olt": {"id": olt.id, "name": olt.name, "status": olt.status, "ip": olt.ip_address},
        "impacted_clients_count": len(onts),
        "onts": [{"gpon_sn": o.gpon_sn, "ip": o.ip_address, "customer_id": o.customer_id} for o in onts]
    }


@router.post("/{olt_id}/ping")
def ping_olt_now(olt_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    """Manual ping for an OLT (useful for testing from UI). Updates status and last_ping_ms."""
    olt = db.query(OLT).filter(OLT.id == olt_id).first()
    if not olt:
        raise HTTPException(404, "OLT no encontrada")

    is_alive, rtt, err = robust_ping(olt.ip_address, count=2, timeout=2)
    status = "UP" if (is_alive and rtt is not None) else "DOWN"
    ping_ms = rtt if rtt is not None else None
    # Log for history and graphing ping to OLT
    log = PingLog(
        target_type="olt",
        target_id=olt.id,
        ip_address=olt.ip_address,
        status=status,
        ping_ms=ping_ms,
        error=err if not is_alive else None,
    )
    db.add(log)
    if is_alive and rtt is not None:
        olt.last_ping_ms = rtt
        olt.last_seen_at = datetime.now(timezone.utc)
        olt.status = "UP"
        db.add(olt)
        db.commit()
        db.refresh(olt)
        return {"status": "UP", "ping_ms": rtt, "olt": {"id": olt.id, "name": olt.name}}
    else:
        olt.status = "DOWN"
        olt.last_seen_at = datetime.now(timezone.utc)
        db.add(olt)
        db.commit()
        db.refresh(olt)
        return {"status": "DOWN", "error": err or "no response", "olt": {"id": olt.id, "name": olt.name}}


@router.delete("/{olt_id}")
def delete_olt(
    olt_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    olt = db.query(OLT).filter(OLT.id == olt_id).first()
    if not olt:
        raise HTTPException(404, "OLT no encontrada")
    db.delete(olt)
    db.commit()
    return {"status": "deleted", "id": olt_id}
