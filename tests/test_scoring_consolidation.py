from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.ai.service import STATUS_ERROR, STATUS_SUCCESS
from app.db import Base
from app.models import AIExtraction, Company, Conversation, Lead, LeadScore, PointOfSale
from app.scoring.consolidation import consolidate_lead_extractions
from app.scoring.service import prepare_lead_signals, score_and_persist_lead

FIELDS_BASE = {
    "schema_version": "v1",
    "model_interes": None,
    "model_interes_evidence": None,
    "presupuesto": None,
    "presupuesto_evidence": None,
    "cuota_inicial": None,
    "cuota_inicial_evidence": None,
    "forma_pago": None,
    "forma_pago_evidence": None,
    "intencion_compra": None,
    "intencion_compra_evidence": None,
    "objecion": None,
    "objecion_evidence": None,
    "solicitud_cita": None,
    "solicitud_cita_evidence": None,
    "solicitud_cotizacion": None,
    "solicitud_cotizacion_evidence": None,
}


def _row(extraction_id, conversation_id, status=STATUS_SUCCESS, **overrides):
    fields = dict(FIELDS_BASE)
    fields.update(overrides)
    return AIExtraction(
        extraction_id=extraction_id,
        conversation_id=conversation_id,
        lead_id="LD-00001",
        provider="fake",
        model_name="fake-1",
        prompt_version="v2",
        schema_version="v1",
        status=status,
        error=None if status == STATUS_SUCCESS else "boom",
        input_hash=f"hash-{extraction_id}",
        fields=fields if status == STATUS_SUCCESS else None,
        is_current=True,
    )


@pytest.fixture()
def factory(tmp_path):
    db_path = tmp_path / "consolidation.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as session:
        session.add(Company(company_id="EMP-01", name="Empresa 1"))
        session.add(PointOfSale(point_of_sale_id="PV-001", company_id="EMP-01", name="PV 1"))
        for lead_id in ("LD-00001", "LD-00002"):
            session.add(
                Lead(
                    lead_id=lead_id,
                    company_id="EMP-01",
                    point_of_sale_id="PV-001",
                    status="Sin gestión",
                    phone_raw="3001234567",
                    phone_normalized="3001234567",
                    raw_payload={"lead_id": lead_id},
                    record_hash="abc",
                )
            )
        session.add(
            Conversation(
                conversation_id="CONV-A",
                lead_id="LD-00001",
                company_id="EMP-01",
                status="linked",
                messages=[{"seq": 1, "sender": "cliente", "hour": "", "text": "Hola"}],
            )
        )
        session.add(
            Conversation(
                conversation_id="CONV-B",
                lead_id="LD-00001",
                company_id="EMP-01",
                status="linked",
                messages=[{"seq": 1, "sender": "cliente", "hour": "", "text": "Sigo mirando"}],
            )
        )
        session.commit()
    yield maker
    engine.dispose()


def test_1_lead_sin_conversacion_deja_ia_en_none(factory):
    with factory() as session:
        signals = prepare_lead_signals(session, "LD-00002")
        assert signals.has_conversation is False
        assert signals.intencion_compra is None
        assert signals.presupuesto is None
        assert signals.solicitud_cita is None
        scored = score_and_persist_lead(session, "LD-00002")
        assert scored.result.commercial == 20.0  # solo base, sin castigo


def test_2_una_extraccion_valida_alimenta_senales(factory):
    with factory() as session:
        session.add(
            _row(1, "CONV-A", intencion_compra="media",
                 intencion_compra_evidence="lo estoy pensando",
                 solicitud_cotizacion=True,
                 solicitud_cotizacion_evidence="me la cotiza")
        )
        session.commit()
        signals = prepare_lead_signals(session, "LD-00001")
        assert signals.has_conversation is True
        assert signals.intencion_compra == "media"
        assert signals.solicitud_cotizacion is True
        assert signals.solicitud_cita is None


def test_3_multiples_conversaciones_se_consolidan(factory):
    with factory() as session:
        session.add(_row(1, "CONV-A", intencion_compra="baja",
                          intencion_compra_evidence="solo miro"))
        session.add(_row(2, "CONV-B", forma_pago="financiacion",
                          forma_pago_evidence="financiada porfa"))
        session.commit()
        signals = prepare_lead_signals(session, "LD-00001")
        assert signals.intencion_compra == "baja"
        assert signals.forma_pago == "financiacion"


def test_4_intencion_mayor_gana_entre_conversaciones(factory):
    assert consolidate_lead_extractions([
        _row(1, "CONV-A", intencion_compra="baja"),
        _row(2, "CONV-B", intencion_compra="alta"),
    ]).intencion_compra == "alta"
    assert consolidate_lead_extractions([
        _row(1, "CONV-A", intencion_compra="alta"),
        _row(2, "CONV-B", intencion_compra="media"),
    ]).intencion_compra == "alta"


def test_5_reciente_gana_en_conflicto_de_forma_de_pago(factory):
    consolidated = consolidate_lead_extractions([
        _row(1, "CONV-A", forma_pago="contado", forma_pago_evidence="de contado"),
        _row(2, "CONV-B", forma_pago="financiacion", forma_pago_evidence="financiada"),
    ])
    assert consolidated.forma_pago == "financiacion"
    assert consolidated.sources["forma_pago"] == 2


