from __future__ import annotations

from app.scoring.engine import (
    SCORE_V1_PARAMS,
    SCORE_VERSION,
    score_lead,
    to_lead_score_kwargs,
)
from app.scoring.signals import LeadSignals


def _reason_codes(result) -> list[str]:
    return [r.code for r in result.reasons]


def test_alta_intencion_con_cita_es_banda_alta_y_urgencia_hoy():
    signals = LeadSignals(
        lead_id="T-alta",
        list_price=12990000.0,
        model_resolved=True,
        intencion_compra="alta",
        solicitud_cita=True,
        has_conversation=True,
        phone_valid=True,
        estado_gestion="Contactado",
        registration_trustworthy=True,
        days_since_registration=1,
        has_first_contact=True,
    )
    result = score_lead(signals)
    # 20 base + 30 intención + 20 cita + 4.02 ticket = 74.02
    assert result.commercial == 74.02
    assert result.band == "Alta"
    assert result.urgency == 100
    assert result.urgency_band == "Hoy"
    assert "INTENCION_ALTA" in _reason_codes(result)
    assert "CLIENTE_PIDIO_CITA" in _reason_codes(result)
    assert result.queue == round(0.7 * 74.02 + 0.3 * 100, 2)


def test_intencion_media_con_ticket_alto_llega_a_media():
    signals = LeadSignals(
        lead_id="T-media",
        list_price=24900000.0,
        model_resolved=True,
        intencion_compra="media",
        has_conversation=True,
    )
    result = score_lead(signals)
    # 20 base + 15 media + 10 ticket tope = 45
    assert result.commercial == 45.0
    assert result.band == "Media"


def test_modelo_identificado_con_presupuesto_compatible():
    signals = LeadSignals(
        lead_id="T-presupuesto",
        list_price=7290000.0,
        model_resolved=True,
        presupuesto=8000000.0,
        has_conversation=True,
    )
    result = score_lead(signals)
    # 20 base + 10 presupuesto + 1.16 ticket = 31.16
    assert result.commercial == 31.16
    assert "PRESUPUESTO_COMPATIBLE" in _reason_codes(result)

    pobre = score_lead(
        LeadSignals(
            lead_id="T-presupuesto-bajo",
            list_price=7290000.0,
            model_resolved=True,
            presupuesto=3000000.0,
            has_conversation=True,
        )
    )
    assert pobre.commercial == 11.16
    assert "PRESUPUESTO_INSUFICIENTE" in _reason_codes(pobre)


def test_modelo_ambiguo_sin_precio_no_resta():
    signals = LeadSignals(
        lead_id="T-ambiguo",
        list_price=None,
        model_resolved=False,
        has_conversation=True,
    )
    result = score_lead(signals)
    assert result.commercial == 20.0  # solo base, sin negativos
    assert "precio_modelo" in result.missing
    assert all(r.contribution >= 0 for r in result.reasons if r.dimension == "commercial")


def test_datos_incompletos_marcan_faltantes_en_calidad():
    result = score_lead(LeadSignals(lead_id="T-incompleto"))
    assert result.quality == 0
    assert {"telefono", "modelo", "email", "ciudad", "fecha_registro_confiable"} <= set(
        result.missing
    )


def test_sin_senales_ia_no_se_penaliza():
    signals = LeadSignals(
        lead_id="T-sin-ia",
        list_price=9990000.0,
        model_resolved=True,
        has_conversation=False,
        phone_valid=True,
        email_present=True,
        city_present=True,
        registration_trustworthy=True,
        estado_gestion="Sin gestión",
        days_since_registration=5,
        has_first_contact=False,
    )
    result = score_lead(signals)
    # 20 base + 2.51 ticket, sin negativos por ausencia de IA
    assert result.commercial == 22.51
    assert "intencion_compra" not in result.missing
    assert "presupuesto" not in result.missing
    assert result.quality == 30 + 25 + 20 + 15 + 10
    # Urgencia: 70 base + 20 antigüedad, piso 90 por Sin gestión +48h
    assert result.urgency == 90
    assert result.urgency_band == "Hoy"


def test_lead_con_objecion_resta_sin_descalificar():
    signals = LeadSignals(
        lead_id="T-objecion",
        intencion_compra="alta",
        objecion="precio",
        has_conversation=True,
    )
    result = score_lead(signals)
    # 20 + 30 - 10 = 40
    assert result.commercial == 40.0
    assert result.band == "Baja"
    assert "OBJECION_PRECIO" in _reason_codes(result)

    leve = score_lead(
        LeadSignals(lead_id="T-objecion-leve", objecion="tiempo", has_conversation=True)
    )
    assert leve.commercial == 17.0


