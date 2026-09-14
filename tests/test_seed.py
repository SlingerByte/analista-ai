import sqlalchemy as sa
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db import Base
from app.models import Advisor
from app.seed import seed

EXPECTED_COUNTS = {
    "companies": 3,
    "points_of_sale": 15,
    "advisors": 42,
    "catalog_items": 24,
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
