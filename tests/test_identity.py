from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.db import Base
from app.identity.conversations import cluster_conversations
from app.identity.service import run_identity
from app.ingestion.service import run_ingestion
from app.models import Conversation, IdentityCluster, IdentityMember, Lead
from app.seed import seed


@pytest.fixture
def factory(tmp_path):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'identity.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        seed(session)
    yield session_factory
    engine.dispose()


def _add_lead(
    session: Session,
    lead_id: str,
    name: str,
    *,
    company_id: str = "EMP-01",
    point_of_sale_id: str = "PV-001",
    phone: str | None = None,
    email: str | None = None,
    city: str | None = None,
):
    session.add(
        Lead(
            lead_id=lead_id,
            company_id=company_id,
            point_of_sale_id=point_of_sale_id,
            customer_name=name,
            phone_normalized=phone,
            email_normalized=email,
            city_normalized=city,
            raw_payload={"source": "test"},
            record_hash=f"hash-{lead_id}",
            is_current=True,
        )
    )


def _clusters(session: Session) -> list[IdentityCluster]:
    return list(session.scalars(sa.select(IdentityCluster)).all())


def _members(session: Session) -> list[IdentityMember]:
    return list(session.scalars(sa.select(IdentityMember)).all())


def test_phone_and_email_is_strong(factory):
    with factory() as session:
        _add_lead(session, "L1", "Juan Perez", phone="3001111111", email="a@x.com", city="Bogotá")
        _add_lead(session, "L2", "Juan Perez", phone="3001111111", email="a@x.com", city="Bogotá")
        session.commit()
        report = run_identity(session)

    assert report["steps"]["relations_by_rule"]["PHONE_EMAIL_EXACT"] == 1
    assert report["steps"]["clusters_created"] == 1
    with factory() as session:
        cluster = _clusters(session)[0]
        members = _members(session)
    assert cluster.match_strength == "strong"
    assert cluster.status == "auto"
    assert {member.rule_id for member in members} == {"PHONE_EMAIL_EXACT"}
    assert all(member.evidence["email_match"] is True for member in members)


def test_phone_and_similar_name_is_possible(factory):
    with factory() as session:
        _add_lead(session, "L1", "Carlos Ramirez", phone="3002222222", city="Bogotá")
        _add_lead(session, "L2", "Carlos Ramirez Gomez", phone="3002222222", city="Bogotá")
        session.commit()
        report = run_identity(session)

    assert report["steps"]["relations_by_rule"]["PHONE_NAME_SIMILAR"] == 1
    with factory() as session:
        cluster = _clusters(session)[0]
        members = _members(session)
    assert cluster.match_strength == "possible"
    assert cluster.status == "possible_pending"
    assert {member.rule_id for member in members} == {"PHONE_NAME_SIMILAR"}
    assert all(member.evidence["name_similarity"] >= 0.90 for member in members)


def test_name_and_city_is_weak(factory):
    with factory() as session:
        _add_lead(session, "L1", "Ana Torres", phone="3003333333", city="Bogotá")
        _add_lead(session, "L2", "Ana Torres", phone="3004444444", city="Bogotá")
        session.commit()
        report = run_identity(session)

    assert report["steps"]["relations_by_rule"]["NAME_CITY_MATCH"] == 1
    with factory() as session:
        cluster = _clusters(session)[0]
        members = _members(session)
    assert cluster.match_strength == "weak"
    assert cluster.status == "possible_pending"
    assert {member.rule_id for member in members} == {"NAME_CITY_MATCH"}


def test_same_phone_different_company_not_linked(factory):
    with factory() as session:
        _add_lead(session, "L1", "Juan Perez", phone="3005555555", email="a@x.com", city="Bogotá")
        _add_lead(
            session,
            "L2",
            "Juan Perez",
            company_id="EMP-02",
            point_of_sale_id="PV-006",
            phone="3005555555",
            email="a@x.com",
            city="Bogotá",
        )
        session.commit()
        report = run_identity(session)

    assert report["steps"]["clusters_created"] == 0
    assert sum(report["steps"]["relations_by_rule"].values()) == 0
    with factory() as session:
        assert _clusters(session) == []


def test_same_name_city_different_company_not_linked(factory):
    with factory() as session:
        _add_lead(session, "L1", "Ana Torres", phone="3006666666", city="Bogotá")
        _add_lead(
            session,
            "L2",
            "Ana Torres",
            company_id="EMP-02",
            point_of_sale_id="PV-006",
            phone="3007777777",
            city="Bogotá",
        )
        session.commit()
        report = run_identity(session)

    assert report["steps"]["clusters_created"] == 0
    with factory() as session:
        assert _clusters(session) == []


def test_no_evidence_no_cluster(factory):
    with factory() as session:
        _add_lead(session, "L1", "Pedro Uno", phone="3008888888", city="Bogotá")
        _add_lead(session, "L2", "Maria Dos", phone="3009999999", city="Medellín")
        session.commit()
        report = run_identity(session)

    assert report["steps"]["clusters_created"] == 0
    assert report["steps"]["members_created"] == 0