def test_combinacion_limite_respeta_tope():
    signals = LeadSignals(
        lead_id="T-tope",
        list_price=24900000.0,
        model_resolved=True,
        intencion_compra="alta",
        solicitud_cita=True,
        solicitud_cotizacion=True,
        presupuesto=25000000.0,
        cuota_inicial=6000000.0,
        forma_pago="financiacion",
        objecion="tiempo",
        has_conversation=True,
    )
    result = score_lead(signals)
    # 20+30+20+10+10+5+5+10-3 = 107 → tope 100
    assert result.commercial == 100.0
    assert result.urgency == 100
    assert result.queue == 100.0


def test_score_es_reproducible():
    signals = LeadSignals(
        lead_id="T-repro",
        list_price=7990000.0,
        model_resolved=True,
        intencion_compra="media",
        solicitud_cotizacion=True,
        estado_gestion="No contesta",
        registration_trustworthy=True,
        days_since_registration=2,
        has_first_contact=False,
        has_conversation=True,
    )
    assert score_lead(signals).to_dict() == score_lead(signals).to_dict()


def test_score_respeta_version_y_params_configurados():
    custom = dict(SCORE_V1_PARAMS, score_version="v1-test", base_gestionable=50)
    result = score_lead(LeadSignals(lead_id="T-version"), params=custom)
    assert result.score_version == "v1-test"
    assert result.commercial == 50.0
    assert result.params["base_gestionable"] == 50

    sin_ticket = score_lead(
        LeadSignals(lead_id="T-sin-ticket", list_price=24900000.0, model_resolved=True),
        params=dict(SCORE_V1_PARAMS, ticket_weight=0),
    )
    assert sin_ticket.commercial == 20.0
    assert "TICKET_REGLA_NEGOCIO" in _reason_codes(sin_ticket)


def test_queue_ordena_de_mayor_a_menor_prioridad():
    alto = score_lead(
        LeadSignals(lead_id="A", intencion_compra="alta", has_conversation=True)
    )
    medio = score_lead(
        LeadSignals(lead_id="B", intencion_compra="media", has_conversation=True)
    )
    bajo = score_lead(LeadSignals(lead_id="C"))
    assert alto.queue > medio.queue > bajo.queue


def test_calidad_es_dimension_separada_del_comercial():
    con_datos = LeadSignals(
        lead_id="D1",
        intencion_compra="media",
        has_conversation=True,
        phone_valid=True,
        email_present=True,
        city_present=True,
        model_resolved=True,
        registration_trustworthy=True,
    )
    sin_datos = LeadSignals(
        lead_id="D2", intencion_compra="media", has_conversation=True
    )
    r1, r2 = score_lead(con_datos), score_lead(sin_datos)
    assert r1.commercial == r2.commercial  # calidad no infla lo comercial
    assert r1.quality == 100
    assert r2.quality == 0


def test_fecha_no_confiable_no_alimenta_urgencia():
    result = score_lead(
        LeadSignals(
            lead_id="T-fecha",
            estado_gestion="Sin gestión",
            registration_trustworthy=False,
            days_since_registration=None,
        )
    )
    assert result.urgency == 70  # solo base de estado
    assert "FECHA_NO_CONFIABLE" in _reason_codes(result)
    assert result.urgency_band == "24 h"


def test_descartado_no_genera_urgencia():
    result = score_lead(LeadSignals(lead_id="T-desc", estado_gestion="Descartado"))
    assert result.urgency == 0
    assert result.urgency_band == "Semana"


def test_integracion_minima_con_modelo_lead_score():
    result = score_lead(LeadSignals(lead_id="T-map", intencion_compra="alta"))
    kwargs = to_lead_score_kwargs(result, "T-map", run_id=7)
    assert kwargs["lead_id"] == "T-map"
    assert kwargs["run_id"] == 7
    assert kwargs["score_version"] == SCORE_VERSION
    assert kwargs["priority_score"] == result.commercial
    assert kwargs["urgency_score"] == result.urgency
    assert kwargs["queue_score"] == result.queue
    assert kwargs["band"] == result.band
    assert isinstance(kwargs["reasons"], list)
    assert kwargs["params_snapshot"]["score_version"] == SCORE_VERSION
