from __future__ import annotations

from dataclasses import dataclass, field

from app.scoring.signals import LeadSignals

SCORE_VERSION = "v1"

# Parámetros versionados de la fórmula. Cada fila de `lead_scores` guarda una
# copia (params_snapshot) para poder reconstruir el cálculo. Poner un peso en
# 0 desactiva esa regla sin cambiar código (p. ej. ticket_weight = 0 si el
# negocio decide que el ticket no debe ordenar).
SCORE_V1_PARAMS: dict = {
    "score_version": SCORE_VERSION,
    "base_gestionable": 20,
    "intencion_points": {"alta": 30, "media": 15, "baja": 5, "informativa": 0},
    "cita_points": 20,
    "cotizacion_points": 10,
    "presupuesto_compatible_points": 10,
    "presupuesto_insuficiente_points": -10,
    "cuota_suficiente_points": 5,
    "cuota_suficiente_ratio": 0.20,
    "forma_pago_points": 5,
    "objecion_points": {
        "precio": -10,
        "cuota": -8,
        "financiacion": -8,
        "disponibilidad": -5,
        "tiempo": -3,
        "modelo": -5,
        "ubicacion": -5,
        "otra": -5,
    },
    "ticket_weight": 1.0,
    "ticket_max_points": 10,
    # Rango observado del catálogo (data/catalogo_motos.csv, 24 SKU).
    "catalog_min_price": 4990000.0,
    "catalog_max_price": 24900000.0,
    "quality_points": {
        "phone": 30,
        "model": 25,
        "email": 20,
        "city": 15,
        "registration_date": 10,
    },
    "estado_base": {
        "Sin gestión": 70,
        "No contesta": 60,
        "Cotización enviada": 55,
        "Contactado": 40,
        "En proceso": 30,
        "Descartado": 0,
    },
    "estado_desconocido_base": 30,
    "antiguedad_points": {"mas_48h": 20, "24_48h": 10},
    "cita_urgency_override": 100,
    "sin_gestion_mas_48h_min": 90,
    "queue_commercial_weight": 0.7,
    "queue_urgency_weight": 0.3,
    "band_alta_desde": 70,
    "band_media_desde": 45,
    "urgency_hoy_desde": 75,
    "urgency_24h_desde": 45,
}


@dataclass(frozen=True)
class Reason:
    code: str
    dimension: str  # "commercial" | "quality" | "urgency"
    text: str
    contribution: float


@dataclass(frozen=True)
class ScoreResult:
    lead_id: str
    score_version: str
    commercial: float
    quality: float
    urgency: float
    urgency_band: str
    queue: float
    band: str
    reasons: tuple = ()
    missing: tuple = ()
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "score_version": self.score_version,
            "commercial": self.commercial,
            "quality": self.quality,
            "urgency": self.urgency,
            "urgency_band": self.urgency_band,
            "queue": self.queue,
            "band": self.band,
            "reasons": [r.__dict__ for r in self.reasons],
            "missing": list(self.missing),
            "params": dict(self.params),
        }


def _norm_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip().lower()
    return token or None


