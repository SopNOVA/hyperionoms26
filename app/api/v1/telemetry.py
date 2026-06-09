from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.database import get_db
from app.models.ont import Ont
from app.models.telemetry import TelemetryEvent
from app.models.olt import OLT
from app.models.customer import Customer
from app.models.ping_log import PingLog
from app.core.security import get_current_active_technician
# SINGLE SOURCE OF TRUTH for classification (extracted for long-term maintainability)
from app.services.classifier import classify_telemetry
from app.services.ingest import process_telemetry_event

router = APIRouter()

# Re-export for any code that was importing it from here (back-compat)
__all__ = ["classify_telemetry", "router"]


@router.post("/ingest")
def ingest_telemetry(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Structured ingest endpoint (preferred for new agents or simulators).

    Delegates to the central process_telemetry_event service so that
    tolerant parsing, customer matching, heuristics and classification
    stay in one place (app/services/ingest.py + classifier.py).
    """
    if not (payload.get("gpon_sn") or payload.get("gpon") or payload.get("mac_address") or payload.get("mac")):
        raise HTTPException(422, "gpon_sn or mac_address required in telemetry")

    result = process_telemetry_event(db, payload, delivery=payload.get("delivery", "live"))

    return {
        "status": "accepted",
        "ont_id": result["ont_id"],
        "gpon_sn": result["gpon_sn"],
        "classification": result["classification"],
        "reason": result["reason"],
        "olt_status": result.get("olt_status"),
        "event_id": result["event_id"],
    }


@router.get("/stats/range")
def get_stats_for_range(
    from_ts: str = Query(..., description="ISO from e.g. 2026-06-01T00:00"),
    to_ts: str = Query(..., description="ISO to"),
    gpon_sn: Optional[str] = Query(None),
    olt_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    """
    Optimized stats for modern dashboard date-range.
    Returns time series for ping (8.8/1.1), jitter (synthetic if absent), service_total_time.
    NO tcp_retrans in the graphs as per spec.
    """
    from datetime import datetime as dt
    try:
        fs = from_ts
        if len(fs) == 16: fs += ":00"  # datetime-local gives YYYY-MM-DDTHH:MM
        if len(fs) == 19: fs += "+00:00"  # make explicit UTC if no tz (treat picker times as UTC per server hora)
        start = dt.fromisoformat(fs.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        te = to_ts
        if len(te) == 16: te += ":00"
        if len(te) == 19: te += "+00:00"
        end = dt.fromisoformat(te.replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(422, "Invalid ISO timestamps")

    q = db.query(TelemetryEvent).filter(
        TelemetryEvent.received_at >= start,
        TelemetryEvent.received_at <= end
    )
    if gpon_sn:
        ont = db.query(Ont).filter(Ont.gpon_sn == gpon_sn).first()
        if ont:
            q = q.filter(TelemetryEvent.ont_id == ont.id)
    if olt_id:
        ont_ids = [o.id for o in db.query(Ont).filter(Ont.olt_id == olt_id).all()]
        if ont_ids:
            q = q.filter(TelemetryEvent.ont_id.in_(ont_ids))

    if gpon_sn:
        events = q.order_by(TelemetryEvent.received_at.asc()).all()
    elif olt_id:
        events = []  # for pure OLT ping graph, no need full telemetry events
    else:
        events = q.order_by(TelemetryEvent.received_at.asc()).limit(1000).all()  # cap for perf in global

    series = []
    for ev in events:
        d = ev.data or {}
        # Support both old "pings" and new probe "ping" structure (google_8_8_8_8 with avg_ms)
        p8 = None
        p1 = None
        p = d.get("pings") or d.get("ping") or {}
        if isinstance(p, dict):
            for k, v in p.items():
                if "8.8.8.8" in k or "google" in str(k).lower():
                    if isinstance(v, dict):
                        p8 = v.get("avg") or v.get("avg_ms")
                    else:
                        p8 = v
                if "1.1.1.1" in k or "cloudflare" in str(k).lower():
                    if isinstance(v, dict):
                        p1 = v.get("avg") or v.get("avg_ms")
                    else:
                        p1 = v
        ping_8 = ev.ping_8_avg or p8 or (p.get("8.8.8.8", {}) if isinstance(p.get("8.8.8.8"), dict) else p.get("8.8.8.8"))
        ping_1 = ev.ping_1_avg or p1 or (p.get("1.1.1.1", {}) if isinstance(p.get("1.1.1.1"), dict) else p.get("1.1.1.1"))

        # Extract loss for quality chart if present in raw ping data
        loss_8 = None
        loss_1 = None
        if isinstance(p, dict):
            for k, v in p.items():
                if "8.8.8.8" in k or "google" in str(k).lower():
                    if isinstance(v, dict):
                        loss_8 = v.get("packet_loss")
                if "1.1.1.1" in k or "cloudflare" in str(k).lower():
                    if isinstance(v, dict):
                        loss_1 = v.get("packet_loss")

        # Service total connection time: prefer probe http_tests total_ms avg, or old total_connection_time_ms
        # Also expose per-service for colored graphs
        http_tests = d.get("http_tests") or []
        svc_time = None
        services = {}
        if isinstance(http_tests, list) and http_tests:
            totals = []
            for h in http_tests:
                if isinstance(h, dict):
                    name = h.get("name") or h.get("url") or "service"
                    t = h.get("total_ms") or h.get("total")
                    if t is not None:
                        tval = float(t)
                        totals.append(tval)
                        services[name] = tval
            if totals:
                svc_time = sum(totals) / len(totals)
        if svc_time is None:
            svc_time = d.get("total_connection_time_ms") or d.get("avg_service_total_ms") or (ev.ping_8_avg or 20) * 3 + 50

        # No jitter in graphs per requirements
        series.append({
            "ts": ev.received_at.isoformat(),
            "ping_8": ping_8,
            "ping_1": ping_1,
            "loss_8": loss_8,
            "loss_1": loss_1,
            "service_time_ms": svc_time,
            "services": services,  # per-service for multi-color graph: {"Google": 417.43, "Cloudflare": 123.4, ...}
            "classification": ev.classification,
            "reason": ev.reason,
            "gpon": ev.ont.gpon_sn if ev.ont else None,
            "raw": d,  # for future
        })

    # Ping history to ONU (client WAN) and OLT for graphing (only when gpon_sn filtered, for optimization)
    ping_ont_series = []
    ping_olt_series = []
    if gpon_sn:
        ont = db.query(Ont).filter(Ont.gpon_sn == gpon_sn).first()
        if ont:
            ping_ont_series = [
                {
                    "ts": log.ts.isoformat(),
                    "ping_ms": log.ping_ms,
                    "status": log.status,
                    "ip": log.ip_address,
                }
                for log in db.query(PingLog)
                .filter(
                    PingLog.target_type == "ont",
                    PingLog.target_id == ont.id,
                    PingLog.ts >= start,
                    PingLog.ts <= end,
                )
                .order_by(PingLog.ts.asc())
                .all()
            ]
            if ont.olt_id:
                ping_olt_series = [
                    {
                        "ts": log.ts.isoformat(),
                        "ping_ms": log.ping_ms,
                        "status": log.status,
                        "ip": log.ip_address,
                    }
                    for log in db.query(PingLog)
                    .filter(
                        PingLog.target_type == "olt",
                        PingLog.target_id == ont.olt_id,
                        PingLog.ts >= start,
                        PingLog.ts <= end,
                    )
                    .order_by(PingLog.ts.asc())
                    .all()
                ]
    elif olt_id:
        ping_olt_series = [
            {
                "ts": log.ts.isoformat(),
                "ping_ms": log.ping_ms,
                "status": log.status,
                "ip": log.ip_address,
            }
            for log in db.query(PingLog)
            .filter(
                PingLog.target_type == "olt",
                PingLog.target_id == olt_id,
                PingLog.ts >= start,
                PingLog.ts <= end,
            )
            .order_by(PingLog.ts.asc())
            .all()
        ]

    # Simple aggregates
    pings = [s["ping_8"] for s in series if s["ping_8"]]
    avg_ping = sum(pings) / len(pings) if pings else 0

    return {
        "range": {"from": from_ts, "to": to_ts},
        "count": len(series),
        "avg_ping_8": round(avg_ping, 1),
        "series": series,
        "ping_ont": ping_ont_series,
        "ping_olt": ping_olt_series,
    }


@router.get("/alerts/summary")
def alerts_summary(
    limit: int = Query(10, ge=1, le=100, description="Max items per alert category"),
    db: Session = Depends(get_db), 
    current_user=Depends(get_current_active_technician)
):
    """Sectioned alerts for main dashboard: OLT downs, mass client impact, critical ONUs, plus new conntrack/NAT analytics (high usage, unreplied, syn_sent, top talker anomalies from local_net_diag). Use limit param for more."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    recent = now - timedelta(minutes=30)

    # OLT downs
    down_olts = db.query(OLT).filter(OLT.status == "DOWN", OLT.is_active == True).all()

    # Recent critical events
    critical_events = db.query(TelemetryEvent).filter(
        TelemetryEvent.classification == "CRITICAL",
        TelemetryEvent.received_at >= recent
    ).all()

    # Group by OLT impact (if from propagation)
    mass_impacted = []
    for ev in critical_events:
        if ev.ont and ev.ont.olt_id:
            olt = db.query(OLT).get(ev.ont.olt_id)
            if olt and olt.status == "DOWN":
                mass_impacted.append({
                    "olt_name": olt.name,
                    "gpon": ev.ont.gpon_sn,
                    "mac": ev.ont.mac_address,
                    "ip": ev.ont.ip_address or ev.wan_ip,
                    "uptime_seconds": (ev.data or {}).get("uptime_seconds") if ev.data else None,
                })
                if ev.ont.customer_id:
                    try:
                        cust = db.query(Customer).get(ev.ont.customer_id)
                        if cust:
                            mass_impacted[-1]["customer"] = cust.name
                    except Exception:
                        pass

    # Critical ONUs (distinct) - minimal for summary cards + uptime + client info
    critical_onts = {}
    for ev in critical_events:
        if ev.ont:
            uptime = None
            if ev.data and isinstance(ev.data, dict):
                try:
                    uptime = ev.data.get("uptime_seconds")
                except Exception:
                    pass
            item = {
                "gpon": ev.ont.gpon_sn,
                "reason": ev.reason,
                "ts": ev.received_at.isoformat(),
                "classification": ev.classification,
                "mac": ev.ont.mac_address,
                "ip": ev.ont.ip_address or ev.wan_ip,
                "uptime_seconds": uptime,
            }
            if ev.ont.customer_id:
                try:
                    cust = db.query(Customer).get(ev.ont.customer_id)
                    if cust:
                        item["customer"] = cust.name
                except Exception:
                    pass
            critical_onts[ev.ont.gpon_sn] = item

    # Config changes (medium severity) - ip/gw/dns/subnetmask drift from previous probe report
    # Avoid duplicating ONUs that are already in critical list
    config_change_events = db.query(TelemetryEvent).filter(
        TelemetryEvent.received_at >= recent,
        TelemetryEvent.reason.ilike("%CONFIG_CHANGE%")
    ).all()
    config_changes = []
    seen = set()
    for ev in config_change_events:
        if ev.ont and ev.ont.gpon_sn not in seen and ev.ont.gpon_sn not in critical_onts:
            seen.add(ev.ont.gpon_sn)
            uptime = None
            if ev.data and isinstance(ev.data, dict):
                try:
                    uptime = ev.data.get("uptime_seconds")
                except Exception:
                    pass
            item = {
                "gpon": ev.ont.gpon_sn,
                "reason": ev.reason,
                "ts": ev.received_at.isoformat(),
                "classification": ev.classification,
                "mac": ev.ont.mac_address,
                "ip": ev.ont.ip_address or ev.wan_ip,
                "uptime_seconds": uptime,
            }
            if ev.ont.customer_id:
                try:
                    cust = db.query(Customer).get(ev.ont.customer_id)
                    if cust:
                        item["customer"] = cust.name
                except Exception:
                    pass
            config_changes.append(item)

    # New: Conntrack / NAT analytics based alerts from recent probe local_net_diag
    conntrack_high = []
    unreplied_high = []
    syn_high = []
    top_talker = []
    seen = set()
    for ev in db.query(TelemetryEvent).filter(
        TelemetryEvent.received_at >= recent
    ).all():
        if not ev.ont or ev.ont.gpon_sn in seen:
            continue
        d = ev.data or {}
        if not isinstance(d, dict):
            continue
        local = d.get("local_net_diag") or {}
        if not isinstance(local, dict):
            continue
        count = local.get("nf_conntrack_count") or 0
        maxc = local.get("nf_conntrack_max") or 1
        unrepl = local.get("nf_unreplied") or 0
        syns = local.get("nf_syn_sent") or 0
        topip = local.get("nf_top_lan_ip") or ""
        tops = local.get("nf_top_lan_sessions") or 0
        topt = local.get("nf_top_lan_tcp_sessions") or 0
        topu = local.get("nf_top_lan_udp_sessions") or 0
        topun = local.get("nf_top_lan_unreplied") or 0
        topsy = local.get("nf_top_lan_syn_sent") or 0
        pct = (count / maxc * 100.0) if maxc > 0 else 0.0
        if pct >= 70 or unrepl >= 500 or syns >= 500 or (topip and topip != "unknown" and (tops >= 5000 or topun >= 300 or topsy >= 300)):
            if pct >= 70:
                conntrack_high.append({
                    "gpon": ev.ont.gpon_sn,
                    "reason": f"Alta utilización conntrack: {pct:.1f}% ({count}/{maxc})",
                    "ts": ev.received_at.isoformat(),
                    "mac": ev.ont.mac_address,
                    "ip": ev.ont.ip_address or ev.wan_ip,
                    "uptime_seconds": (ev.data or {}).get("uptime_seconds") if ev.data else None,
                    "customer": None,
                })
            if unrepl >= 500:
                unreplied_high.append({
                    "gpon": ev.ont.gpon_sn,
                    "reason": f"Alto UNREPLIED: {unrepl} sesiones sin respuesta",
                    "ts": ev.received_at.isoformat(),
                    "mac": ev.ont.mac_address,
                    "ip": ev.ont.ip_address or ev.wan_ip,
                    "uptime_seconds": (ev.data or {}).get("uptime_seconds") if ev.data else None,
                    "customer": None,
                })
            if syns >= 500:
                syn_high.append({
                    "gpon": ev.ont.gpon_sn,
                    "reason": f"Alto SYN_SENT: {syns} handshakes TCP incompletos",
                    "ts": ev.received_at.isoformat(),
                    "mac": ev.ont.mac_address,
                    "ip": ev.ont.ip_address or ev.wan_ip,
                    "uptime_seconds": (ev.data or {}).get("uptime_seconds") if ev.data else None,
                    "customer": None,
                })
            ctype = "RESIDENCIAL"
            if ev.ont.customer_id:
                try:
                    cust = db.query(Customer).get(ev.ont.customer_id)
                    if cust:
                        doc = (cust.document or "").upper()
                        nameu = (cust.name or "").upper()
                        if len(doc) > 11 or "-" in doc or "NIT" in doc or any(k in nameu for k in ["CORP", "S.A", "LTDA", "EMP", "SOCIEDAD"]):
                            ctype = "CORPORATIVO"
                except:
                    pass
            top_thresh = 1000 if ctype == "RESIDENCIAL" else 10000
            if topip and topip != "unknown" and (tops >= top_thresh or topun >= 300 or topsy >= 300):
                alert = {
                    "gpon": ev.ont.gpon_sn,
                    "top_ip": topip,
                    "sessions": tops,
                    "reason": f"Top talker LAN {topip}: {tops} sess (TCP {topt}, UDP {topu}, UNR {topun}, SYN {topsy})",
                    "ts": ev.received_at.isoformat(),
                    "mac": ev.ont.mac_address,
                    "ip": ev.ont.ip_address or ev.wan_ip,
                    "uptime_seconds": (ev.data or {}).get("uptime_seconds") if ev.data else None,
                }
                if ev.ont.customer_id:
                    try:
                        cust = db.query(Customer).get(ev.ont.customer_id)
                        if cust:
                            alert["customer"] = cust.name
                            alert["customer_type"] = ctype
                            alert["reason"] += f" | {cust.name} ({ctype})"
                    except:
                        pass
                top_talker.append(alert)
            seen.add(ev.ont.gpon_sn)

    # === Alertas ópticas (RX/TX power de última lectura por ONT en las últimas 30 min) ===
    optical_critical = []
    optical_warning = []
    seen_optical = set()
    for ev in db.query(TelemetryEvent).filter(
        TelemetryEvent.received_at >= recent,
        TelemetryEvent.optical_status.in_(["WARNING", "CRITICAL"])
    ).order_by(TelemetryEvent.received_at.desc()).all():
        if not ev.ont or ev.ont.gpon_sn in seen_optical:
            continue
        seen_optical.add(ev.ont.gpon_sn)
        item = {
            "gpon": ev.ont.gpon_sn,
            "rx_power_dbm": ev.rx_power_dbm,
            "tx_power_dbm": ev.tx_power_dbm,
            "optical_status": ev.optical_status,
            "reason": f"RX={ev.rx_power_dbm:.2f} dBm" if ev.rx_power_dbm is not None else "sin lectura",
            "ts": ev.received_at.isoformat(),
            "mac": ev.ont.mac_address,
            "ip": ev.ont.ip_address or ev.wan_ip,
            "uptime_seconds": (ev.data or {}).get("uptime_seconds") if ev.data else None,
            "customer": None,
        }
        try:
            if ev.ont.customer_id:
                cust = db.get(Customer, ev.ont.customer_id)
                if cust:
                    item["customer"] = cust.name
        except Exception:
            pass
        if ev.optical_status == "CRITICAL":
            optical_critical.append(item)
        else:
            optical_warning.append(item)

    return {
        "olt_downs": [{"id": o.id, "name": o.name, "ip": o.ip_address, "last_ping": o.last_ping_ms} for o in down_olts],
        "mass_client_outages": mass_impacted[:limit],
        "critical_onus": list(critical_onts.values())[:limit],
        "config_changes": config_changes[:limit],
        "high_conntrack": conntrack_high[:limit],
        "high_unreplied": unreplied_high[:limit],
        "high_syn_sent": syn_high[:limit],
        "top_talker_issues": top_talker[:limit],
        "optical_critical": optical_critical[:limit],
        "optical_warning": optical_warning[:limit],
        "generated_at": now.isoformat(),
    }


@router.get("/recent")
def get_recent_telemetry(
    gpon_sn: Optional[str] = Query(None, description="Filtrar por GPON SN del ONT"),
    limit: int = Query(5, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_technician),
):
    """Return recent telemetry events (latest first). Use with gpon_sn + limit=1 for 'mas detalle' modal stats."""
    q = db.query(TelemetryEvent)
    if gpon_sn:
        ont = db.query(Ont).filter(Ont.gpon_sn == gpon_sn).first()
        if not ont:
            return []
        q = q.filter(TelemetryEvent.ont_id == ont.id)
    events = q.order_by(TelemetryEvent.received_at.desc()).limit(limit).all()
    out = []
    for e in events:
        uptime = None
        if e.data and isinstance(e.data, dict):
            try:
                uptime = e.data.get("uptime_seconds")
            except Exception:
                pass

        out.append({
            "id": e.id,
            "ont_id": e.ont_id,
            "gpon_sn": e.ont.gpon_sn if e.ont else None,
            "received_at": e.received_at.isoformat() if e.received_at else None,
            "classification": e.classification,
            "reason": e.reason,
            "wan_ip": e.wan_ip,
            "ping_8_avg": e.ping_8_avg,
            "ping_1_avg": e.ping_1_avg,
            "tcp_retrans_segs": e.tcp_retrans_segs,
            "rx_power_dbm": e.rx_power_dbm,
            "tx_power_dbm": e.tx_power_dbm,
            "optical_status": e.optical_status,
            "uptime_seconds": uptime,
            "data": e.data,
        })
    return out

