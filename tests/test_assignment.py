from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.assignment.service import (
    STRATEGY_VERSION,
    AdvisorCapacity,
    LeadCandidate,
    plan_assignments,
    retry_assignment,
    run_assignment,
)
from app.db import Base
from app.models import (
    Advisor,
    Assignment,
    Company,
    IdentityCluster,
    IdentityMember,
    Lead,
    LeadScore,
    PointOfSale,
)
from app.seed import seed


def _advisor(advisor_id, company="EMP-01", pos="PV-001", capacity=5, active=True):
    return AdvisorCapacity(
        advisor_id=advisor_id,
        company_id=company,
        point_of_sale_id=pos,
        daily_capacity=capacity,
        active=active,
    )


def _lead(lead_id, company="EMP-01", pos="PV-001", queue=50.0):
    return LeadCandidate(
        lead_id=lead_id, company_id=company, point_of_sale_id=pos, queue=queue
    )


def test_empresa_un_lead_nunca_va_a_asesor_de_otra_empresa():
    decisions = plan_assignments(
        [_lead("LD-1", company="EMP-01")],
        [_advisor("AS-1", company="EMP-02", pos="PV-006", capacity=5)],
    )
    assert decisions[0].status == "overflow"

    mixed = plan_assignments(
        [_lead("LD-1", company="EMP-01")],
        [
            _advisor("AS-1", company="EMP-02", pos="PV-006", capacity=5),
            _advisor("AS-2", company="EMP-01", pos="PV-001", capacity=5),
        ],
    )
    assert mixed[0].advisor_id == "AS-2"


def test_pos_un_lead_nunca_va_a_asesor_de_otro_pos():
    decisions = plan_assignments(
        [_lead("LD-1", pos="PV-001")],
        [
            _advisor("AS-1", pos="PV-002", capacity=5),
            _advisor("AS-2", pos="PV-001", capacity=5),
        ],
    )
    assert decisions[0].advisor_id == "AS-2"
    assert decisions[0].status == "assigned"


def test_asesores_inactivos_nunca_reciben_leads():
    decisions = plan_assignments(
        [_lead("LD-1"), _lead("LD-2")],
        [_advisor("AS-1", capacity=5, active=False)],
    )
    assert all(d.status == "overflow" for d in decisions)


def test_ningun_asesor_supera_su_capacidad_y_reparto_respeta_pesos():
    leads = [_lead(f"LD-{i:02d}", queue=90.0 - i) for i in range(6)]
    decisions = plan_assignments(
        leads, [_advisor("AS-1", capacity=4), _advisor("AS-2", capacity=2)]
    )
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.advisor_id] = counts.get(decision.advisor_id, 0) + 1
    assert counts == {"AS-1": 4, "AS-2": 2}


def test_overflow_conserva_datos_y_motivo():
    decisions = plan_assignments([_lead("LD-1")], [_advisor("AS-1", capacity=0)])
    (decision,) = decisions
    assert decision.status == "overflow"
    assert decision.advisor_id is None
    assert decision.reason == "sin_capacidad"
    assert decision.company_id == "EMP-01"
    assert decision.point_of_sale_id == "PV-001"
    assert decision.priority_rank == 1


def test_determinismo_misma_entrada_mismas_decisiones():
    leads = [_lead(f"LD-{i:02d}", queue=float(i % 3)) for i in range(10)]
    advisors = [_advisor("AS-1", capacity=3), _advisor("AS-2", capacity=3)]
    assert plan_assignments(leads, advisors) == plan_assignments(leads, advisors)


def test_prioridad_mayor_queue_recibe_mejor_rank():
    decisions = plan_assignments(
        [_lead("LD-B", queue=10.0), _lead("LD-A", queue=90.0)],
        [_advisor("AS-1", capacity=5)],
    )
    by_lead = {d.lead_id: d for d in decisions}
    assert by_lead["LD-A"].priority_rank == 1
    assert by_lead["LD-B"].priority_rank == 2


