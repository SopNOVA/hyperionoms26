from fastapi.testclient import TestClient


def test_telemetry_ingest_and_classification(client: TestClient):
    """Real ingest + smart classification (GOOD even with high TCP retrans if services OK)."""
    # First ensure an ONT
    client.post("/api/v1/onts/", json={"gpon_sn": "INGEST-TEST-001"})

    payload = {
        "gpon_sn": "INGEST-TEST-001",
        "pings": {"8.8.8.8": {"avg": 19}, "1.1.1.1": {"avg": 15}},
        "tcp_retrans": 72,
        "services": [{"name": "DNS", "latency_ms": 6, "status": "ok"}],
        "total_connection_time_ms": 165,
        "jitter": 2.8
    }
    resp = client.post("/api/v1/telemetry/ingest", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["classification"] == "GOOD"
    assert "Observación" in (body.get("reason") or "") or body.get("reason") is None  # good with note

