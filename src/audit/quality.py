from __future__ import annotations

from collections import Counter, defaultdict

from .config import (
    CLASS_AUTO,
    CLASS_HUMAN,
    CLASS_KEEP,
    CLASS_RULE,
)
from .normalization import (
    CIUDAD_ALIASES,
    classify_date,
    is_valid_email,
    normalize_canal,
    normalize_ciudad,
    normalize_email,
    normalize_estado,
    normalize_key,
    normalize_model_text,
    normalize_phone,
    phone_digits,
    phone_format,
)


def _issue(issue_id, dataset, campo, tipo, clasificacion, n, descripcion, ejemplo=None):
    return {
        "id": issue_id,
        "dataset": dataset,
        "campo": campo,
        "tipo": tipo,
        "clasificacion": clasificacion,
        "n_afectados": n,
        "descripcion": descripcion,
        "ejemplo": ejemplo,
    }


def duplicate_rows(rows: list[dict[str, str]]) -> dict:
    seen: dict[tuple, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        seen[tuple(row.items())].append(index)
    duplicates = {key: idx for key, idx in seen.items() if len(idx) > 1}
    return {
        "grupos_duplicados": len(duplicates),
        "filas_duplicadas_extra": sum(len(idx) - 1 for idx in duplicates.values()),
        "ejemplos": [key[0][1] for key in list(duplicates)[:5]],
    }


def duplicate_keys(rows: list[dict[str, str]], key: str) -> dict:
    counter = Counter(row[key] for row in rows)
    duplicated = {k: v for k, v in counter.items() if v > 1}
    return {"valores_duplicados": len(duplicated), "detalle": dict(sorted(duplicated.items()))}


def canal_variants(rows: list[dict[str, str]]) -> dict:
    raw = Counter((row["canal"] or "").strip() for row in rows)
    normalized = Counter(normalize_canal(row["canal"]) for row in rows)
    canonical = {"WhatsApp", "Meta Ads", "Formulario Web"}
    return {
        "valores_crudos": dict(sorted(raw.items())),
        "valores_normalizados": {str(k): v for k, v in normalized.items()},
        "variantes_redundantes": sum(v for k, v in raw.items() if k and k not in canonical),
        "vacios": raw.get("", 0),
    }


def name_analysis(rows: list[dict[str, str]]) -> dict:
    raw = [row["nombre_cliente"] for row in rows]
    whitespace = sum(1 for value in raw if value != value.strip() or "  " in value)
    upper = sum(1 for value in raw if value.strip() and value.strip() == value.strip().upper())
    groups: dict[tuple, list[str]] = defaultdict(list)
    for row in rows:
        key = (normalize_key(row["nombre_cliente"]), normalize_phone(row["telefono"]))
        groups[key].append(row["lead_id"])
    repeated = {f"{name}|{phone}": ids for (name, phone), ids in groups.items() if len(ids) > 1}
    return {
        "con_espacios_extra": whitespace,
        "en_mayusculas": upper,
        "clientes_repetidos_nombre_telefono": len(repeated),
        "ejemplos": dict(list(repeated.items())[:5]),
    }


def estado_variants(rows: list[dict[str, str]]) -> dict:
    raw = Counter((row["estado_gestion"] or "").strip() for row in rows)
    normalized = Counter(normalize_estado(row["estado_gestion"]) for row in rows)
    return {
        "valores_crudos": dict(sorted(raw.items())),
        "valores_normalizados": {str(k): v for k, v in normalized.items()},
        "variantes_redundantes": len(raw) - len(normalized),
    }


def estado_contacto_consistency(rows: list[dict[str, str]]) -> dict:
    result = {}
    for row in rows:
        estado = normalize_estado(row["estado_gestion"])
        has_contact = bool((row["fecha_primer_contacto"] or "").strip())
        key = (estado, has_contact)
        result[key] = result.get(key, 0) + 1
    pending = sum(
        count
        for (estado, has_contact), count in result.items()
        if estado != "Sin gestión" and not has_contact
    )
    return {"matriz": {f"{k[0]}|contacto={k[1]}": v for k, v in sorted(result.items())}, "gestionados_sin_fecha": pending}


def city_variants(rows: list[dict[str, str]]) -> dict:
    raw = Counter((row["ciudad"] or "").strip() for row in rows if (row["ciudad"] or "").strip())
    normalized = Counter(normalize_ciudad(row["ciudad"]) for row in rows if (row["ciudad"] or "").strip())
    return {
        "valores_crudos": dict(sorted(raw.items())),
        "valores_normalizados": dict(sorted(normalized.items())),
        "vacios": sum(1 for row in rows if not (row["ciudad"] or "").strip()),
        "variantes_agrupadas": len(raw) - len(normalized),
        "alias_aplicados": CIUDAD_ALIASES,
    }


def phone_analysis(rows: list[dict[str, str]]) -> dict:
    raw_values = [row["telefono"] for row in rows]
    formats = Counter(phone_format(value) for value in raw_values)
    digits = [phone_digits(value) for value in raw_values]
    invalid = [(row, d) for row, d in zip(rows, digits) if not (10 <= len(d) <= 12)]
    by_number: dict[str, set] = defaultdict(set)
    for row, d in zip(rows, digits):
        canonical = normalize_phone(row["telefono"])
        by_number[canonical].add(row["lead_id"])
    shared = {k: sorted(v) for k, v in by_number.items() if len(v) > 1}
    return {
        "formatos": dict(formats),
        "invalidos": [{"lead_id": row["lead_id"], "telefono": row["telefono"]} for row, _ in invalid],
        "telefonos_compartidos": len(shared),
        "leads_involucrados": sum(len(v) for v in shared.values()),
        "max_leads_por_telefono": max((len(v) for v in shared.values()), default=0),
        "ejemplos_duplicados": dict(list(shared.items())[:5]),
    }


def email_analysis(rows: list[dict[str, str]]) -> dict:
    present = [(row["lead_id"], (row["email"] or "").strip()) for row in rows if (row["email"] or "").strip()]
    invalid = [(lead, email) for lead, email in present if not is_valid_email(email)]
    counter = Counter(normalize_email(email) for _, email in present)
    duplicates = {k: v for k, v in counter.items() if v > 1}
    return {
        "presentes": len(present),
        "faltantes": len(rows) - len(present),
        "pct_faltantes": round(100 * (len(rows) - len(present)) / len(rows), 2),
        "invalidos": invalid,
        "duplicados": dict(sorted(duplicates.items())),
    }


def date_analysis(rows: list[dict[str, str]], columns: list[str]) -> dict:
    result = {}
    for column in columns:
        checks = [classify_date(row[column]) for row in rows]
        formats = Counter(check["format"] for check in checks)
        ambiguous_slash = sum(1 for check in checks if check["format"] == "DD/MM/YYYY vs MM/DD/YYYY")
        ambiguous_dash = sum(
            1 for check in checks if check["ambiguous"] and check["format"] == "DD-MM-YYYY"
        )
        unknown_values = sorted({row[column].strip() for row, check in zip(rows, checks) if check["format"] == "desconocido"})
        result[column] = {
            "formatos": dict(sorted(formats.items())),
            "ambiguos_slash": ambiguous_slash,
            "ambiguos_dash_convencion": ambiguous_dash,
            "desconocidos": len(unknown_values),
            "valores_desconocidos": unknown_values[:10],
        }
    return result


def chronological_inconsistencies(rows: list[dict[str, str]]) -> dict:
    before = 0
    unparsed = 0
    skipped_ambiguous = 0
    examples = []
    for row in rows:
        if not (row["fecha_primer_contacto"] or "").strip():
            continue
        start = classify_date(row["fecha_registro"])
        contact = classify_date(row["fecha_primer_contacto"])
        if start["parsed"] is None or contact["parsed"] is None:
            unparsed += 1
            continue
        if start["ambiguous"] or contact["ambiguous"]:
            skipped_ambiguous += 1
            continue
        if contact["parsed"] < start["parsed"]:
            before += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "lead_id": row["lead_id"],
                        "fecha_registro": row["fecha_registro"],
                        "fecha_primer_contacto": row["fecha_primer_contacto"],
                    }
                )
    return {
        "contacto_antes_de_registro": before,
        "entre_ellos_ambiguos": skipped_ambiguous,
        "no_comparables_por_formato": unparsed,
        "ejemplos": examples,
    }


