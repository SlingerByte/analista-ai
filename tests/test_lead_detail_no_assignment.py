"""Detalle del lead sin asignación vigente: scope por empresa/rol."""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.auth import hash_password
from app.auth import get_session as auth_get_session
from app.dashboard import get_session
from app.db import Base
from app.main import app
from app.models import Advisor, Assignment, Company, Lead, PointOfSale, User

DAY = date(2026, 9, 14)
PASSWORD = "secret"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture()
def env(tmp_path):
    db_path = tmp_path / "lead_no_assign.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        s.add_all([Company(company_id="EMP-01", name="E1"),
                   Company(company_id="EMP-02", name="E2")])
        s.add_all([
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1"),
            PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="P6"),
        ])
        s.add(Advisor(advisor_id="AS-001", company_id="EMP-01", point_of_sale_id="PV-001",
                      name="Asesor Uno", daily_capacity=5, active=True))
        s.add_all([
            User(company_id="EMP-01", advisor_id="AS-001", email="adv@x",
                 password_hash=PASSWORD_HASH, role="asesor"),
            User(company_id="EMP-01", advisor_id=None, email="sup@x",
                 password_hash=PASSWORD_HASH, role="supervisor"),
            User(company_id="EMP-01", advisor_id=None, email="adm@x",
                 password_hash=PASSWORD_HASH, role="admin"),
        ])
        for lead_id, company, pos in (("LD-ASSIGNED", "EMP-01", "PV-001"),
                                      ("LD-UNASSIGNED", "EMP-01", "PV-001"),
                                      ("LD-OTHER", "EMP-02", "PV-006")):
            s.add(Lead(lead_id=lead_id, company_id=company, point_of_sale_id=pos,
                       customer_name=lead_id, raw_payload={}, record_hash=lead_id))
        s.add(Assignment(lead_id="LD-ASSIGNED", advisor_id="AS-001", company_id="EMP-01",
                         point_of_sale_id="PV-001", run_date=DAY, strategy_version="v1",
                         priority_rank=1, status="assigned", reason="x", is_current=True))
        s.commit()

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[auth_get_session] = _override

    def make_client(email: str):
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"email": email, "password": PASSWORD})
        return client

    yield {"make_client": make_client, "maker": maker}
    app.dependency_overrides.clear()
    engine.dispose()


def test_supervisor_opens_assigned_lead(env):
    assert env["make_client"]("sup@x").get("/leads/LD-ASSIGNED").status_code == 200


def test_supervisor_opens_unassigned_lead_in_company(env):
    assert env["make_client"]("sup@x").get("/leads/LD-UNASSIGNED").status_code == 200


def test_supervisor_cannot_open_other_company(env):
    assert env["make_client"]("sup@x").get("/leads/LD-OTHER").status_code == 404


def test_admin_opens_unassigned_and_other_company(env):
    client = env["make_client"]("adm@x")
    assert client.get("/leads/LD-UNASSIGNED").status_code == 200
    assert client.get("/leads/LD-OTHER").status_code == 200


def test_advisor_opens_assigned_lead(env):
    assert env["make_client"]("adv@x").get("/leads/LD-ASSIGNED").status_code == 200


def test_advisor_cannot_open_unassigned_lead(env):
    # Sin asignación vigente el lead no está en el alcance del asesor.
    assert env["make_client"]("adv@x").get("/leads/LD-UNASSIGNED").status_code == 404
    assert env["make_client"]("adv@x").get("/leads/LD-OTHER").status_code == 404


def test_no_assignment_side_effects(env):
    client = env["make_client"]("sup@x")
    with env["maker"]() as s:
        before = s.scalar(sa.select(sa.func.count()).select_from(Assignment))
        sig = s.execute(
            sa.select(Assignment.assignment_id, Assignment.advisor_id,
                      Assignment.status, Assignment.is_current)
            .order_by(Assignment.assignment_id)).all()
    client.get("/leads/LD-UNASSIGNED")
    client.get("/leads/LD-ASSIGNED")
    with env["maker"]() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Assignment)) == before
        assert s.execute(
            sa.select(Assignment.assignment_id, Assignment.advisor_id,
                      Assignment.status, Assignment.is_current)
            .order_by(Assignment.assignment_id)).all() == sig
