from fastapi.testclient import TestClient


def test_create_and_list_customers_with_matching(client: TestClient):
    """Full customer creation + automatic GPON/MAC matching to ONT."""
    payload = {"name": "Cliente Prueba", "gpon_sn": "TESTGPON98765", "mac_address": "DE:AD:BE:EF:00:11"}
    r = client.post("/api/v1/customers/", json=payload)
    assert r.status_code == 201
    c = r.json()
    assert c["name"] == "Cliente Prueba"
    assert c["gpon_sn"] == "TESTGPON98765"

    # List
    r2 = client.get("/api/v1/customers/")
    assert r2.status_code == 200
    assert len(r2.json()) >= 1