def test_desempate_mismo_score_por_lead_id():
    decisions = plan_assignments(
        [_lead("LD-03", queue=50.0), _lead("LD-01", queue=50.0), _lead("LD-02", queue=50.0)],
        [_advisor("AS-1", capacity=5)],
    )
    assert [d.lead_id for d in decisions] == ["LD-01", "LD-02", "LD-03"]
    assert [d.priority_rank for d in decisions] == [1, 2, 3]


@pytest.fixture()
def factory(tmp_path):
    db_path = tmp_path / "assignment.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="Empresa 1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="PV 1"))
        session.commit()
    yield maker
    engine.dispose()


def _add_lead(session, lead_id, status="Contactado", pos="PV-001", company="EMP-01"):
    session.add(
        Lead(
            lead_id=lead_id,
            company_id=company,
            point_of_sale_id=pos,
            status=status,
            raw_payload={"lead_id": lead_id},
            record_hash="abc",
        )
    )


def _add_score(session, lead_id, queue=50.0, current=True):
    session.add(
        LeadScore(
            lead_id=lead_id,
            score_version="v1",
            priority_score=queue,
            urgency_score=10.0,
            queue_score=queue,
            band="Media",
            is_current=current,
        )
    )


def _add_advisor(session, advisor_id, capacity=5, active=True):
    session.add(
        Advisor(
            advisor_id=advisor_id,
            company_id="EMP-01",
            point_of_sale_id="PV-001",
            name=advisor_id,
            daily_capacity=capacity,
            active=active,
        )
    )


def test_descartado_no_se_asigna(factory):
    with factory() as session:
        _add_lead(session, "LD-01", status="Descartado")
        _add_score(session, "LD-01", queue=99.0)
        _add_advisor(session, "AS-01")
        session.commit()
        report = run_assignment(session, date(2026, 9, 14))
        assert report["candidates"] == 0
        assert session.scalar(sa.select(sa.func.count()).select_from(Assignment)) == 0


def test_solo_scores_vigentes(factory):
    with factory() as session:
        _add_lead(session, "LD-01")
        _add_score(session, "LD-01", queue=99.0, current=False)
        _add_advisor(session, "AS-01")
        session.commit()
        assert run_assignment(session, date(2026, 9, 14))["candidates"] == 0

        _add_score(session, "LD-01", queue=10.0, current=True)
        session.commit()
        report = run_assignment(session, date(2026, 9, 15))
        assert report["assigned"] == 1
        row = session.scalar(sa.select(Assignment))
        assert row.priority_rank == 1
        assert row.strategy_version == STRATEGY_VERSION


def test_identidad_canonico_si_miembro_no(factory):
    with factory() as session:
        _add_lead(session, "LD-01")
        _add_lead(session, "LD-02")
        _add_score(session, "LD-01", queue=80.0)
        _add_score(session, "LD-02", queue=90.0)
        _add_advisor(session, "AS-01", capacity=5)
        session.add(
            IdentityCluster(
                cluster_id=1,
                company_id="EMP-01",
                canonical_lead_id="LD-01",
                status="auto",
                match_strength="strong",
            )
        )
        session.add(
            IdentityMember(cluster_id=1, lead_id="LD-01", role="canonical",
                           match_strength="strong")
        )
        session.add(
            IdentityMember(cluster_id=1, lead_id="LD-02", role="member",
                           match_strength="strong")
        )
        session.commit()
        report = run_assignment(session, date(2026, 9, 14))
        assert report["candidates"] == 1
        row = session.scalar(sa.select(Assignment))
        assert row.lead_id == "LD-01"  # sin doble gestión del miembro


