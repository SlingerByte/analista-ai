from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from .config import CLASS_KEEP, CLASS_RULE
from .normalization import normalize_canal


def _numeric(rows, column):
    values = []
    for row in rows:
        text = (row.get(column) or "").strip()
        if not text:
            continue
        try:
            values.append(float(text))
        except ValueError:
            continue
    return values


def _stats(values):
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "media": round(statistics.mean(values), 2),
        "mediana": statistics.median(values),
    }


def analyze_historico(data: dict) -> dict:
    historico = data["historico"]

    desenlace = Counter(row["desenlace"] for row in historico)
    por_empresa = Counter(row["empresa_id"] for row in historico)
    por_canal = Counter(normalize_canal(row["canal"]) for row in historico)
    por_empresa_desenlace = Counter((row["empresa_id"], row["desenlace"]) for row in historico)
    por_canal_desenlace = Counter((normalize_canal(row["canal"]), row["desenlace"]) for row in historico)

    faltantes = {}
    for column in historico[0].keys():
        missing = sum(1 for row in historico if not (row.get(column) or "").strip())
        if missing:
            faltantes[column] = {
                "n": missing,
                "pct": round(100 * missing / len(historico), 2),
            }

    contactos_por_desenlace = defaultdict(list)
    horas_por_desenlace = defaultdict(list)
    for row in historico:
        contactos_por_desenlace[row["desenlace"]].append(float(row["numero_contactos"]))
        text = (row["horas_al_primer_contacto"] or "").strip()
        if text:
            horas_por_desenlace[row["desenlace"]].append(float(text))

    sin_gestion = [row for row in historico if row["desenlace"] == "Sin gestión"]
    cero_contactos = [row for row in historico if float(row["numero_contactos"]) == 0]
    nulos_horas = [row for row in historico if not (row["horas_al_primer_contacto"] or "").strip()]
    sin_gestion_ids = {row["lead_id"] for row in sin_gestion}
    cero_ids = {row["lead_id"] for row in cero_contactos}
    nulos_ids = {row["lead_id"] for row in nulos_horas}

    leakage = {
        "horas_al_primer_contacto": {
            "nulos": len(nulos_horas),
            "nulos_que_son_sin_gestion": len(nulos_ids & sin_gestion_ids),
            "nulos_fuera_de_sin_gestion": len(nulos_ids - sin_gestion_ids),
            "clasificacion": CLASS_RULE,
            "motivo": "El nulo coincide exactamente con 'Sin gestión': la variable se registra después de gestionar y delata el desenlace.",
        },
        "numero_contactos": {
            "iguales_a_cero": len(cero_contactos),
            "ceros_que_son_sin_gestion": len(cero_ids & sin_gestion_ids),
            "ceros_fuera_de_sin_gestion": len(cero_ids - sin_gestion_ids),
            "clasificacion": CLASS_RULE,
            "motivo": "El valor 0 coincide exactamente con 'Sin gestión'; se comporta como consecuencia del desenlace.",
        },
        "desenlace": {
            "clasificacion": "variable_objetivo",
            "motivo": "Es la etiqueta a predecir; nunca debe entrar como predictor.",
        },
        "precio_lista": {
            "clasificacion": CLASS_KEEP,
            "motivo": "Disponible en catálogo antes de la gestión; no hay evidencia de fuga, aunque su utilidad es limitada.",
        },
        "manifesto_cuota_inicial": {
            "clasificacion": CLASS_RULE,
            "motivo": "Declarado por el cliente durante la gestión; debe confirmarse si estaba disponible al momento de priorizar.",
        },
        "forma_pago_declarada": {
            "clasificacion": CLASS_RULE,
            "motivo": "Declarado por el cliente durante la gestión; debe confirmarse su momento de captura.",
        },
        "pidio_cita": {
            "clasificacion": CLASS_RULE,
            "motivo": "Comportamiento previo a la decisión, pero podría registrarse después; requiere confirmación.",
        },
    }

    posible_priorizacion = [
        "canal",
        "empresa_id",
        "punto_venta_id",
        "modelo_cotizado",
        "precio_lista",
        "fecha_registro",
    ]

    issues = [
        {
            "id": "H01",
            "dataset": "historico_cierres",
            "campo": "horas_al_primer_contacto",
            "tipo": "data_leakage",
            "clasificacion": CLASS_RULE,
            "n_afectados": len(nulos_horas),
            "descripcion": "Nulo exactamente cuando desenlace='Sin gestión'. Usar o imputar esta variable fuga la etiqueta.",
            "ejemplo": sorted(nulos_ids)[:5],
        },
        {
            "id": "H02",
            "dataset": "historico_cierres",
            "campo": "numero_contactos",
            "tipo": "data_leakage",
            "clasificacion": CLASS_RULE,
            "n_afectados": len(cero_contactos),
            "descripcion": "Valor 0 exactamente cuando desenlace='Sin gestión'. Se comporta como consecuencia del desenlace.",
            "ejemplo": sorted(cero_ids)[:5],
        },
        {
            "id": "H03",
            "dataset": "historico_cierres",
            "campo": "desenlace",
            "tipo": "desbalance_clases",
            "clasificacion": CLASS_KEEP,
            "n_afectados": desenlace.get("Cerrado", 0),
            "descripcion": f"Clase minoritaria 'Cerrado' = {desenlace.get('Cerrado', 0)} de {len(historico)} ({round(100*desenlace.get('Cerrado',0)/len(historico),2)}%).",
            "ejemplo": dict(desenlace),
        },
    ]

    return {
        "registros": len(historico),
        "desenlace": dict(desenlace),
        "por_empresa": dict(por_empresa),
        "por_canal": dict(por_canal),
        "empresa_desenlace": {f"{k[0]}|{k[1]}": v for k, v in sorted(por_empresa_desenlace.items())},
        "canal_desenlace": {f"{k[0]}|{k[1]}": v for k, v in sorted(por_canal_desenlace.items())},
        "faltantes": faltantes,
        "numericas": {
            "precio_lista": _stats(_numeric(historico, "precio_lista")),
            "numero_contactos": _stats(_numeric(historico, "numero_contactos")),
            "horas_al_primer_contacto": _stats(_numeric(historico, "horas_al_primer_contacto")),
        },
        "contactos_por_desenlace": {
            k: _stats(v) for k, v in sorted(contactos_por_desenlace.items())
        },
        "horas_por_desenlace": {k: _stats(v) for k, v in sorted(horas_por_desenlace.items())},
        "leakage": leakage,
        "posible_priorizacion": posible_priorizacion,
        "issues": issues,
    }