def test_6_conflicto_de_presupuesto_prefiere_reciente_con_evidencia(factory):
    consolidated = consolidate_lead_extractions([
        _row(1, "CONV-A", presupuesto=15000000.0,
             presupuesto_evidence="tengo 15 millones"),
        _row(2, "CONV-B", presupuesto=8000000.0),
    ])
    # La evidencia desempatía a favor del valor explícito más antiguo.
    assert consolidated.presupuesto == 15000000.0
    assert consolidated.sources["presupuesto"] == 1


def test_7_conflicto_de_forma_de_pago_usa_mas_reciente(factory):
    with factory() as session:
        session.add(_row(1, "CONV-A", forma_pago="contado"))
        session.add(_row(2, "CONV-B", forma_pago="credito"))
        session.commit()
        signals = prepare_lead_signals(session, "LD-00001")
        assert signals.forma_pago == "credito"


def test_8_cuota_mensual_del_asesor_no_se_convierte(factory):
    # El extractor dejó cuota_inicial en None (la cuota era del asesor):
    # la consolidación no deriva nada.
    consolidated = consolidate_lead_extractions([
        _row(1, "CONV-A", cuota_inicial=None, cuota_inicial_evidence=None),
    ])
    assert consolidated.cuota_inicial is None
    # Y si el extractor sí declaró una inicial explícita, se respeta tal cual.
    declared = consolidate_lead_extractions([
        _row(1, "CONV-A", cuota_inicial=2000000.0,
             cuota_inicial_evidence="tengo 2 millones para la inicial"),
    ])
    assert declared.cuota_inicial == 2000000.0


def test_9_precio_del_asesor_no_es_presupuesto(factory):
    consolidated = consolidate_lead_extractions([_row(1, "CONV-A")])
    assert consolidated.presupuesto is None


def test_10_cita_explicita_en_una_conversacion(factory):
    consolidated = consolidate_lead_extractions([
        _row(1, "CONV-A", solicitud_cita=None),
        _row(2, "CONV-B", solicitud_cita=True,
             solicitud_cita_evidence="a que hora los visito"),
    ])
    assert consolidated.solicitud_cita is True
    assert consolidated.sources["solicitud_cita"] == 2


def test_11_cotizacion_explicita(factory):
    with factory() as session:
        session.add(_row(1, "CONV-A", solicitud_cotizacion=True,
                          solicitud_cotizacion_evidence="mandeme la cotizacion"))
        session.commit()
        signals = prepare_lead_signals(session, "LD-00001")
        assert signals.solicitud_cotizacion is True
        scored = score_and_persist_lead(session, "LD-00001")
        codes = [r.code for r in scored.result.reasons]
        assert "CLIENTE_PIDIO_COTIZACION" in codes


def test_12_extraccion_con_error_se_ignora(factory):
    consolidated = consolidate_lead_extractions([
        _row(1, "CONV-A", status=STATUS_ERROR),
        _row(2, "CONV-B", intencion_compra="media"),
    ])
    assert consolidated.intencion_compra == "media"
    assert consolidated.had_error is True
    only_error = consolidate_lead_extractions([_row(1, "CONV-A", status=STATUS_ERROR)])
    assert only_error.intencion_compra is None
    assert only_error.solicitud_cita is None


def test_13_evidencia_trazable_a_su_extraccion(factory):
    with factory() as session:
        session.add(_row(1, "CONV-A", objecion="precio",
                          objecion_evidence="esta muy caro para mi"))
        session.commit()
        signals = prepare_lead_signals(session, "LD-00001")
        assert signals.objecion == "precio"
        row = session.get(AIExtraction, 1)
        assert row.fields["objecion_evidence"] == "esta muy caro para mi"


def test_14_consolidacion_determinista_ante_orden(factory):
    rows = [
        _row(1, "CONV-A", intencion_compra="media", forma_pago="contado"),
        _row(2, "CONV-B", intencion_compra="alta", objecion="tiempo"),
    ]
    first = consolidate_lead_extractions(rows)
    second = consolidate_lead_extractions(list(reversed(rows)))
    assert first == second


def test_15_persistencia_idempotente_de_lead_score(factory):
    with factory() as session:
        session.add(_row(1, "CONV-A", intencion_compra="alta"))
        session.commit()
        first = score_and_persist_lead(session, "LD-00001")
        second = score_and_persist_lead(session, "LD-00001")
        assert second.reused is True
        assert second.score_id == first.score_id
        assert session.scalar(
            sa.select(sa.func.count()).select_from(LeadScore).where(
                LeadScore.lead_id == "LD-00001"
            )
        ) == 1

        session.add(_row(2, "CONV-B", solicitud_cita=True))
        session.commit()
        third = score_and_persist_lead(session, "LD-00001")
        assert third.reused is False
        rows = session.scalars(
            sa.select(LeadScore).where(LeadScore.lead_id == "LD-00001").order_by(LeadScore.score_id)
        ).all()
        assert [r.is_current for r in rows] == [False, True]
        assert rows[-1].priority_score == third.result.commercial
        assert rows[-1].params_snapshot["score_version"] == "v1"
