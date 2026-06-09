from fastapi.testclient import TestClient


def test_login_works_with_demo_user(client: TestClient):
    """Login with form data (OAuth2). Demo user seeded in lifespan."""
    # Use form style
    resp = client.post("/api/v1/auth/login", data={"username": "tech", "password": "tech123"})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["user"]["username"] == "tech"