def test_identidad_descartada_vuelve_a_priorizar_miembros(factory):
    with factory() as session:
        _add_lead(session, "LD-01")
        _add_lead(session, "LD-02")
        _add_score(session, "LD-01", queue=80.0)
        _add_score(session, "LD-02", queue=90.0)
        _add_advisor(session, "AS-01", capacity=5)
        session.add(
            IdentityCluster(
                cluster_id=1,
                company_id="EMP-01",
                canonical_lead_id="LD-01",
                status="reviewed_discarded",
                match_strength="weak",
            )
        )
        session.add(
            IdentityMember(cluster_id=1, lead_id="LD-01", role="canonical",
                           match_strength="weak")
        )
        session.add(
            IdentityMember(cluster_id=1, lead_id="LD-02", role="member",
                           match_strength="weak")
        )
        session.commit()
        assert run_assignment(session, date(2026, 9, 14))["candidates"] == 2


def test_reejecucion_versiona_sin_duplicar_vigentes(factory):
    day = date(2026, 9, 14)
    with factory() as session:
        _add_lead(session, "LD-01")
        _add_score(session, "LD-01", queue=80.0)
        _add_advisor(session, "AS-01", capacity=5)
        session.commit()
        run_assignment(session, day)
        run_assignment(session, day)
        rows = session.scalars(
            sa.select(Assignment).where(Assignment.lead_id == "LD-01").order_by(
                Assignment.assignment_id)
        ).all()
        assert [row.is_current for row in rows] == [False, True]
        current = session.scalars(
            sa.select(Assignment).where(
                Assignment.lead_id == "LD-01", Assignment.is_current.is_(True))
        ).all()
        assert len(current) == 1


def test_cobertura_15_pos_con_seed_real(tmp_path):
    db_path = tmp_path / "assignment_seed.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        seed(session)
        advisors = session.scalars(sa.select(Advisor)).all()
        assert {a.point_of_sale_id for a in advisors if a.active} == {
            f"PV-{i:03d}" for i in range(1, 16)
        }
        groups = sorted({(a.company_id, a.point_of_sale_id) for a in advisors})
        assert len(groups) == 15
        for index, (company, pos) in enumerate(groups):
            for slot in range(2):
                lead_id = f"LD-{pos}-{slot}"
                session.add(
                    Lead(
                        lead_id=lead_id,
                        company_id=company,
                        point_of_sale_id=pos,
                        status="Contactado",
                        raw_payload={"lead_id": lead_id},
                        record_hash="abc",
                    )
                )
                session.add(
                    LeadScore(
                        lead_id=lead_id,
                        score_version="v1",
                        priority_score=50.0 - index,
                        urgency_score=10.0,
                        queue_score=50.0 - index,
                        band="Media",
                        is_current=True,
                    )
                )
        session.commit()
        report = run_assignment(session, date(2026, 9, 14))
        assert report["groups"] == 15
        assert report["candidates"] == 30
        assert report["overflow"] == 0
        rows = session.scalars(sa.select(Assignment)).all()
        for row in rows:
            advisor = session.get(Advisor, row.advisor_id)
            assert advisor.active is True
            assert (row.company_id, row.point_of_sale_id) == (
                advisor.company_id, advisor.point_of_sale_id)
            assert (row.company_id, row.point_of_sale_id) == (
                session.get(Lead, row.lead_id).company_id,
                session.get(Lead, row.lead_id).point_of_sale_id,
            )
        assert "AS-037" not in report["per_advisor"]
        assert "AS-040" not in report["per_advisor"]
    engine.dispose()


# --- Overflow / reintento (Phase 2) ----------------------------------------


