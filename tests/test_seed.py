import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.config import get_settings
from app.db import Base
from app.models import Advisor, PointOfSale, User
from app.seed import seed

EXPECTED_COUNTS = {
    "companies": 3,
    "points_of_sale": 15,
    "advisors": 42,
    "catalog_items": 24,
    "users": 3,
}


def _make_engine(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'seed.db'}")
    Base.metadata.create_all(engine)
    return engine


def test_seed_loads_structural_data(tmp_path):
    engine = _make_engine(tmp_path)

    with Session(engine) as session:
        counts = seed(session)

    assert counts == EXPECTED_COUNTS


def test_seed_is_idempotent(tmp_path):
    engine = _make_engine(tmp_path)

    with Session(engine) as session:
        first = seed(session)
    with Session(engine) as session:
        second = seed(session)

    assert first == EXPECTED_COUNTS
    assert second == first

    with Session(engine) as session:
        inactive = session.scalar(
            sa.select(sa.func.count()).select_from(Advisor).where(Advisor.active.is_(False))
        )
    assert inactive == 2


def test_seed_creates_demo_users_on_fresh_db_without_autoflush(tmp_path):
    """Regresión: `SessionLocal` usa autoflush=False.

    El seed debe crear los 3 usuarios demo en una base nueva en una sola
    ejecución, sin depender de que la sesión haga autoflush.
    """
    engine = _make_engine(tmp_path)
    maker = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    settings = get_settings()

    with maker() as session:
        counts = seed(session)
    assert counts["users"] == 3

    with maker() as session:
        users = {user.email: user for user in session.scalars(sa.select(User)).all()}
        assert set(users) == {
            settings.advisor_demo_email.strip().lower(),
            settings.supervisor_demo_email.strip().lower(),
            settings.admin_demo_email.strip().lower(),
        }

        advisor_user = users[settings.advisor_demo_email.strip().lower()]
        assert advisor_user.role == "asesor"
        assert advisor_user.advisor_id is not None
        assert advisor_user.company_id is not None
        # Relación coherente con el asesor real (empresa / punto de venta).
        advisor = session.get(Advisor, advisor_user.advisor_id)
        assert advisor is not None
        assert advisor.company_id == advisor_user.company_id
        assert advisor.point_of_sale_id is not None
        assert session.get(PointOfSale, advisor.point_of_sale_id) is not None

        supervisor_user = users[settings.supervisor_demo_email.strip().lower()]
        assert supervisor_user.role == "supervisor"
        assert supervisor_user.company_id is not None

        admin_user = users[settings.admin_demo_email.strip().lower()]
        assert admin_user.role == "admin"
        assert admin_user.company_id is None

    # Re-ejecutar no debe duplicar usuarios.
    with maker() as session:
        seed(session)
    with maker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(User)) == 3
