from fastapi.testclient import TestClient


def test_list_onts_empty(client: TestClient):
    """Initially no ONTs, list should return empty list."""
    response = client.get("/api/v1/onts/")
    assert response.status_code == 200
    assert response.json() == []


def test_create_ont(client: TestClient):
    """Create a new ONU via POST."""
    payload = {
        "gpon_sn": "TESTGPON123456",
        "ip_address": "192.168.1.100",
        "model": "TestModel-X",
        "location": "Test Zone",
    }
    response = client.post("/api/v1/onts/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["gpon_sn"] == "TESTGPON123456"
    assert data["ip_address"] == "192.168.1.100"
    assert data["id"] is not None
    assert data["is_active"] is True


def test_create_ont_duplicate_gpon(client: TestClient):
    """Creating duplicate gpon_sn should probably fail or be handled.
    Current impl has TODO for duplicate check, so for now it may allow or DB unique will catch.
    """
    payload = {"gpon_sn": "DUPTEST001"}
    # First create
    r1 = client.post("/api/v1/onts/", json=payload)
    assert r1.status_code == 201

    # Second should fail at DB level (unique constraint)
    r2 = client.post("/api/v1/onts/", json=payload)
    # Expect 400 or 500? Currently no handling, sqlalchemy will raise IntegrityError -> 500
    # For first tests we accept it fails; later add proper error handling + 409
    assert r2.status_code in (400, 409, 422, 500)


def test_get_ont_by_gpon(client: TestClient):
    """Get specific ONU by gpon_sn."""
    # Create one
    payload = {"gpon_sn": "GETTEST001", "model": "GetModel"}
    create_resp = client.post("/api/v1/onts/", json=payload)
    assert create_resp.status_code == 201

    # Get it
    response = client.get("/api/v1/onts/GETTEST001")
    assert response.status_code == 200
    data = response.json()
    assert data["gpon_sn"] == "GETTEST001"
    assert data["model"] == "GetModel"


def test_get_ont_not_found(client: TestClient):
    """404 for unknown gpon_sn."""
    response = client.get("/api/v1/onts/NONEXISTENT999")
    assert response.status_code == 404
    assert "no encontrada" in response.json()["detail"].lower()