def _commercial(signals: LeadSignals, params: dict, reasons: list, missing: list) -> float:
    total = 0.0

    base = params["base_gestionable"]
    total += base
    reasons.append(
        Reason("BASE_GESTIONABLE", "commercial",
               "Lead registrado y gestionable; la falta de conversación no resta.", base)
    )

    intencion = _norm_token(signals.intencion_compra)
    points_map = params["intencion_points"]
    if intencion in points_map:
        points = points_map[intencion]
        total += points
        reasons.append(
            Reason(f"INTENCION_{intencion.upper()}", "commercial",
                   f"Intención de compra declarada por el cliente: {intencion}.", points)
        )
    elif signals.has_conversation:
        missing.append("intencion_compra")

    if signals.solicitud_cita is True:
        points = params["cita_points"]
        total += points
        reasons.append(
            Reason("CLIENTE_PIDIO_CITA", "commercial",
                   "El cliente solicitó cita/visita.", points)
        )
    elif signals.solicitud_cita is None and signals.has_conversation:
        missing.append("solicitud_cita")

    if signals.solicitud_cotizacion is True:
        points = params["cotizacion_points"]
        total += points
        reasons.append(
            Reason("CLIENTE_PIDIO_COTIZACION", "commercial",
                   "El cliente solicitó cotización.", points)
        )
    elif signals.solicitud_cotizacion is None and signals.has_conversation:
        missing.append("solicitud_cotizacion")

    if signals.presupuesto is not None and signals.list_price is not None:
        if signals.presupuesto >= signals.list_price:
            points = params["presupuesto_compatible_points"]
            total += points
            reasons.append(
                Reason("PRESUPUESTO_COMPATIBLE", "commercial",
                       "El presupuesto declarado cubre el precio del modelo.", points)
            )
        else:
            points = params["presupuesto_insuficiente_points"]
            total += points
            reasons.append(
                Reason("PRESUPUESTO_INSUFICIENTE", "commercial",
                       "El presupuesto declarado no cubre el precio del modelo.", points)
            )
    elif signals.has_conversation:
        if signals.presupuesto is None:
            missing.append("presupuesto")
        if signals.list_price is None:
            missing.append("precio_modelo")

    if (
        signals.cuota_inicial is not None
        and signals.list_price is not None
        and signals.list_price > 0
        and signals.cuota_inicial >= params["cuota_suficiente_ratio"] * signals.list_price
    ):
        points = params["cuota_suficiente_points"]
        total += points
        reasons.append(
            Reason("CUOTA_SUFICIENTE", "commercial",
                   "La cuota inicial declarada muestra capacidad de pago (≥20% del precio).",
                   points)
        )
    elif signals.has_conversation and signals.cuota_inicial is None:
        missing.append("cuota_inicial")

    if _norm_token(signals.forma_pago) is not None:
        points = params["forma_pago_points"]
        total += points
        reasons.append(
            Reason("FORMA_PAGO_DECLARADA", "commercial",
                   "El cliente declaró cómo quiere pagar.", points)
        )
    elif signals.has_conversation:
        missing.append("forma_pago")

    objecion = _norm_token(signals.objecion)
    if objecion is not None:
        points = params["objecion_points"].get(objecion, -5)
        total += points
        reasons.append(
            Reason(f"OBJECION_{objecion.upper()}", "commercial",
                   f"El cliente manifestó una objeción: {objecion}.", points)
        )
    elif signals.has_conversation:
        missing.append("objecion")

    if signals.list_price is not None:
        span = params["catalog_max_price"] - params["catalog_min_price"]
        position = 0.0
        if span > 0:
            position = (signals.list_price - params["catalog_min_price"]) / span
            position = min(1.0, max(0.0, position))
        points = round(
            params["ticket_max_points"] * position * params["ticket_weight"], 2
        )
        total += points
        reasons.append(
            Reason("TICKET_REGLA_NEGOCIO", "commercial",
                   "Regla de negocio configurable: a mayor precio de lista, más puntos "
                   "(peso 0 la desactiva).", points)
        )
    else:
        missing.append("precio_modelo")

    return min(100.0, max(0.0, round(total, 2)))


def _quality(signals: LeadSignals, params: dict, reasons: list, missing: list) -> float:
    total = 0.0
    points_map = params["quality_points"]

    if signals.phone_valid:
        total += points_map["phone"]
        reasons.append(Reason("TELEFONO_VALIDO", "quality", "Teléfono contactable.", points_map["phone"]))
    else:
        missing.append("telefono")

    if signals.model_resolved:
        total += points_map["model"]
        reasons.append(Reason("MODELO_RESUELTO", "quality", "Modelo identificado en catálogo.", points_map["model"]))
    else:
        missing.append("modelo")

    if signals.email_present:
        total += points_map["email"]
        reasons.append(Reason("EMAIL_PRESENTE", "quality", "Email registrado.", points_map["email"]))
    else:
        missing.append("email")

    if signals.city_present:
        total += points_map["city"]
        reasons.append(Reason("CIUDAD_PRESENTE", "quality", "Ciudad registrada.", points_map["city"]))
    else:
        missing.append("ciudad")

    if signals.registration_trustworthy:
        total += points_map["registration_date"]
        reasons.append(
            Reason("FECHA_CONFIABLE", "quality", "Fecha de registro confiable.", points_map["registration_date"])
        )
    else:
        missing.append("fecha_registro_confiable")

    return min(100.0, max(0.0, round(total, 2)))


