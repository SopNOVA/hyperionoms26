from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.security import get_current_active_technician
from app.models.customer import Customer
from app.models.ont import Ont
from app.models.olt import OLT
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate

router = APIRouter()


def _match_or_create_ont(db: Session, customer: Customer, gpon_sn: Optional[str], mac: Optional[str], ip: Optional[str], olt_id: Optional[int] = None):
    """Creative matching: if gpon_sn or mac provided on customer, link or create Ont entry. Optionally assign OLT."""
    if not gpon_sn and not mac:
        return None

    ont = None
    if gpon_sn:
        ont = db.query(Ont).filter(Ont.gpon_sn == gpon_sn).first()
    if not ont and mac:
        ont = db.query(Ont).filter(Ont.mac_address == mac).first()

    if ont:
        # Match success! Link it
        ont.customer_id = customer.id
        if ip:
            ont.ip_address = ip
        if mac and not ont.mac_address:
            ont.mac_address = mac
        if olt_id:
            # validate later or assume caller did
            ont.olt_id = olt_id
        db.add(ont)
        return ont
    else:
        # Create the Ont for this client
        new_ont = Ont(
            gpon_sn=gpon_sn or f"AUTO-{customer.id}",
            mac_address=mac,
            ip_address=ip,
            customer_id=customer.id,
            olt_id=olt_id,
            is_active=True,
        )
        db.add(new_ont)
        return new_ont


@router.get("/", response_model=List[CustomerRead])
def list_customers(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(None, description="Search by name, gpon or mac"),
    current_user=Depends(get_current_active_technician),
):
    q = db.query(Customer)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Customer.name.ilike(like)) |
            (Customer.gpon_sn.ilike(like)) |
            (Customer.mac_address.ilike(like)) |
            (Customer.document.ilike(like))
        )
    customers = q.offset(skip).limit(limit).all()
    # Eager load onts for response (simple, no joinedload for brevity)
    for c in customers:
        c.onts = db.query(Ont).filter(Ont.customer_id == c.id).all()
    return customers


@router.post("/", response_model=CustomerRead, status_code=201)
def create_customer(
    customer_in: CustomerCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    """Create client + auto match/create associated ONT by gpon/mac/ip. Matching connects successfully."""
    # Check unique
    if customer_in.gpon_sn and db.query(Customer).filter(Customer.gpon_sn == customer_in.gpon_sn).first():
        raise HTTPException(400, "GPON already registered to another client")
    if customer_in.mac_address and db.query(Customer).filter(Customer.mac_address == customer_in.mac_address).first():
        raise HTTPException(400, "MAC already registered")

    cust_data = customer_in.model_dump(exclude_unset=True)
    cust_data.pop("olt_id", None)
    db_customer = Customer(**cust_data)
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)

    # Validate OLT if provided (for the ONT that will be linked/created)
    if customer_in.olt_id:
        if not db.query(OLT).filter(OLT.id == customer_in.olt_id).first():
            raise HTTPException(404, "OLT no encontrada para asignar al cliente")

    # Matching magic
    ont = _match_or_create_ont(
        db, db_customer,
        gpon_sn=customer_in.gpon_sn,
        mac=customer_in.mac_address,
        ip=None,  # ip usually on the Ont
        olt_id=customer_in.olt_id
    )
    if ont:
        db.commit()
        db.refresh(db_customer)

    # Reload onts
    db_customer.onts = db.query(Ont).filter(Ont.customer_id == db_customer.id).all()
    return db_customer


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_active_technician)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Cliente no encontrado")
    customer.onts = db.query(Ont).filter(Ont.customer_id == customer.id).all()
    return customer


@router.put("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: int,
    customer_in: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Cliente no encontrado")
    for field, value in customer_in.model_dump(exclude_unset=True).items():
        if field == "olt_id":
            continue
        setattr(customer, field, value)
    db.add(customer)
    db.commit()
    db.refresh(customer)

    # If olt_id provided in update, apply to all linked ONTs (and validate)
    if customer_in.olt_id is not None:
        if customer_in.olt_id:
            if not db.query(OLT).filter(OLT.id == customer_in.olt_id).first():
                raise HTTPException(404, "OLT no encontrada")
        for o in db.query(Ont).filter(Ont.customer_id == customer.id).all():
            o.olt_id = customer_in.olt_id
            db.add(o)
        db.commit()

    customer.onts = db.query(Ont).filter(Ont.customer_id == customer.id).all()
    return customer


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Cliente no encontrado")
    db.delete(customer)
    db.commit()
    return {"status": "deleted", "id": customer_id}