def test_three_related_leads_one_cluster(factory):
    with factory() as session:
        _add_lead(session, "L1", "Juan Perez", phone="3001212121", email="a@x.com", city="Bogotá")
        _add_lead(session, "L2", "Juan Perez", phone="3001212121", email="a@x.com", city="Bogotá")
        _add_lead(session, "L3", "Juan Perez L", phone="3001212121", city="Bogotá")
        session.commit()
        report = run_identity(session)

    assert report["steps"]["clusters_created"] == 1
    assert report["steps"]["members_created"] == 3
    with factory() as session:
        assert len(_clusters(session)) == 1
        assert len(_members(session)) == 3


def test_identity_is_idempotent(factory):
    with factory() as session:
        _add_lead(session, "L1", "Juan Perez", phone="3001313131", email="a@x.com", city="Bogotá")
        _add_lead(session, "L2", "Juan Perez", phone="3001313131", email="a@x.com", city="Bogotá")
        session.commit()
        first = run_identity(session)
    with factory() as session:
        second = run_identity(session)

    assert first["steps"]["clusters_created"] == 1
    assert second["steps"]["clusters_created"] == 0
    assert second["steps"]["clusters_reused"] == 1
    assert second["steps"]["members_created"] == 0
    assert second["steps"]["members_unchanged"] == 2
    with factory() as session:
        assert len(_clusters(session)) == 1
        assert len(_members(session)) == 2


def test_orphan_conversation_stays_orphan(factory):
    with factory() as session:
        session.add(
            Conversation(
                conversation_id="CONV-ORPHAN",
                lead_id=None,
                company_id=None,
                channel="WhatsApp",
                status="orphan",
                messages=[{"seq": 1, "sender": "cliente", "hour": "10:00", "text": "hola"}],
            )
        )
        _add_lead(session, "L1", "Pedro Uno", phone="3001414141", city="Bogotá")
        session.commit()
        report = run_identity(session)

    assert report["steps"]["conversations_orphan"] == 1
    assert report["steps"]["conversations_with_lead"] == 0
    with factory() as session:
        conversation = session.get(Conversation, "CONV-ORPHAN")
        assert conversation.status == "orphan"
        assert conversation.lead_id is None
        assert conversation.company_id is None
        assert session.scalar(sa.select(sa.func.count()).select_from(Lead)) == 1


def test_multiple_conversations_are_preserved(factory):
    with factory() as session:
        _add_lead(session, "L1", "Juan Perez", phone="3001515151", email="a@x.com", city="Bogotá")
        _add_lead(session, "L2", "Juan Perez", phone="3001515151", email="a@x.com", city="Bogotá")
        session.add(
            Conversation(
                conversation_id="CONV-B",
                lead_id="L1",
                company_id="EMP-01",
                channel="WhatsApp",
                status="linked",
                messages=[],
            )
        )
        session.add(
            Conversation(
                conversation_id="CONV-A",
                lead_id="L1",
                company_id="EMP-01",
                channel="WhatsApp",
                status="linked",
                messages=[],
            )
        )
        session.commit()
        run_identity(session)

    with factory() as session:
        cluster = _clusters(session)[0]
        conversations = cluster_conversations(session, cluster.cluster_id)
    assert [conversation.conversation_id for conversation in conversations] == ["CONV-A", "CONV-B"]


def test_leads_are_not_modified(factory):
    with factory() as session:
        _add_lead(session, "L1", "Juan Perez", phone="3001616161", email="a@x.com", city="Bogotá")
        _add_lead(session, "L2", "Juan Perez", phone="3001616161", email="a@x.com", city="Bogotá")
        session.commit()
        before = {
            lead.lead_id: (
                lead.company_id,
                lead.point_of_sale_id,
                lead.customer_name,
                lead.phone_normalized,
                dict(lead.raw_payload),
            )
            for lead in session.scalars(sa.select(Lead)).all()
        }
        run_identity(session)
    with factory() as session:
        after = {
            lead.lead_id: (
                lead.company_id,
                lead.point_of_sale_id,
                lead.customer_name,
                lead.phone_normalized,
                dict(lead.raw_payload),
            )
            for lead in session.scalars(sa.select(Lead)).all()
        }
    assert before == after
    assert set(before) == {"L1", "L2"}


@pytest.fixture(scope="module")
def real_pipeline(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("identity_real") / "real.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        seed(session)
        run_ingestion(session)
        report = run_identity(session)
    yield session_factory, report
    engine.dispose()


def test_real_clusters_never_mix_companies(real_pipeline):
    session_factory, _ = real_pipeline
    with session_factory() as session:
        rows = session.execute(
            sa.select(IdentityMember.cluster_id, Lead.company_id)
            .join(Lead, Lead.lead_id == IdentityMember.lead_id)
        ).all()
    companies_by_cluster: dict[int, set[str]] = {}
    for cluster_id, company_id in rows:
        companies_by_cluster.setdefault(cluster_id, set()).add(company_id)
    assert companies_by_cluster
    assert all(len(companies) == 1 for companies in companies_by_cluster.values())


def test_real_conversation_report(real_pipeline):
    _, report = real_pipeline
    steps = report["steps"]
    assert steps["conversations_with_lead"] == 665
    assert steps["conversations_orphan"] == 12
    assert steps["leads_with_multiple_conversations"] == 25


def test_real_leads_are_preserved(real_pipeline):
    session_factory, _ = real_pipeline
    with session_factory() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Lead)) == 1501
