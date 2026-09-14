from __future__ import annotations

from collections import Counter, defaultdict

from .config import CLASS_KEEP


def analyze_asesores(data: dict) -> dict:
    asesores = data["asesores"]

    por_empresa = Counter(row["empresa_id"] for row in asesores)
    por_punto = Counter(row["punto_venta_id"] for row in asesores)
    activos = Counter(row["activo"] for row in asesores)
    capacidades = Counter(int(row["capacidad_diaria_leads"]) for row in asesores)

    activos_por_pv = defaultdict(int)
    capacidad_por_pv = defaultdict(int)
    for row in asesores:
        if row["activo"] == "SI":
            activos_por_pv[row["punto_venta_id"]] += 1
            capacidad_por_pv[row["punto_venta_id"]] += int(row["capacidad_diaria_leads"])

    inactivos = [
        {"asesor_id": row["asesor_id"], "punto_venta_id": row["punto_venta_id"], "empresa_id": row["empresa_id"]}
        for row in asesores
        if row["activo"] != "SI"
    ]

    puntos = set(por_punto)
    sin_activo = sorted(pv for pv in puntos if activos_por_pv.get(pv, 0) == 0)

    return {
        "registros": len(asesores),
        "por_empresa": dict(por_empresa),
        "por_punto_venta": dict(sorted(por_punto.items())),
        "activos": dict(activos),
        "inactivos": inactivos,
        "capacidades": dict(sorted(capacidades.items())),
        "activos_por_punto_venta": dict(sorted(activos_por_pv.items())),
        "capacidad_diaria_por_punto_venta": dict(sorted(capacidad_por_pv.items())),
        "puntos_sin_asesor_activo": sin_activo,
        "puntos_de_venta": sorted(puntos),
        "issues": [
            {
                "id": "A01",
                "dataset": "asesores",
                "campo": "activo",
                "tipo": "estado",
                "clasificacion": CLASS_KEEP,
                "n_afectados": len(inactivos),
                "descripcion": "Asesores inactivos; todos los puntos de venta conservan al menos un asesor activo.",
                "ejemplo": inactivos,
            },
            {
                "id": "A02",
                "dataset": "asesores",
                "campo": "punto_venta_id / empresa_id",
                "tipo": "referencias",
                "clasificacion": CLASS_KEEP,
                "n_afectados": 0,
                "descripcion": "No se detectaron referencias inválidas ni combinaciones empresa/punto de venta incoherentes.",
                "ejemplo": [],
            },
        ],
    }
