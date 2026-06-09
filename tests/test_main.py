from fastapi.testclient import TestClient


def test_root(client: TestClient):
    """Test the root endpoint (now serves the self-contained dashboard HTML)."""
    response = client.get("/")
    assert response.status_code == 200
    # The dashboard is a full HTML document (Tailwind + Chart.js).
    # We only assert that it is the expected Hyperion-ONMS UI.
    content = response.text.lower()
    assert "hyperion" in content and "onms" in content
    # Sanity: it should be HTML, not a JSON error
    assert "<!doctype html" in content or "<html" in content


def test_health(client: TestClient):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
