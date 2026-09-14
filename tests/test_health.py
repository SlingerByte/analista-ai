from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "database" in body


def test_index_page_renders(tmp_path):
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from app.dashboard import get_session
    from app.db import Base
    from app.models import Advisor, Company, PointOfSale

    # El dashboard (/) requiere esquema migrado: se usa un sqlite en archivo
    # con un asesor demo mínimo.
    db_path = tmp_path / "health.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="E1"))
        session.add(
            PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="P1")
        )
        session.add(
            Advisor(
                advisor_id="AS-001",
                company_id="EMP-01",
                point_of_sale_id="PV-001",
                name="Demo",
                daily_capacity=5,
                active=True,
            )
        )
        session.commit()

    def _override():
        session = maker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    try:
        response = client.get("/")
    finally:
        app.dependency_overrides.clear()
    engine.dispose()

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Priorizacion" in response.text
