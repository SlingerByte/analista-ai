from __future__ import annotations

from collections import defaultdict


def empresa_pv_map(asesores: list[dict[str, str]]) -> dict[str, list[str]]:
    mapping: dict[str, set] = defaultdict(set)
    for row in asesores:
        mapping[row["empresa_id"]].add(row["punto_venta_id"])
    return {key: sorted(value) for key, value in sorted(mapping.items())}


def _pv_to_empresa(mapping: dict[str, list[str]]) -> dict[str, str]:
    result = {}
    for empresa, pvs in mapping.items():
        for pv in pvs:
            result[pv] = empresa
    return result


def validate_references(rows, mapping, label):
    pv_empresa = _pv_to_empresa(mapping)
    unknown_pv = []
    inconsistent = []
    for row in rows:
        pv = row.get("punto_venta_id", "")
        empresa = row.get("empresa_id", "")
        if pv not in pv_empresa:
            unknown_pv.append({"lead_id": row.get("lead_id", row.get("asesor_id", "?")), "punto_venta_id": pv})
        elif empresa and pv_empresa[pv] != empresa:
            inconsistent.append(
                {
                    "id": row.get("lead_id", row.get("asesor_id", "?")),
                    "punto_venta_id": pv,
                    "empresa_id": empresa,
                    "empresa_esperada": pv_empresa[pv],
                }
            )
    return {
        "dataset": label,
        "pv_desconocido": unknown_pv,
        "empresa_inconsistente_con_pv": inconsistent,
    }


def analyze_relations(data: dict) -> dict:
    leads = data["leads"]
    catalogo = data["catalogo"]
    asesores = data["asesores"]
    historico = data["historico"]

    mapping = empresa_pv_map(asesores)
    valid_pvs = {pv for pvs in mapping.values() for pv in pvs}

    catalog_pvs = set()
    bad_catalog_pvs = []
    for row in catalogo:
        pvs = row["puntos_venta_disponibles"].split("|")
        catalog_pvs.update(pvs)
        for pv in pvs:
            if pv not in valid_pvs:
                bad_catalog_pvs.append({"sku": row["sku"], "punto_venta_id": pv})

    lead_ids = {row["lead_id"] for row in leads}
    hist_ids = {row["lead_id"] for row in historico}

    return {
        "empresa_pv": mapping,
        "validaciones": [
            validate_references(leads, mapping, "leads"),
            validate_references(historico, mapping, "historico_cierres"),
            validate_references(asesores, mapping, "asesores"),
        ],
        "catalogo_pv_invalidos": bad_catalog_pvs,
        "punto_venta_validos": sorted(valid_pvs),
        "catalogo_pv_sin_asesor": sorted(catalog_pvs - valid_pvs),
        "leads_historico": {
            "leads_distintos": len(lead_ids),
            "historico_distintos": len(hist_ids),
            "interseccion": len(lead_ids & hist_ids),
            "prefijos": {
                "leads": sorted({lid.split("-")[0] for lid in lead_ids}),
                "historico": sorted({lid.split("-")[0] for lid in hist_ids}),
            },
        },
    }
