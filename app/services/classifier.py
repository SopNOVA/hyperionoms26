"""
Centralized classification logic for telemetry/probe data.

This module is the SINGLE SOURCE OF TRUTH for deciding GOOD / REGULAR / BAD / CRITICAL.

Extracted during 2026-06 maintainability pass to remove duplication between
the legacy /ont-monitor path (main.py) and the structured /ingest path (telemetry.py).

Rules (kept faithful to original intent):
- If services (http_tests) look healthy → prefer GOOD even when TCP retransmissions are high.
- Conntrack / NAT anomalies can downgrade GOOD → REGULAR.
- Packet loss and high latency on primary DNS have highest severity.
"""

from typing import Any, Dict, Tuple


def classify_telemetry(data: Dict[str, Any]) -> Tuple[str, str | None]:
    """
    Classify a probe payload.

    Returns:
        (classification, reason)
    """
    # Support both legacy "pings" structure and newer "ping" structure from ontprobe
    pings = data.get("pings") or data.get("ping") or {}
    if not isinstance(pings, dict):
        pings = {}

    # Extract 8.8.8.8 and 1.1.1.1 averages (multiple key name variants supported)
    def _get_ping_avg(section: Any) -> float:
        if isinstance(section, dict):
            return section.get("avg", section.get("avg_ms", 999)) or 999
        if isinstance(section, (int, float)):
            return float(section)
        return 999.0

    def _get_ping_loss(section: Any) -> float:
        if isinstance(section, dict):
            val = section.get("packet_loss", section.get("loss", 0))
            try:
                return float(val)
            except Exception:
                return 0.0
        return 0.0

    p8 = (
        pings.get("google_8_8_8_8")
        or pings.get("8.8.8.8")
        or pings.get("dns_8.8.8.8")
        or {}
    )
    p1 = (
        pings.get("cloudflare_1_1_1_1")
        or pings.get("1.1.1.1")
        or {}
    )

    avg8 = _get_ping_avg(p8)
    avg1 = _get_ping_avg(p1)
    loss8 = _get_ping_loss(p8)
    loss1 = _get_ping_loss(p1)

    tcp_retrans = (
        data.get("tcp_retrans")
        or data.get("tcp_retrans_segs")
        or data.get("retrans")
        or 0
    )
    try:
        tcp_retrans = int(tcp_retrans or 0)
    except Exception:
        tcp_retrans = 0

    services = data.get("services") or []
    if not isinstance(services, list):
        services = []

    jitter = data.get("jitter", 0)
    try:
        jitter = float(jitter or 0)
    except Exception:
        jitter = 0.0

    total_conn = data.get("total_connection_time_ms", 0)
    try:
        total_conn = float(total_conn or 0)
    except Exception:
        total_conn = 0.0

    # Are the explicit service tests (Google, Cloudflare, Netflix...) succeeding?
    services_good = True
    for s in services:
        if not isinstance(s, dict):
            continue
        status = str(s.get("status", "ok")).lower()
        latency = s.get("latency_ms", 0)
        try:
            latency = float(latency or 0)
        except Exception:
            latency = 0
        if status not in ("ok", "good") or latency > 150:
            services_good = False
            break

    # === Core classification ===
    reason = None
    if loss8 > 5 or avg8 > 150 or avg1 > 150:
        classification = "CRITICAL"
        reason = "High latency or packet loss on primary DNS"
    elif avg8 > 80 or jitter > 15 or tcp_retrans > 100:
        if services_good:
            classification = "GOOD"
            reason = f"Servicios OK (total_conn={int(total_conn)}ms). Observación: alto TCP retrans ({tcp_retrans}) pero pruebas de servicio exitosas."
        else:
            classification = "BAD"
            reason = f"Latencia elevada o retransmisiones altas ({tcp_retrans}) + servicios degradados"
    elif avg8 > 40 or jitter > 8:
        classification = "REGULAR"
        reason = "Degradación leve"
    else:
        classification = "GOOD"
        if tcp_retrans > 20:
            reason = f"Observación: TCP retransmisiones moderadas ({tcp_retrans}) pero todo estable."

    # === Conntrack / NAT / top-talker signals (can downgrade GOOD) ===
    local = data.get("local_net_diag") or {}
    if not isinstance(local, dict):
        local = {}

    nf_count = local.get("nf_conntrack_count") or 0
    nf_max = local.get("nf_conntrack_max") or 1
    nf_unre = local.get("nf_unreplied") or 0
    nf_syns = local.get("nf_syn_sent") or 0
    top_ip = local.get("nf_top_lan_ip") or ""
    top_sess = local.get("nf_top_lan_sessions") or 0

    try:
        nf_pct = (float(nf_count) / float(nf_max) * 100.0) if nf_max > 0 else 0.0
    except Exception:
        nf_pct = 0.0

    if nf_pct >= 80 or nf_unre >= 1000 or nf_syns >= 1000 or (top_ip and top_ip != "unknown" and top_sess >= 10000):
        extra = []
        if nf_pct >= 80:
            extra.append(f"conntrack {nf_pct:.0f}%")
        if nf_unre >= 1000:
            extra.append(f"UNREPLIED {nf_unre}")
        if nf_syns >= 1000:
            extra.append(f"SYN_SENT {nf_syns}")
        if top_ip and top_ip != "unknown" and top_sess >= 10000:
            extra.append(f"top talker {top_ip} {top_sess} sess")

        if classification == "GOOD":
            classification = "REGULAR"
        reason = (reason or "") + " | CONNTRACK: " + ", ".join(extra)

    return classification, reason
