from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import get_current_active_technician
from app.models.ont import Ont
from app.models.olt import OLT
from app.models.customer import Customer
from app.models.ping_log import PingLog
from app.schemas.ont import OntRead, OntCreate, OntUpdate
from datetime import datetime, timezone

from app.core.ping import robust_ping

router = APIRouter()


@router.get("/", response_model=List[OntRead])
def list_onts(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    olt_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    current_user=Depends(get_current_active_technician),
):
    q = db.query(Ont)
    if olt_id:
        q = q.filter(Ont.olt_id == olt_id)
    onts = q.offset(skip).limit(limit).all()
    # Batch load customer names for summaries (optimize for 1000+ ONUs lists)
    cust_ids = [o.customer_id for o in onts if o.customer_id]
    cust_map = {}
    if cust_ids:
        for c in db.query(Customer).filter(Customer.id.in_(cust_ids)).all():
            cust_map[c.id] = c.name

    # Batch load OLT info so it is visible in lists (as requested)
    olt_ids = [o.olt_id for o in onts if o.olt_id]
    olt_map = {}
    if olt_ids:
        for olt in db.query(OLT).filter(OLT.id.in_(olt_ids)).all():
            olt_map[olt.id] = {"name": olt.name, "status": olt.status, "ip": olt.ip_address}

    for o in onts:
        if o.customer_id and o.customer_id in cust_map:
            setattr(o, 'customer_name', cust_map[o.customer_id])
        if o.olt_id and o.olt_id in olt_map:
            olt_info = olt_map[o.olt_id]
            setattr(o, 'olt_name', olt_info["name"])
            setattr(o, 'olt_status', olt_info["status"])
            setattr(o, 'olt_ip', olt_info["ip"])
    return onts


@router.post("/", response_model=OntRead, status_code=201)
def create_ont(ont_in: OntCreate, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    # Duplicate gpon check (unique constraint will also catch)
    if db.query(Ont).filter(Ont.gpon_sn == ont_in.gpon_sn).first():
        raise HTTPException(status_code=409, detail="GPON SN ya existe")

    if ont_in.mac_address and db.query(Ont).filter(Ont.mac_address == ont_in.mac_address).first():
        raise HTTPException(status_code=409, detail="MAC ya registrada")

    # Validate OLT if provided
    if ont_in.olt_id:
        if not db.query(OLT).filter(OLT.id == ont_in.olt_id).first():
            raise HTTPException(404, "OLT no encontrada")

    db_ont = Ont(**ont_in.model_dump(exclude_unset=True))
    db.add(db_ont)
    db.commit()
    db.refresh(db_ont)
    return db_ont


@router.get("/{gpon_sn}", response_model=OntRead)
def get_ont_by_gpon(gpon_sn: str, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    ont = db.query(Ont).filter(Ont.gpon_sn == gpon_sn).first()
    if not ont:
        raise HTTPException(status_code=404, detail="ONU no encontrada")

    # Enrich with OLT info for detail views
    if ont.olt_id:
        olt = db.query(OLT).filter(OLT.id == ont.olt_id).first()
        if olt:
            setattr(ont, 'olt_name', olt.name)
            setattr(ont, 'olt_status', olt.status)
            setattr(ont, 'olt_ip', olt.ip_address)

    # Also enrich customer if present
    if ont.customer_id:
        cust = db.query(Customer).filter(Customer.id == ont.customer_id).first()
        if cust:
            setattr(ont, 'customer_name', cust.name)

    return ont


@router.put("/{ont_id}", response_model=OntRead)
def update_ont(
    ont_id: int,
    ont_in: OntUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    ont = db.query(Ont).filter(Ont.id == ont_id).first()
    if not ont:
        raise HTTPException(404, "ONU no encontrada")
    for field, value in ont_in.model_dump(exclude_unset=True).items():
        setattr(ont, field, value)
    db.add(ont)
    db.commit()
    db.refresh(ont)
    return ont


@router.delete("/{ont_id}")
def delete_ont(
    ont_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    ont = db.query(Ont).filter(Ont.id == ont_id).first()
    if not ont:
        raise HTTPException(404, "ONU no encontrada")
    db.delete(ont)
    db.commit()
    return {"status": "deleted", "id": ont_id}


@router.post("/{ont_id}/ping")
def ping_ont_now(ont_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    """Manual ping for an ONT's IP (the client WAN IP from probe)."""
    ont = db.query(Ont).filter(Ont.id == ont_id).first()
    if not ont:
        raise HTTPException(404, "ONU no encontrada")
    if not ont.ip_address:
        return {"status": "NO_IP", "ont": {"id": ont.id, "gpon_sn": ont.gpon_sn}}

    is_alive, rtt, err = robust_ping(ont.ip_address, count=2, timeout=2)
    status = "UP" if (is_alive and rtt is not None) else "DOWN"
    ping_ms = rtt if rtt is not None else None
    # Log for history and graphing
    log = PingLog(
        target_type="ont",
        target_id=ont.id,
        ip_address=ont.ip_address,
        status=status,
        ping_ms=ping_ms,
        error=err if not is_alive else None,
    )
    db.add(log)
    if is_alive and rtt is not None:
        ont.last_seen_at = datetime.now(timezone.utc)
        ont.last_ping_ms = rtt
        db.add(ont)
        db.commit()
        db.refresh(ont)
        return {"status": "UP", "ping_ms": rtt, "ont": {"id": ont.id, "gpon_sn": ont.gpon_sn}}
    else:
        db.commit()
        # On real failure, still report DOWN with the real error (no more fake 50ms sim hiding the truth)
        return {"status": "DOWN", "error": err or "no response", "ont": {"id": ont.id, "gpon_sn": ont.gpon_sn}}

