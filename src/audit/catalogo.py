from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from .config import CLASS_KEEP
from .normalization import normalize_canal, normalize_model_text


def analyze_catalogo(data: dict) -> dict:
    catalogo = data["catalogo"]
    leads = data["leads"]
    historico = data["historico"]

    line_keys = {normalize_model_text(f"{row['marca']} {row['linea']}"): row for row in catalogo}
    line_only = {normalize_model_text(row["linea"]): row for row in catalogo}

    precios = [int(row["precio_lista"]) for row in catalogo]
    unidades = [int(row["unidades_disponibles"]) for row in catalogo]

    historico_mismatch = []
    historico_unknown = []
    for row in historico:
        key = normalize_model_text(row["modelo_cotizado"])
        catalog_row = line_keys.get(key) or line_only.get(key)
        if catalog_row is None:
            historico_unknown.append(row["modelo_cotizado"])
        elif int(row["precio_lista"]) != int(catalog_row["precio_lista"]):
            historico_mismatch.append(
                {
                    "lead_id": row["lead_id"],
                    "modelo": row["modelo_cotizado"],
                    "precio_historico": int(row["precio_lista"]),
                    "precio_catalogo": int(catalog_row["precio_lista"]),
                }
            )

    leads_unknown = []
    for row in leads:
        text = (row["modelo_interes_texto"] or "").strip()
        if not text:
            continue
        key = normalize_model_text(text)
        if key in line_keys or key in line_only:
            continue
        brand_tokens = key.split()
        if len(brand_tokens) == 1 and any(
            normalize_model_text(c["marca"]) == brand_tokens[0] for c in catalogo
        ):
            continue
        prefix = [
            candidate
            for candidate in list(line_keys) + list(line_only)
            if candidate.startswith(key) or key.startswith(candidate)
        ]
        if not prefix:
            leads_unknown.append(text)

    return {
        "registros": len(catalogo),
        "marcas": dict(Counter(row["marca"] for row in catalogo)),
        "segmentos": dict(Counter(row["segmento"] for row in catalogo)),
        "lineas": [row["linea"] for row in catalogo],
        "lineas_unicas": len({row["linea"] for row in catalogo}),
        "cilindrajes": dict(sorted(Counter(row["cilindraje"] for row in catalogo).items())),
        "precios": {
            "min": min(precios),
            "max": max(precios),
            "media": round(statistics.mean(precios)),
        },
        "unidades": {
            "total": sum(unidades),
            "min": min(unidades),
            "max": max(unidades),
        },
        "cobertura_puntos_venta": {
            "min": min(len(row["puntos_venta_disponibles"].split("|")) for row in catalogo),
            "max": max(len(row["puntos_venta_disponibles"].split("|")) for row in catalogo),
        },
        "historico_modelos_sin_catalogo": sorted(set(historico_unknown)),
        "historico_precio_inconsistente": historico_mismatch,
        "leads_modelos_sin_match": sorted(set(leads_unknown)),
        "canal_historico_consistente": sorted({normalize_canal(row["canal"]) for row in historico}),
        "issues": [
            {
                "id": "K01",
                "dataset": "catalogo_motos / historico_cierres",
                "campo": "modelo_cotizado / marca+linea",
                "tipo": "consistencia",
                "clasificacion": CLASS_KEEP,
                "n_afectados": len(historico_unknown),
                "descripcion": "No se detectaron modelos de histórico fuera del catálogo (marca + línea).",
                "ejemplo": sorted(set(historico_unknown))[:5],
            },
            {
                "id": "K02",
                "dataset": "catalogo_motos / historico_cierres",
                "campo": "precio_lista",
                "tipo": "consistencia",
                "clasificacion": CLASS_KEEP,
                "n_afectados": len(historico_mismatch),
                "descripcion": "No se detectaron precios del histórico distintos del precio de catálogo.",
                "ejemplo": historico_mismatch[:5],
            },
        ],
    }
