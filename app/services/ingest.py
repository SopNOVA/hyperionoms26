"""
Telemetry ingestion service.

Central place for:
- Tolerant parsing of data coming from real ontprobe agents (many key name variants).
- Auto-provisioning of ONT records.
- Smart linking between pre-created Customers and ONTs (by gpon_sn or mac).
- Heuristics: config drift detection, low-uptime downgrade.
- Creation of TelemetryEvent + last_seen updates.
- OLT last_seen touch when the ONT belongs to an OLT.

This was extracted from the giant 270-line handler that lived in app/main.py
(the /ont-monitor legacy endpoint) during the June 2026 maintainability refactor.

Goal: make the complex "field agent" path testable and keep the main.py thin.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.ont import Ont
from app.models.customer import Customer
from app.models.olt import OLT
from app.models.telemetry import TelemetryEvent
from app.services.classifier import classify_telemetry, classify_optical_rx
from app.core.database import Base, SessionLocal  # for defensive table creation in early hits

logger = logging.getLogger("hyperion.ingest")


def _extract_gpon(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("gpon_sn", "gpon", "serial", "sn", "ont_sn", "gpon_serial"):
        val = payload.get(key)
        if val:
            return str(val)
    return None


def _extract_mac(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("mac_address", "mac", "macaddr", "mac_addr", "hwaddr"):
        val = payload.get(key)
        if val:
            return str(val)
    return None


def _extract_wan_ip(payload: Dict[str, Any]) -> Optional[str]:
    # Common locations in probe payloads
    wan = payload.get("wan") or payload.get("config_snapshot") or {}
    if isinstance(wan, dict):
        ip = wan.get("ip") or wan.get("wan_ip")
        if ip:
            return str(ip) if not isinstance(ip, dict) else str(ip.get("ip", ""))
    for k in ("wan_ip", "ip", "public_ip", "ip_address"):
        val = payload.get(k)
        if val:
            return str(val) if not isinstance(val, dict) else str(val.get("ip", ""))
    return None


def _extract_current_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = payload.get("config_snapshot") or payload.get("wan") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "ip": cfg.get("ip") or cfg.get("wan_ip"),
        "gateway": cfg.get("gateway"),
        "dns": cfg.get("active_wan_dns") or cfg.get("system_dns"),
        "subnet": cfg.get("subnet") or cfg.get("netmask"),
    }


def _extract_ping_averages(payload: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    ping_section = payload.get("ping") or payload.get("pings") or {}
    if not isinstance(ping_section, dict):
        # flat keys sometimes used
        p8 = payload.get("ping_8_avg") or payload.get("ping8")
        p1 = payload.get("ping_1_avg") or payload.get("ping1")
        return (float(p8) if p8 is not None else None,
                float(p1) if p1 is not None else None)

    p8 = (
        ping_section.get("google_8_8_8_8")
        or ping_section.get("8.8.8.8")
        or ping_section.get("dns_8.8.8.8")
        or {}
    )
    p1 = (
        ping_section.get("cloudflare_1_1_1_1")
        or ping_section.get("1.1.1.1")
        or {}
    )
    if not isinstance(p8, dict):
        p8 = {"avg_ms": p8}
    if not isinstance(p1, dict):
        p1 = {"avg_ms": p1}

    def _avg(d: Dict[str, Any]) -> Optional[float]:
        v = d.get("avg_ms") or d.get("avg")
        try:
            return float(v) if v is not None else None
        except Exception:
            return None

    return _avg(p8), _avg(p1)


def _extract_optical(payload: Dict[str, Any]) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Extrae rx_power_dbm, tx_power_dbm y optical_status del payload del probe.

    El probe envía:
      "optical": {"rx_power_dbm": -23.09, "tx_power_dbm": 3.02, "status": "GOOD", ...}
    También acepta claves directas en el root para compatibilidad futura.
    """
    opt = payload.get("optical")
    if not isinstance(opt, dict):
        opt = {}

    rx = opt.get("rx_power_dbm")
    tx = opt.get("tx_power_dbm")
    status = opt.get("status") or None

    # Fallback a claves de nivel raíz
    if rx is None:
        rx = payload.get("rx_power_dbm")
    if tx is None:
        tx = payload.get("tx_power_dbm")

    try:
        rx = float(rx) if rx is not None else None
    except Exception:
        rx = None
    try:
        tx = float(tx) if tx is not None else None
    except Exception:
        tx = None

    if status not in ("GOOD", "WARNING", "CRITICAL", "UNKNOWN"):
        status = None

    return rx, tx, status


def _extract_tcp_retrans(payload: Dict[str, Any]) -> Optional[int]:
    local = payload.get("local_net_diag") or {}
    if isinstance(local, dict):
        val = local.get("tcp_retrans_segs")
        if val is not None:
            try:
                return int(val)
            except Exception:
                pass
    for k in ("tcp_retrans", "tcp_retrans_segs", "retrans", "tcp_retransmissions"):
        val = payload.get(k)
        if val is not None:
            try:
                return int(val)
            except Exception:
                pass
    return None


