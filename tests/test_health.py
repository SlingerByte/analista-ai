from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, follow_redirects=False)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "database" in body


def test_index_requiere_login():
    response = client.get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_renders():
    response = client.get("/login")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Priorizacion" in response.text or "Ingresar" in response.text
