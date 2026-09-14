from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.auth import (
    SESSION_COOKIE,
    hash_password,
    parse_session_value,
    verify_password,
)
from app.auth import get_session as auth_get_session
from app.config import get_settings
from app.dashboard import get_session
from app.db import Base
from app.main import app
from app.models import Advisor, Company, PointOfSale, User


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "auth.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="E1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"))
        session.add(Advisor(advisor_id="AS-001", company_id="EMP-01",
                            point_of_sale_id="PV-001", name="Uno",
                            daily_capacity=5, active=True))
        session.add(Advisor(advisor_id="AS-X", company_id="EMP-01",
                            point_of_sale_id="PV-001", name="Inactivo",
                            daily_capacity=5, active=False))
        session.add(User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                         password_hash=hash_password("correcta"), role="asesor"))
        session.add(User(company_id="EMP-01", advisor_id="AS-X", email="off@x",
                         password_hash=hash_password("correcta"), role="asesor"))
        session.add(User(company_id="EMP-01", advisor_id=None, email="sup@x",
                         password_hash=hash_password("correcta"), role="supervisor"))
        session.add(User(company_id=None, advisor_id=None, email="admin@x",
                         password_hash=hash_password("correcta"), role="admin"))
        session.commit()

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()
    engine.dispose()


def test_hash_no_es_texto_plano_y_verifica():
    stored = hash_password("demo-asesor-123")
    assert "demo-asesor-123" not in stored
    assert stored.startswith("pbkdf2$")
    assert verify_password("demo-asesor-123", stored) is True
    assert verify_password("otra", stored) is False
    assert verify_password("x", "formato-invalido") is False


def test_sesion_firmada_no_acepta_forgery():
    secret = get_settings().secret_key
    from app.auth import create_session_value

    value = create_session_value(7, secret)
    assert parse_session_value(value, secret) == 7
    assert parse_session_value(value, "otra-clave") is None
    assert parse_session_value("7:9999999999:firma-falsa", secret) is None
    assert parse_session_value("basura", secret) is None


def test_login_valido_asesor_redirige_a_dashboard(client):
    response = client.post("/login", data={"email": "adv@x", "password": "correcta"})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert SESSION_COOKIE in client.cookies


def test_login_valido_supervisor_redirige_a_supervision(client):
    response = client.post("/login", data={"email": "sup@x", "password": "correcta"})
    assert response.status_code == 303
    assert response.headers["location"] == "/supervision"


def test_login_valido_admin_redirige_a_supervision(client):
    response = client.post("/login", data={"email": "admin@x", "password": "correcta"})
    assert response.status_code == 303
    assert response.headers["location"] == "/supervision"


def test_login_invalido_muestra_error(client):
    response = client.post("/login", data={"email": "adv@x", "password": "mala"})
    assert response.status_code == 401
    assert "Credenciales inv" in response.text
    assert SESSION_COOKIE not in client.cookies

    response = client.post("/login", data={"email": "nadie@x", "password": "x"})
    assert response.status_code == 401


def test_login_asesor_inactivo_rechazado(client):
    response = client.post("/login", data={"email": "off@x", "password": "correcta"})
    assert response.status_code == 403
    assert SESSION_COOKIE not in client.cookies


def test_logout_invalida_sesion(client):
    client.post("/login", data={"email": "adv@x", "password": "correcta"})
    assert SESSION_COOKIE in client.cookies
    response = client.get("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert client.get("/").status_code == 303


def test_rutas_protegidas_sin_sesion(client):
    for path in ("/", "/supervision", "/leads/LD-1"):
        response = client.get(path)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/login", path