def _urgency(signals: LeadSignals, params: dict, reasons: list, missing: list) -> float:
    estado_base = params["estado_base"]
    if signals.estado_gestion in estado_base:
        total = float(estado_base[signals.estado_gestion])
        reasons.append(
            Reason("ESTADO_OPERATIVO", "urgency",
                   f"Estado de gestión: {signals.estado_gestion}.", total)
        )
    else:
        total = float(params["estado_desconocido_base"])
        reasons.append(
            Reason("ESTADO_DESCONOCIDO", "urgency",
                   "Estado de gestión ausente o no reconocido; urgencia neutra.", total)
        )
        missing.append("estado_gestion")

    if signals.solicitud_cita is True:
        total = float(params["cita_urgency_override"])
        reasons.append(
            Reason("URGENCIA_HOY_CITA", "urgency",
                   "El cliente pidió cita: atender hoy.", 0.0)
        )
        return total

    if signals.registration_trustworthy and signals.days_since_registration is not None:
        if not signals.has_first_contact:
            if signals.days_since_registration >= 2:
                points = params["antiguedad_points"]["mas_48h"]
                total += points
                reasons.append(
                    Reason("SIN_CONTACTO_MAS_48H", "urgency",
                           "Registrado hace más de 48 h sin primer contacto.", points)
                )
            elif signals.days_since_registration >= 1:
                points = params["antiguedad_points"]["24_48h"]
                total += points
                reasons.append(
                    Reason("SIN_CONTACTO_24_48H", "urgency",
                           "Registrado hace 24–48 h sin primer contacto.", points)
                )
        if (
            signals.estado_gestion == "Sin gestión"
            and signals.days_since_registration >= 2
        ):
            floor = float(params["sin_gestion_mas_48h_min"])
            if total < floor:
                reasons.append(
                    Reason("SIN_GESTION_MAS_48H", "urgency",
                           "Sin gestión por más de 48 h: piso de urgencia.", 0.0)
                )
                total = floor
    else:
        reasons.append(
            Reason("FECHA_NO_CONFIABLE", "urgency",
                   "Fecha de registro ambigua o ausente: la antigüedad no alimenta "
                   "la urgencia.", 0.0)
        )

    return min(100.0, max(0.0, round(total, 2)))


def score_lead(signals: LeadSignals, params: dict | None = None) -> ScoreResult:
    """Calcula el score v1. Función pura: mismos datos → mismo score."""
    active = dict(SCORE_V1_PARAMS if params is None else params)
    reasons: list[Reason] = []
    missing: list[str] = []

    commercial = _commercial(signals, active, reasons, missing)
    quality = _quality(signals, active, reasons, missing)
    urgency = _urgency(signals, active, reasons, missing)

    queue = round(
        active["queue_commercial_weight"] * commercial
        + active["queue_urgency_weight"] * urgency,
        2,
    )

    if commercial >= active["band_alta_desde"]:
        band = "Alta"
    elif commercial >= active["band_media_desde"]:
        band = "Media"
    else:
        band = "Baja"

    if urgency >= active["urgency_hoy_desde"]:
        urgency_band = "Hoy"
    elif urgency >= active["urgency_24h_desde"]:
        urgency_band = "24 h"
    else:
        urgency_band = "Semana"

    seen: set[str] = set()
    ordered_missing = tuple(m for m in missing if not (m in seen or seen.add(m)))

    return ScoreResult(
        lead_id=signals.lead_id,
        score_version=str(active.get("score_version", SCORE_VERSION)),
        commercial=commercial,
        quality=quality,
        urgency=urgency,
        urgency_band=urgency_band,
        queue=queue,
        band=band,
        reasons=tuple(reasons),
        missing=ordered_missing,
        params=dict(active),
    )


def to_lead_score_kwargs(
    result: ScoreResult, lead_id: str, run_id: int | None = None
) -> dict:
    """Mapeo mínimo a las columnas de `LeadScore`. Sin cambios de modelo."""
    return {
        "lead_id": lead_id,
        "run_id": run_id,
        "score_version": result.score_version,
        "priority_score": result.commercial,
        "urgency_score": result.urgency,
        "queue_score": result.queue,
        "band": result.band,
        "reasons": [r.__dict__ for r in result.reasons],
        "params_snapshot": result.params,
        "is_current": True,
    }
