from fastapi.testclient import TestClient


def test_create_and_list_olts(client: TestClient):
    payload = {"name": "OLT-TEST-01", "ip_address": "192.168.99.10", "location": "Lab"}
    r = client.post("/api/v1/olts/", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "OLT-TEST-01"
    assert data["status"] == "UP"

    r2 = client.get("/api/v1/olts/")
    assert r2.status_code == 200
    assert len(r2.json()) >= 1
