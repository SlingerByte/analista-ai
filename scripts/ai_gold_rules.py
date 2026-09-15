"""Tooling de evaluación (NO producción): reglas de anotación del gold set.

Deriva un *candidato* de ground truth a partir de la conversación original
(mensajes del cliente), siguiendo las reglas documentadas en
``docs/ai-extraction-benchmark.md``. No usa ninguna salida de modelo.

Las anotaciones se marcan con ``gold_source`` (``rule`` o ``human``) y
``gold_confidence``. Un revisor humano puede sobreescribir registros completos
vía ``scripts/gold_overrides.json``.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.ai.validation import amounts_in_text
from app.text import normalize_key

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

EXTRACTION_FIELDS = [
    "model_interes",
    "intencion_compra",
    "presupuesto",
    "cuota_inicial",
    "forma_pago",
    "objecion",
    "solicitud_cita",
    "solicitud_cotizacion",
]

HIGH_INTENT = [
    "me sirve", "esa si me sirve", "la quiero", "quiero esa", "la voy a comprar",
    "la separo", "separo la moto", "separemela", "separela", "ya voy",
    "voy en camino", "hagale pues", "como hago para sacarla", "me la llevo",
    "la compro", "ya tengo la plata", "voy esta tarde", "voy saliendo",
    "voy para alla", "voy hoy", "la necesito ya",
]
MEDIUM_INTENT = [
    "me interesa", "estoy interesado", "me gusta", "quisiera", "estoy buscando",
    "la necesito", "necesito la moto", "quiero una moto", "estoy pensando en comprar",
    "hablo con mi esposa",
]
LOW_INTENT = [
    "solo mirando", "solo estaba mirando", "estoy mirando", "estaba viendo una usada",
    "usada mas barata", "estoy averiguando", "averiguando", "mirando precios",
    "no tengo inicial", "no tengo con que dar la inicial", "mas economico",
    "otra marca", "estoy comparando", "comparando", "estoy pensando",
    "lo estoy pensando", "pensarlo", "aun no", "sin inicial", "por curiosidad",
    "curiosidad", "se me sale", "por encima de lo que tengo", "es mucho",
]
INFORMATIVE = [
    "informacion", "cuanto vale", "cuanto cuesta", "horario", "ubicacion",
    "donde estan", "donde queda", "que precio tiene", "preguntar",
]
FINANCIACION_CUES = ["financiada", "financiado", "financiacion", "a credito", "credito", "de credito"]
CONTADO_CUES = ["de contado", "al contado", "contado", "efectivo"]
INITIAL_CUES = ["inicial", "entrada", "enganche"]
INITIAL_NONE_CUES = ["no tengo inicial", "sin inicial", "no tengo para la inicial",
                     "no tengo con que dar la inicial", "no tengo plata", "no tengo con que"]
OBJ_PRICE = ["algo mas economico", "mas economico", "usada mas barata", "usadas mas baratas",
             "muy caro", "muy cara", "costosa", "costoso", "muy alta", "no me alcanza",
             "fuera de presupuesto", "se me sale del presupuesto", "se me sale",
             "descuento", "mejor precio", "interes esta caro", "esta caro"]
OBJ_QUOTA = ["cuota muy alta", "cuota alta", "la cuota me queda alta", "cuota esta muy alta"]
OBJ_FINANCING = ["tasa muy alta", "interes muy alto", "intereses muy altos", "esa tasa",
                 "la inicial esta muy alta", "inicial esta muy alta"]
OBJ_AVAILABILITY = ["no tienen usadas", "no hay usadas", "no manejan", "no hay disponible",
                    "no tienen disponible", "disponibilidad"]
OBJ_OTHER = ["otra marca", "otro modelo", "prefiero otra", "me gusta otra", "otra opcion",
             "otra por menos plata", "me estan ofreciendo otra", "datacredito", "reportado",
             "reporte viejo", "centrales de riesgo"]
CITA_CUES = ["a que hora los puedo visitar", "puedo pasar", "puedo ir", "los visito",
             "visitar", "pasar por", "ir al concesionario", "ir a la sucursal",
             "agendar", "cita", "voy manana", "manana voy", "voy esta tarde",
             "voy para alla", "voy saliendo", "me acerco", "hasta que hora abren",
             "vamos para", "voy hoy"]
QUOTE_CUES = ["cotiz", "mandela", "mandemela", "enviela", "enviemela", "pasame el precio",
              "me la cotiza", "cotizame"]
ACCEPTANCE_CUES = ["me sirve", "esa si", "esa me", "hagale", "listo", "de acuerdo",
                   "perfecto", "si por favor", "separemela"]


def _load_lines() -> dict[str, str]:
    rows = list(csv.DictReader((DATA_DIR / "catalogo_motos.csv").read_text(encoding="utf-8-sig").splitlines()))
    mapping: dict[str, str] = {}
    for row in rows:
        key = normalize_key(row["linea"])
        if key:
            mapping[key] = f"{row['marca'].strip()} {row['linea'].strip()}"
    return mapping


CATALOG_LINES = _load_lines()


def client_messages(conversation: dict) -> list[str]:
    return [normalize_key(m.get("texto")) for m in conversation["mensajes"] if m.get("emisor") == "cliente"]


def advisor_messages(conversation: dict) -> list[str]:
    return [normalize_key(m.get("texto")) for m in conversation["mensajes"] if m.get("emisor") == "asesor"]


def _has(text: str, cues: list[str]) -> bool:
    return any(c in text for c in cues)


def _last_cue(text: str, cues: list[str]) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for cue in cues:
        pos = text.rfind(cue)
        if pos >= 0 and (best is None or pos > best[0]):
            best = (pos, cue)
    return best


def _find_amount(text: str) -> float | None:
    amounts = amounts_in_text(text)
    return max(amounts) if amounts else None


def _model(conversation: dict) -> tuple[str | None, str, str]:
    cm = client_messages(conversation)
    ordered: list[tuple[int, str]] = []
    for idx, text in enumerate(cm):
        for key, canonical in CATALOG_LINES.items():
            if key in text:
                ordered.append((idx, canonical))
    if not ordered:
        return None, "high", "no model mentioned by client"
    distinct: list[str] = []
    for _, canonical in ordered:
        if canonical not in distinct:
            distinct.append(canonical)
    if len(distinct) == 1:
        return distinct[0], "high", "single model mentioned by client"
    last = distinct[-1]
    last_first_idx = next(i for i, c in ordered if c == last)
    after = " || ".join(cm[last_first_idx:])
    if _has(after, ACCEPTANCE_CUES) or _has(after, HIGH_INTENT) or _has(after, MEDIUM_INTENT):
        return last, "medium", f"model switch, client confirms '{last}'"
    return None, "low", f"multiple models without confirmation: {distinct}"


def _intent(conversation: dict) -> tuple[str | None, str, str]:
    text = " || ".join(client_messages(conversation))
    candidates: list[tuple[int, str, str]] = []
    for level, cues in (("alta", HIGH_INTENT), ("media", MEDIUM_INTENT), ("baja", LOW_INTENT)):
        hit = _last_cue(text, cues)
        if hit is not None:
            candidates.append((hit[0], level, hit[1]))
    if candidates:
        _, level, cue = max(candidates, key=lambda item: item[0])
        return level, "high", f"cue: {cue!r}"
    info = _last_cue(text, INFORMATIVE)
    if info is not None:
        return "informativa", "medium", f"cue: {info[1]!r}"
    return None, "medium", "no explicit client intent cue"


def _payment_form(conversation: dict) -> tuple[str | None, str, str]:
    text = " || ".join(client_messages(conversation))
    fin = _last_cue(text, FINANCIACION_CUES)
    contado = _last_cue(text, CONTADO_CUES)
    if fin is not None and (contado is None or fin[0] > contado[0]):
        return "financiacion", "high", f"client cue: {fin[1]!r}"
    if contado is not None:
        return "contado", "high", f"client cue: {contado[1]!r}"
    return None, "high", "client did not declare payment form"


def _down_payment(conversation: dict) -> tuple[float | None, str, str]:
    text = " || ".join(client_messages(conversation))
    if _has(text, INITIAL_NONE_CUES):
        return 0.0, "high", "client explicitly states no down payment"
    if _has(text, INITIAL_CUES):
        amount = _find_amount(text)
        if amount is not None:
            return amount, "high", "client states initial amount"
        return None, "medium", "initial mentioned without amount (ambiguous)"
    return None, "high", "no down payment mentioned by client"


def _budget(conversation: dict) -> tuple[float | None, str, str]:
    text = " || ".join(client_messages(conversation))
    if "para la inicial" in text or "de inicial" in text or "para inicial" in text:
        return None, "high", "amount refers to down payment, not budget"
    for cue in ("tengo hasta", "presupuesto", "puedo pagar", "cuento con", "tengo pensado gastar"):
        if cue in text:
            amount = _find_amount(text)
            if amount is not None:
                return amount, "medium", f"budget cue: {cue!r}"
    return None, "high", "no total budget stated by client"


def _objection(conversation: dict) -> tuple[str | None, str, str]:
    text = " || ".join(client_messages(conversation))
    checks = [
        ("financiacion", OBJ_FINANCING),
        ("cuota", OBJ_QUOTA),
        ("precio", OBJ_PRICE),
        ("disponibilidad", OBJ_AVAILABILITY),
        ("otra", OBJ_OTHER),
    ]
    found: list[tuple[int, str, str]] = []
    for value, cues in checks:
        hit = _last_cue(text, cues)
        if hit is not None:
            found.append((hit[0], value, hit[1]))
    if not found:
        return None, "high", "no objection expressed by client"
    _, value, cue = min(found, key=lambda item: item[0])
    confidence = "high"
    note = f"client cue: {cue!r}"
    if value == "disponibilidad":
        confidence = "low"
        note += " (availability question, possibly not a barrier)"
    return value, confidence, note


def _cita(conversation: dict) -> tuple[bool | None, str, str]:
    text = " || ".join(client_messages(conversation))
    cue = _last_cue(text, CITA_CUES)
    if cue is not None:
        return True, "high", f"client cue: {cue[1]!r}"
    return None, "high", "no client appointment request"


def _quote(conversation: dict) -> tuple[bool | None, str, str]:
    text = " || ".join(client_messages(conversation))
    cue = _last_cue(text, QUOTE_CUES)
    if cue is not None:
        return True, "high", f"client cue: {cue[1]!r}"
    return None, "high", "client did not request a quote"


def annotate(conversation: dict) -> dict:
    model, mc, mn = _model(conversation)
    intent, ic, inote = _intent(conversation)
    budget, bc, bnote = _budget(conversation)
    down, dc, dnote = _down_payment(conversation)
    form, fc, fnote = _payment_form(conversation)
    obj, oc, onote = _objection(conversation)
    cita, cc, cnote = _cita(conversation)
    quote, qc, qnote = _quote(conversation)

    confidences = [mc, ic, bc, dc, fc, oc, cc, qc]
    overall = "low" if "low" in confidences else ("medium" if "medium" in confidences else "high")

    return {
        "conversation_id": conversation["conversation_id"],
        "lead_id": conversation.get("lead_id"),
        "channel": conversation.get("channel"),
        "message_count": len(conversation["mensajes"]),
        "gold_model_interes": model,
        "gold_intencion_compra": intent,
        "gold_presupuesto": budget,
        "gold_cuota_inicial": down,
        "gold_forma_pago": form,
        "gold_objecion": obj,
        "gold_solicitud_cita": cita,
        "gold_solicitud_cotizacion": quote,
        "gold_notes": {
            "model_interes": mn, "intencion_compra": inote, "presupuesto": bnote,
            "cuota_inicial": dnote, "forma_pago": fnote, "objecion": onote,
            "solicitud_cita": cnote, "solicitud_cotizacion": qnote,
        },
        "gold_confidence": overall,
        "gold_source": "rule",
    }