def test_retry_fills_overflow_when_capacity_appears(factory):
    day = date(2026, 9, 14)
    with factory() as session:
        _add_lead(session, "LD-01")
        _add_lead(session, "LD-02")
        _add_score(session, "LD-01", queue=90.0)
        _add_score(session, "LD-02", queue=80.0)
        _add_advisor(session, "AS-01", capacity=1)
        session.commit()

        first = run_assignment(session, day)
        assert first["assigned"] == 1
        assert first["overflow"] == 1

        # Aparece capacidad (p. ej. se reactiva/amplía un asesor).
        session.get(Advisor, "AS-01").daily_capacity = 2
        session.commit()

        retry = retry_assignment(session, day)
        assert retry["reused"] is False
        assert retry["assigned"] == 2
        assert retry["overflow"] == 0

        current = session.scalars(
            sa.select(Assignment).where(Assignment.is_current.is_(True))
        ).all()
        assert {row.lead_id for row in current} == {"LD-01", "LD-02"}
        assert all(row.status == "assigned" for row in current)

        total_rows = session.scalar(sa.select(sa.func.count()).select_from(Assignment))
        second = retry_assignment(session, day)
        assert second["reused"] is True
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(Assignment))
            == total_rows
        )


def test_retry_is_idempotent_without_changes(factory):
    day = date(2026, 9, 14)
    with factory() as session:
        _add_lead(session, "LD-01")
        _add_score(session, "LD-01", queue=50.0)
        _add_advisor(session, "AS-01", capacity=5)
        session.commit()

        run_assignment(session, day)
        total_rows = session.scalar(sa.select(sa.func.count()).select_from(Assignment))
        retry = retry_assignment(session, day)
        assert retry["reused"] is True
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(Assignment))
            == total_rows
        )
        assert (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(Assignment)
                .where(Assignment.is_current.is_(True))
            )
            == 1
        )


def test_retry_keeps_overflow_when_capacity_is_in_another_pos(factory):
    day = date(2026, 9, 14)
    with factory() as session:
        session.add(PointOfSale(point_of_sale_id="PV-002", company_id="EMP-01", name="PV 2"))
        session.add(
            Advisor(advisor_id="AS-02", company_id="EMP-01", point_of_sale_id="PV-002",
                    name="Dos", daily_capacity=5, active=True)
        )
        _add_lead(session, "LD-01")  # PV-001
        _add_score(session, "LD-01", queue=50.0)
        _add_advisor(session, "AS-01", capacity=0)  # PV-001 sin capacidad
        session.commit()

        retry = retry_assignment(session, day)
        assert retry["assigned"] == 0
        assert retry["overflow"] == 1
        row = session.scalar(
            sa.select(Assignment).where(Assignment.is_current.is_(True))
        )
        assert row.status == "overflow"
        assert row.advisor_id is None
        assert row.reason == "sin_capacidad"


def test_retry_scoped_by_company_leaves_others_untouched(factory):
    day = date(2026, 9, 14)
    with factory() as session:
        session.add(Company(company_id="EMP-02", name="Empresa 2"))
        session.add(PointOfSale(point_of_sale_id="PV-006", company_id="EMP-02", name="PV 6"))
        session.add(
            Advisor(advisor_id="AS-09", company_id="EMP-02", point_of_sale_id="PV-006",
                    name="Nueve", daily_capacity=5, active=True)
        )
        _add_lead(session, "LD-01")  # EMP-01 / PV-001
        _add_lead(session, "LD-90", company="EMP-02", pos="PV-006")
        _add_score(session, "LD-01", queue=50.0)
        _add_score(session, "LD-90", queue=50.0)
        _add_advisor(session, "AS-01", capacity=0)  # EMP-01 queda en overflow
        session.commit()

        run_assignment(session, day)
        emp02_before = session.scalars(
            sa.select(Assignment).where(
                Assignment.company_id == "EMP-02", Assignment.is_current.is_(True)
            )
        ).all()
        assert len(emp02_before) == 1
        ids_before = [row.assignment_id for row in emp02_before]

        retry_assignment(session, day, company_ids={"EMP-01"})

        emp02_after = session.scalars(
            sa.select(Assignment).where(
                Assignment.company_id == "EMP-02", Assignment.is_current.is_(True)
            )
        ).all()
        assert [row.assignment_id for row in emp02_after] == ids_before