def parse_probe_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize the extremely variable shapes that real ontprobe binaries send.
    Returns a dict with canonical keys that the rest of the system can trust.
    """
    gpon = _extract_gpon(payload)
    mac = _extract_mac(payload)
    wan_ip = _extract_wan_ip(payload)
    curr_cfg = _extract_current_config(payload)
    ping8, ping1 = _extract_ping_averages(payload)
    tcp_retrans = _extract_tcp_retrans(payload)
    rx_dbm, tx_dbm, optical_status_probe = _extract_optical(payload)

    uptime = 0.0
    try:
        uptime = float(payload.get("uptime_seconds") or 0)
    except Exception:
        pass

    classification = payload.get("classification") or "UNKNOWN"
    reason = payload.get("reason") or "Data received from ontprobe"

    return {
        "gpon_sn": gpon,
        "mac_address": mac,
        "wan_ip": wan_ip,
        "curr_cfg": curr_cfg,
        "ping_8_avg": ping8,
        "ping_1_avg": ping1,
        "tcp_retrans_segs": tcp_retrans,
        "rx_power_dbm": rx_dbm,
        "tx_power_dbm": tx_dbm,
        "optical_status_probe": optical_status_probe,
        "uptime_seconds": uptime,
        "classification": classification,
        "reason": reason,
        "raw": payload,  # always keep original for the JSON column
    }


def _maybe_link_customer(db: Session, ont: Ont, gpon: Optional[str], mac: Optional[str]) -> None:
    """Auto-link Ont to a pre-created Customer if one matches by gpon or mac."""
    if not (gpon or mac) or ont.customer_id:
        return
    try:
        cust = None
        if gpon:
            cust = db.query(Customer).filter(Customer.gpon_sn == str(gpon)).first()
        if not cust and mac:
            cust = db.query(Customer).filter(Customer.mac_address == str(mac)).first()
        if cust and ont.customer_id != cust.id:
            ont.customer_id = cust.id
            db.add(ont)
            logger.info(f"Linked Ont {ont.gpon_sn} to customer {cust.name}")
    except Exception as e:
        logger.warning(f"Customer linking skipped (non-fatal): {e}")


def _detect_config_drift(db: Session, ont: Ont, curr_cfg: Dict[str, Any], prev_classification: str, prev_reason: str) -> tuple[str, str]:
    """Return possibly upgraded classification + augmented reason if IP/GW/DNS/subnet changed."""
    if not curr_cfg:
        return prev_classification, prev_reason

    try:
        prev_ev = (
            db.query(TelemetryEvent)
            .filter(TelemetryEvent.ont_id == ont.id)
            .order_by(TelemetryEvent.received_at.desc())
            .first()
        )
        if not prev_ev or not prev_ev.data:
            return prev_classification, prev_reason

        prev_cfg = prev_ev.data.get("config_snapshot") or prev_ev.data.get("wan") or {}
        if not isinstance(prev_cfg, dict):
            prev_cfg = {}

        changed = []
        for field, curr_val, prev_key in [
            ("ip", curr_cfg.get("ip"), "ip"),
            ("gateway", curr_cfg.get("gateway"), "gateway"),
            ("dns", curr_cfg.get("dns"), "active_wan_dns"),
            ("subnetmask", curr_cfg.get("subnet"), "subnet"),
        ]:
            prev_val = prev_cfg.get(prev_key) or prev_cfg.get(field)
            if curr_val and prev_val and str(curr_val) != str(prev_val):
                changed.append(field)

        if changed:
            cls = prev_classification
            if cls in (None, "UNKNOWN", "GOOD"):
                cls = "REGULAR"
            new_reason = (prev_reason or "") + f" | CONFIG_CHANGE: {','.join(changed)} (medium severity)"
            logger.info(f"Config change detected for {ont.gpon_sn}: {changed}")
            return cls, new_reason
    except Exception as e:
        logger.warning(f"Config drift detection skipped: {e}")
    return prev_classification, prev_reason


def _maybe_downgrade_for_low_uptime(classification: str, reason: str, uptime: float) -> tuple[str, str]:
    """Recent boot (low uptime) often has transient failures — downgrade CRITICAL/BAD to REGULAR."""
    if uptime > 0 and uptime < 300:  # 5 minutes
        if classification in ("CRITICAL", "BAD"):
            orig = classification
            classification = "REGULAR"
            reason = (reason or "") + f" | LOW_UPTIME_{int(uptime)}s (recent boot, expected transient; downgraded from {orig})"
            logger.info(f"Downgraded classification due to low uptime {uptime}s")
    return classification, reason


def process_telemetry_event(
    db: Session,
    payload: Dict[str, Any],
    delivery: str = "ontprobe",
) -> Dict[str, Any]:
    """
    Main ingestion pipeline. Idempotent-friendly and tolerant.

    Steps:
      1. Parse/normalize the wild probe payload.
      2. Find or create Ont (by gpon_sn then mac).
      3. Update Ont metadata (mac/ip) from probe.
      4. Auto-link to Customer if possible.
      5. Apply classification (prefer probe's own if present, else run classifier).
      6. Apply config-drift and low-uptime heuristics.
      7. Create TelemetryEvent (raw data always stored in .data).
      8. Touch last_seen on Ont (+ OLT if linked).

    Returns a small dict suitable for API responses.
    """
    parsed = parse_probe_payload(payload)
    gpon = parsed["gpon_sn"]
    mac = parsed["mac_address"]
    wan_ip = parsed["wan_ip"]
    curr_cfg = parsed["curr_cfg"]
    ping8 = parsed["ping_8_avg"]
    ping1 = parsed["ping_1_avg"]
    tcp_retrans = parsed["tcp_retrans_segs"]
    rx_dbm = parsed["rx_power_dbm"]
    tx_dbm = parsed["tx_power_dbm"]
    optical_status_probe = parsed["optical_status_probe"]
    uptime = parsed["uptime_seconds"]
    probe_cls = parsed["classification"]
    probe_reason = parsed["reason"]
    raw = parsed["raw"]

    if not gpon and not mac:
        # Still accept garbage — give it a synthetic id so we don't lose the report
        gpon = "PROBE-" + str(int(datetime.now().timestamp()))

    # Defensive: some test runs or early requests can hit ingest before the
    # lifespan or fixture has created tables (especially with SQLite :memory:).
    try:
        Base.metadata.create_all(bind=db.bind)
    except Exception:
        pass

    # 1. Locate or create Ont
    ont = None
    if gpon:
        ont = db.query(Ont).filter(Ont.gpon_sn == str(gpon)).first()
    if not ont and mac:
        ont = db.query(Ont).filter(Ont.mac_address == str(mac)).first()

    if ont:
        # Refresh metadata from live probe
        if mac and ont.mac_address != str(mac):
            ont.mac_address = str(mac)
            db.add(ont)
        if wan_ip and ont.ip_address != wan_ip:
            ont.ip_address = wan_ip
            db.add(ont)
        if mac or wan_ip:
            db.commit()
            db.refresh(ont)
    else:
        ont = Ont(
            gpon_sn=str(gpon) if gpon else "UNKNOWN-PROBE",
            mac_address=str(mac) if mac else None,
            ip_address=wan_ip,
            is_active=True,
        )
        db.add(ont)
        db.commit()
        db.refresh(ont)
        logger.info(f"Auto-created Ont from probe: {ont.gpon_sn}")

    # 2. Customer linking (best effort)
    _maybe_link_customer(db, ont, gpon, mac)

    # 3. Classification
    classification = probe_cls or "UNKNOWN"
    reason = probe_reason or "Data received directly from ontprobe"
    if not probe_cls or classification == "UNKNOWN":
        try:
            c, r = classify_telemetry(raw)
            classification, reason = c, r
        except Exception as e:
            logger.warning(f"Classifier failed, using raw classification: {e}")

    # 4. Heuristics
    classification, reason = _detect_config_drift(db, ont, curr_cfg, classification, reason)
    classification, reason = _maybe_downgrade_for_low_uptime(classification, reason, uptime)

    # 5. Clasificación óptica (siempre calculada en servidor; se prefiere la del probe si es válida)
    optical_cls, optical_reason_str = classify_optical_rx(rx_dbm)
    optical_status = optical_status_probe if optical_status_probe else optical_cls

    # Integración óptica → impacto sobre clasificación principal
    if optical_status == "CRITICAL" and rx_dbm is not None:
        if classification in ("GOOD", "REGULAR"):
            classification = "BAD"
        reason = (reason or "") + f" | OPTICAL_CRITICAL: RX={rx_dbm:.2f} dBm"
    elif optical_status == "WARNING" and rx_dbm is not None:
        if classification == "GOOD":
            classification = "REGULAR"
        reason = (reason or "") + f" | OPTICAL_WARNING: RX={rx_dbm:.2f} dBm"

    # 6. Persist event
    event = TelemetryEvent(
        ont_id=ont.id,
        classification=classification,
        reason=reason,
        wan_ip=wan_ip,
        ping_8_avg=ping8,
        ping_1_avg=ping1,
        tcp_retrans_segs=tcp_retrans,
        rx_power_dbm=rx_dbm,
        tx_power_dbm=tx_dbm,
        optical_status=optical_status,
        data=raw,
        delivery=delivery,
    )
    db.add(event)

    # 6. Touch last_seen
    now = datetime.now(timezone.utc)
    ont.last_seen_at = now
    db.add(ont)

    olt_status = None
    if ont.olt_id:
        olt = db.query(OLT).filter(OLT.id == ont.olt_id).first()
        if olt:
            olt.last_seen_at = now
            db.add(olt)
            olt_status = olt.status

    db.commit()
    db.refresh(event)

    logger.info(f"Telemetry stored for {ont.gpon_sn} classification={classification}")

    return {
        "status": "accepted",
        "ont_id": ont.id,
        "gpon_sn": ont.gpon_sn,
        "classification": classification,
        "reason": reason,
        "event_id": event.id,
        "olt_status": olt_status,
    }
