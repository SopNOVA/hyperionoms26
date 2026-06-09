"""
Ping sensor + OLT status propagation service.
Runs every 1 minute. If OLT down → mark linked ONTs/clients impacted (via status + alerts generation).
Uses robust_ping (icmplib + system /bin/ping fallback) so real low-latency times are reported (e.g. 1-2ms) instead of fake dev simulations.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.ping import robust_ping
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.olt import OLT
from app.models.ping_log import PingLog
from app.models.ont import Ont
from app.models.telemetry import TelemetryEvent

logger = logging.getLogger("hyperion.monitor")

scheduler = AsyncIOScheduler(timezone="UTC")


def _get_db() -> Session:
    return SessionLocal()


def ping_olt(olt: OLT, db: Session) -> Optional[int]:
    """Ping single OLT using robust method (icmplib + system ping fallback). Returns avg rtt ms or None if down."""
    is_alive, rtt, err = robust_ping(olt.ip_address, count=2, timeout=2)
    status = "UP" if (is_alive and rtt is not None) else "DOWN"
    ping_ms = rtt if rtt is not None else None
    # Log ping for graphing history (optimization: we can query these for OLT ping graphs)
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
        logger.info(f"OLT {olt.name} ({olt.ip_address}) UP - {rtt}ms")
        return rtt
    else:
        olt.status = "DOWN"
        olt.last_seen_at = datetime.now(timezone.utc)
        db.add(olt)
        logger.warning(f"OLT {olt.name} ({olt.ip_address}) DOWN: {err}")
        return None


def propagate_olt_outage(olt: OLT, db: Session):
    """If OLT is DOWN, create synthetic critical telemetry for linked ONTs so UI shows them down too."""
    if olt.status != "DOWN":
        return
    linked_onts = db.query(Ont).filter(Ont.olt_id == olt.id, Ont.is_active == True).all()
    for ont in linked_onts:
        # Create a critical event so dashboard/alerts pick it up
        event = TelemetryEvent(
            ont_id=ont.id,
            classification="CRITICAL",
            reason=f"OLT {olt.name} DOWN - todos los clientes en esta OLT impactados",
            data={
                "source": "olt_sensor",
                "olt_id": olt.id,
                "olt_name": olt.name,
                "olt_ip": olt.ip_address,
                "note": "Propagated outage from OLT ping sensor"
            },
            delivery="diagnostic",
        )
        db.add(event)
        ont.last_seen_at = datetime.now(timezone.utc)
        db.add(ont)
    db.commit()
    logger.info(f"Propagated CRITICAL to {len(linked_onts)} ONTs under down OLT {olt.name}")


def run_olt_ping_job():
    """Main job executed every minute."""
    db = _get_db()
    try:
        olts = db.query(OLT).filter(OLT.is_active == True).all()
        for olt in olts:
            rtt = ping_olt(olt, db)
            if olt.status == "DOWN":
                propagate_olt_outage(olt, db)
            else:
                # Clear previous synthetic if any? (optional, we keep history)
                pass
        db.commit()
    except Exception as exc:
        logger.exception("Error in OLT ping sensor job")
    finally:
        db.close()


def start_monitor():
    """Start the 1-minute ping sensor scheduler."""
    if not scheduler.running:
        scheduler.add_job(
            run_olt_ping_job,
            "interval",
            minutes=1,
            id="olt_ping_sensor",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.start()
        logger.info("Hyperion-ONMS ping sensor started (every 1 minute)")
        # Run once immediately for demo
        scheduler.add_job(run_olt_ping_job, id="initial_ping", replace_existing=True)


def shutdown_monitor():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Ping sensor stopped")