def catalog_map(catalogo: list[dict[str, str]]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    for row in catalogo:
        full = normalize_model_text(f"{row['marca']} {row['linea']}")
        line = normalize_model_text(row["linea"])
        brand = normalize_model_text(row["marca"])
        mapping[full].append(row["sku"])
        mapping[line].append(row["sku"])
        mapping[f"{brand} {line}"].append(row["sku"])
    return mapping


def model_analysis(leads: list[dict[str, str]], catalogo: list[dict[str, str]]) -> dict:
    mapping = catalog_map(catalogo)
    brands = {normalize_model_text(row["marca"]) for row in catalogo}
    types = Counter()
    details = defaultdict(list)
    unresolved = []
    for row in leads:
        text = (row["modelo_interes_texto"] or "").strip()
        if not text:
            types["vacio"] += 1
            continue
        canonical = normalize_model_text(text)
        skus = set(mapping.get(canonical, []))
        if skus:
            if len(skus) == 1:
                types["directo_unico"] += 1
            else:
                types["directo_ambiguo"] += 1
            details[text].append({"sku": sorted(skus), "tipo": "directo"})
        elif canonical in brands:
            types["solo_marca"] += 1
            details[text].append({"sku": [], "tipo": "solo_marca"})
        else:
            prefix = [
                (key, sku)
                for key, skus_ in mapping.items()
                for sku in skus_
                if key.startswith(canonical) or canonical.startswith(key)
            ]
            prefix_skus = {sku for _, sku in prefix}
            if len(prefix_skus) == 1:
                types["prefijo_unico"] += 1
                details[text].append({"sku": sorted(prefix_skus), "tipo": "prefijo_unico"})
            elif len(prefix_skus) > 1:
                types["prefijo_ambiguo"] += 1
                details[text].append({"sku": sorted(prefix_skus), "tipo": "prefijo_ambiguo"})
            else:
                types["sin_match"] += 1
                unresolved.append(text)
                details[text].append({"sku": [], "tipo": "sin_match"})
    return {
        "conteo_tipos": dict(types),
        "valores_crudos_unicos": len(details),
        "sin_match": sorted(set(unresolved)),
        "detalle": {text: info[0] for text, info in sorted(details.items())},
    }


def missing_values(rows: list[dict[str, str]]) -> dict:
    resultado = {}
    for column in rows[0].keys():
        missing = sum(1 for row in rows if not str(row.get(column, "")).strip())
        if missing:
            resultado[column] = {"n": missing, "pct": round(100 * missing / len(rows), 2)}
    return resultado


def analyze_quality(data: dict) -> dict:
    leads = data["leads"]
    catalogo = data["catalogo"]

    dup_rows = duplicate_rows(leads)
    dup_ids = duplicate_keys(leads, "lead_id")
    canal = canal_variants(leads)
    estado = estado_variants(leads)
    contacto = estado_contacto_consistency(leads)
    ciudades = city_variants(leads)
    nombres = name_analysis(leads)
    phones = phone_analysis(leads)
    emails = email_analysis(leads)
    fechas = date_analysis(leads, ["fecha_registro", "fecha_primer_contacto"])
    cronologia = chronological_inconsistencies(leads)
    modelos = model_analysis(leads, catalogo)
    faltantes = missing_values(leads)

    issues = [
        _issue(
            "Q01", "leads", "lead_id", "duplicados", CLASS_AUTO, dup_rows["filas_duplicadas_extra"],
            "Filas completamente duplicadas (mismo lead_id y mismos valores).",
            dup_rows["ejemplos"],
        ),
        _issue(
            "Q02", "leads", "canal", "formatos", CLASS_AUTO, canal["variantes_redundantes"],
            "El mismo canal aparece con mayúsculas/minúsculas distintas.",
            canal["valores_crudos"],
        ),
        _issue(
            "Q03", "leads", "estado_gestion", "formatos", CLASS_AUTO, sum(
                v
                for k, v in estado["valores_crudos"].items()
                if k not in estado["valores_normalizados"]
            ),
            "El mismo estado aparece con mayúsculas/minúsculas distintas.",
            estado["valores_crudos"],
        ),
        _issue(
            "Q04", "leads", "fecha_registro / fecha_primer_contacto", "fechas", CLASS_RULE,
            fechas["fecha_registro"]["ambiguos_slash"],
            "Fechas con barra realmente ambiguas entre DD/MM/YYYY y MM/DD/YYYY (día y mes <= 12); no se pueden resolver sin regla.",
            {
                "fecha_registro": fechas["fecha_registro"]["ambiguos_slash"],
                "fecha_primer_contacto": fechas["fecha_primer_contacto"]["ambiguos_slash"],
            },
        ),
        _issue(
            "Q05", "leads", "fecha_registro", "fechas", CLASS_AUTO,
            sum(fechas["fecha_registro"]["formatos"].get(f, 0) for f in ("ISO_T", "ISO_SPACE", "DD-MM-YYYY")),
            "Formatos de fecha mezclados (ISO-T, ISO con espacio, DD-MM-YYYY).",
            fechas["fecha_registro"]["formatos"],
        ),
        _issue(
            "Q06", "leads", "fecha_primer_contacto", "integridad", CLASS_HUMAN,
            cronologia["contacto_antes_de_registro"],
            "fecha_primer_contacto anterior a fecha_registro.",
            cronologia["ejemplos"],
        ),
        _issue(
            "Q07", "leads", "telefono", "formatos", CLASS_AUTO,
            sum(v for k, v in phones["formatos"].items() if k not in ("plano_10", "vacio")),
            "Teléfonos con espacios, guiones, paréntesis y prefijo 57/+57.",
            phones["formatos"],
        ),
        _issue(
            "Q08", "leads", "telefono", "valores_invalidos", CLASS_HUMAN,
            len(phones["invalidos"]),
            "Teléfonos con longitud distinta a 10-12 dígitos.",
            phones["invalidos"],
        ),
        _issue(
            "Q09", "leads", "telefono", "duplicados", CLASS_RULE,
            phones["telefonos_compartidos"],
            f"Teléfono normalizado compartido por más de un lead_id ({phones['leads_involucrados']} leads involucrados).",
            phones["ejemplos_duplicados"],
        ),
        _issue(
            "Q10", "leads", "email", "valores_faltantes", CLASS_RULE,
            emails["faltantes"],
            f"Email faltante en {emails['pct_faltantes']}% de los leads.",
        ),
        _issue(
            "Q11", "leads", "email", "duplicados", CLASS_HUMAN, len(emails["duplicados"]),
            "Email repetido entre leads distintos.",
            emails["duplicados"],
        ),
        _issue(
            "Q12", "leads", "ciudad", "formatos", CLASS_AUTO, ciudades["variantes_agrupadas"],
            "Ciudades con variantes de mayúsculas/acentos y abreviaturas (Bogotá D.C., Sta Marta, B/quilla...).",
            ciudades["valores_crudos"],
        ),
        _issue(
            "Q13", "leads", "ciudad", "valores_faltantes", CLASS_RULE, ciudades["vacios"],
            "Ciudad faltante.",
        ),
        _issue(
            "Q14", "leads", "modelo_interes_texto", "formatos", CLASS_RULE,
            modelos["conteo_tipos"].get("solo_marca", 0) + modelos["conteo_tipos"].get("prefijo_ambiguo", 0),
            "Modelo escrito solo como marca o de forma parcial/ambigua (no permite elegir un SKU único).",
            {k: v for k, v in modelos["detalle"].items() if v["tipo"] in ("solo_marca", "prefijo_ambiguo")},
        ),
        _issue(
            "Q15", "leads", "modelo_interes_texto", "formatos", CLASS_AUTO,
            modelos["conteo_tipos"].get("directo_unico", 0) + modelos["conteo_tipos"].get("prefijo_unico", 0),
            "Modelo con typos de marca (Bajai, Hnda, Heroo, Suzuky), formato A.K.T y sufijo de año; normalizables a un SKU.",
        ),
        _issue(
            "Q16", "leads", "modelo_interes_texto", "valores_faltantes", CLASS_RULE,
            modelos["conteo_tipos"].get("vacio", 0),
            "Modelo de interés faltante.",
        ),
        _issue(
            "Q17", "leads", "campania", "valores_faltantes", CLASS_KEEP, faltantes.get("campania", {}).get("n", 0),
            "Campaña no informada; se conserva como ausencia.",
        ),
        _issue(
            "Q18", "leads", "fecha_primer_contacto", "integridad", CLASS_RULE,
            contacto["gestionados_sin_fecha"],
            "Leads con estado de gestión distinto de 'Sin gestión' pero sin fecha_primer_contacto.",
            contacto["matriz"],
        ),
        _issue(
            "Q19", "leads", "fecha_registro / fecha_primer_contacto", "fechas",
            CLASS_HUMAN if (fechas["fecha_registro"]["desconocidos"] + fechas["fecha_primer_contacto"]["desconocidos"]) else CLASS_KEEP,
            fechas["fecha_registro"]["desconocidos"] + fechas["fecha_primer_contacto"]["desconocidos"],
            "Valores de fecha con formato no reconocible (p. ej. día imposible).",
            fechas["fecha_registro"]["valores_desconocidos"] + fechas["fecha_primer_contacto"]["valores_desconocidos"],
        ),
        _issue(
            "Q20", "leads", "canal", "valores_faltantes", CLASS_RULE, canal["vacios"],
            "Canal vacío: no se puede asignar a una fuente de adquisición.",
        ),
        _issue(
            "Q21", "leads", "nombre_cliente", "formatos", CLASS_AUTO, nombres["con_espacios_extra"],
            "Nombres con espacios sobrantes y mezcla de mayúsculas/minúsculas.",
            {"en_mayusculas": nombres["en_mayusculas"]},
        ),
        _issue(
            "Q22", "leads", "nombre_cliente / telefono", "duplicados", CLASS_RULE,
            nombres["clientes_repetidos_nombre_telefono"],
            "Posibles clientes repetidos (nombre normalizado + teléfono normalizado iguales).",
            nombres["ejemplos"],
        ),
    ]

    return {
        "duplicados_filas": dup_rows,
        "duplicados_lead_id": dup_ids,
        "canal": canal,
        "estado_gestion": estado,
        "estado_contacto": contacto,
        "ciudades": ciudades,
        "nombres": nombres,
        "telefonos": phones,
        "emails": emails,
        "fechas": fechas,
        "cronologia": cronologia,
        "modelos": modelos,
        "faltantes": faltantes,
        "issues": issues,
    }
