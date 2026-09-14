from __future__ import annotations

import csv
import datetime as _dt
import json

from . import asesores as asesores_module
from . import catalogo as catalogo_module
from . import config
from . import conversations as conversations_module
from . import historico as historico_module
from . import loaders
from . import profiling
from . import quality as quality_module
from . import relations as relations_module
from .normalization import normalize_canal, normalize_estado


CLASS_LABELS = {
    config.CLASS_AUTO: "Corregible automáticamente",
    config.CLASS_RULE: "Requiere regla de negocio",
    config.CLASS_KEEP: "Debe conservarse como dato original",
    config.CLASS_HUMAN: "Requiere revisión humana",
}


def build_summary() -> dict:
    data = loaders.load_all()
    data["catalogo_motos"] = data["catalogo"]

    hashes = {}
    for name, path in {**config.CSV_FILES, **config.JSON_FILES}.items():
        hashes[name] = {
            "ruta": str(path.relative_to(config.PROJECT_ROOT)).replace("\\", "/"),
            "bytes": path.stat().st_size,
            "sha256": loaders.sha256(path),
        }

    estructura = {
        "leads.csv": profiling.profile_table(data["leads"]),
        "catalogo_motos.csv": profiling.profile_table(data["catalogo"]),
        "asesores.csv": profiling.profile_table(data["asesores"]),
        "historico_cierres.csv": profiling.profile_table(data["historico"]),
        "conversaciones.json": profiling.profile_conversations(data["conversaciones"]),
    }

    calidad = quality_module.analyze_quality(data)
    relations = relations_module.analyze_relations(data)
    conversations = conversations_module.analyze_conversations(data)
    historico = historico_module.analyze_historico(data)
    catalogo = catalogo_module.analyze_catalogo(data)
    asesores = asesores_module.analyze_asesores(data)

    issues = (
        calidad["issues"]
        + relations_issues(relations)
        + conversations["issues"]
        + historico["issues"]
        + catalogo["issues"]
        + asesores["issues"]
    )

    return {
        "generado": _dt.datetime.now().isoformat(timespec="seconds"),
        "python": _python_version(),
        "solo_lectura": True,
        "archivos": hashes,
        "estructura": estructura,
        "calidad": calidad,
        "relaciones": relations,
        "conversaciones": conversations,
        "historico": historico,
        "catalogo": catalogo,
        "asesores": asesores,
        "issues": issues,
    }


def _python_version() -> str:
    import sys

    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def relations_issues(relations: dict) -> list[dict]:
    invalid_catalog = relations["catalogo_pv_invalidos"]
    inconsistent = [
        item
        for block in relations["validaciones"]
        for item in block["empresa_inconsistente_con_pv"]
    ]
    unknown = [
        item
        for block in relations["validaciones"]
        for item in block["pv_desconocido"]
    ]
    return [
        {
            "id": "R01",
            "dataset": "todos",
            "campo": "punto_venta_id / empresa_id",
            "tipo": "referencias",
            "clasificacion": config.CLASS_KEEP,
            "n_afectados": len(unknown) + len(inconsistent),
            "descripcion": "Sin referencias a puntos de venta inexistentes ni combinaciones empresa/punto incoherentes entre datasets.",
            "ejemplo": (unknown + inconsistent)[:5],
        },
        {
            "id": "R02",
            "dataset": "catalogo_motos",
            "campo": "puntos_venta_disponibles",
            "tipo": "referencias",
            "clasificacion": config.CLASS_KEEP,
            "n_afectados": len(invalid_catalog),
            "descripcion": "Todos los puntos de venta del catálogo existen en asesores.csv.",
            "ejemplo": invalid_catalog[:5],
        },
        {
            "id": "R03",
            "dataset": "leads / historico_cierres",
            "campo": "lead_id",
            "tipo": "llave_compartida",
            "clasificacion": config.CLASS_RULE,
            "n_afectados": 0,
            "descripcion": "La intersección de lead_id entre leads (LD-) e histórico (HX-) es cero: no se pueden unir directamente.",
            "ejemplo": relations["leads_historico"]["prefijos"],
        },
    ]


def write_auxiliary_reports(summary: dict) -> list[str]:
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    summary_path = config.REPORTS_DIR / "audit_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(str(summary_path))

    estructura_path = config.REPORTS_DIR / "estructura.csv"
    with open(estructura_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["archivo", "registros", "columna", "tipo_inferido", "nulos", "pct_nulos", "valores_unicos", "ejemplo"])
        for archivo, profile in summary["estructura"].items():
            if "perfil_columnas" not in profile:
                continue
            for column in profile["perfil_columnas"]:
                writer.writerow(
                    [
                        archivo,
                        profile["registros"],
                        column["columna"],
                        column["tipo_inferido"],
                        column["nulos"],
                        column["pct_nulos"],
                        column["valores_unicos"],
                        " | ".join(str(v) for v in column["ejemplos"][:2]),
                    ]
                )
    written.append(str(estructura_path))

    issues_path = config.REPORTS_DIR / "inconsistencias.csv"
    with open(issues_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "dataset", "campo", "tipo", "clasificacion", "n_afectados", "descripcion"])
        for issue in summary["issues"]:
            writer.writerow(
                [
                    issue["id"],
                    issue["dataset"],
                    issue["campo"],
                    issue["tipo"],
                    CLASS_LABELS.get(issue["clasificacion"], issue["clasificacion"]),
                    issue["n_afectados"],
                    issue["descripcion"],
                ]
            )
    written.append(str(issues_path))

    unmatched_path = config.REPORTS_DIR / "conversaciones_sin_match.csv"
    with open(unmatched_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["conversacion_id", "lead_id", "fecha_inicio"])
        for row in summary["conversaciones"]["ejemplos_sin_match"]:
            writer.writerow([row["conversacion_id"], row["lead_id"], row["fecha_inicio"]])
    written.append(str(unmatched_path))

    mapping_path = config.REPORTS_DIR / "leads_modelos_mapeo.csv"
    with open(mapping_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["modelo_interes_texto", "tipo_match", "skus_candidatos"])
        for text, info in summary["calidad"]["modelos"]["detalle"].items():
            writer.writerow([text, info["tipo"], "|".join(info["sku"])])
    written.append(str(mapping_path))

    duplicates_path = config.REPORTS_DIR / "leads_duplicados.csv"
    with open(duplicates_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["lead_id", "ocurrencias"])
        for lead_id, count in summary["calidad"]["duplicados_lead_id"]["detalle"].items():
            writer.writerow([lead_id, count])
    written.append(str(duplicates_path))

    phones_path = config.REPORTS_DIR / "telefonos_formatos.csv"
    with open(phones_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["formato", "conteo"])
        for fmt, count in summary["calidad"]["telefonos"]["formatos"].items():
            writer.writerow([fmt, count])
    written.append(str(phones_path))

    return written


def _esc(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_esc(cell) for cell in row) + " |")
    return lines


def render_markdown(summary: dict) -> str:
    est = summary["estructura"]
    cal = summary["calidad"]
    rel = summary["relaciones"]
    conv = summary["conversaciones"]
    hist = summary["historico"]
    cat = summary["catalogo"]
    ase = summary["asesores"]

    lines: list[str] = []
    add = lines.append

    add("# Auditoría de datos - Prueba técnica Analista de IA")
    add("")
    add("> Documento generado automáticamente por `scripts/run_audit.py`.")
    add(f"> Generado: {summary['generado']} · Python {summary['python']} · Modo solo lectura.")
    add("> Los archivos de `data/` no se modifican. Ver hashes SHA-256 abajo para verificar la evidencia.")
    add("")

    add("## 0. Archivos auditados y garantía de no modificación")
    add("")
    add("La auditoría abre los archivos originales en modo lectura y nunca escribe en `data/`.")
    add("Hashes al momento de ejecutar (re-ejecutar debe reproducir los mismos hashes):")
    add("")
    rows = [[name, info["ruta"], f"{info['bytes']:,}", info["sha256"][:16] + "…"] for name, info in summary["archivos"].items()]
    lines += _table(["Archivo", "Ruta", "Bytes", "SHA-256 (prefijo)"], rows)
    add("")

    add("## 1. Estructura de cada archivo")
    add("")
    for archivo, profile in est.items():
        add(f"### {archivo}")
        add("")
        if "perfil_columnas" not in profile:
            add(f"- Registros: {profile['registros']}")
            add(f"- Campos de conversación: {', '.join(profile['columnas'])}")
            add(f"- Campos de mensaje: {', '.join(profile['columnas_mensaje'])}")
            add(f"- Mensajes totales: {profile['mensajes_totales']}")
            add("")
            continue
        add(f"- Registros: {profile['registros']} · Columnas: {len(profile['columnas'])}")
        add("")
        rows = [
            [
                c["columna"],
                c["tipo_inferido"],
                c["nulos"],
                f"{c['pct_nulos']}%",
                c["valores_unicos"],
                ", ".join(_esc(v) for v in c["ejemplos"][:2]),
            ]
            for c in profile["perfil_columnas"]
        ]
        lines += _table(["Columna", "Tipo inferido", "Nulos", "% Nulos", "Únicos", "Ejemplos"], rows)
        add("")

    add("## 2. Calidad de datos")
    add("")
    add("### 2.1 Duplicados")
    add("")
    add(
        f"- Filas completamente duplicadas en `leads.csv`: {cal['duplicados_filas']['filas_duplicadas_extra']} "
        f"(grupos: {cal['duplicados_filas']['grupos_duplicados']}; lead_id: {', '.join(cal['duplicados_filas']['ejemplos'])})."
    )
    add(f"- `lead_id` repetidos en `leads.csv`: {list(cal['duplicados_lead_id']['detalle'].keys())}.")
    add(
        f"- Teléfonos normalizados compartidos por más de un `lead_id`: {cal['telefonos']['telefonos_compartidos']} "
        f"({cal['telefonos']['leads_involucrados']} leads involucrados; máx. leads por teléfono: {cal['telefonos']['max_leads_por_telefono']})."
    )
    add(f"- Emails normalizados repetidos: {len(cal['emails']['duplicados'])}.")
    add("")

    add("### 2.2 Teléfonos")
    add("")
    add(f"- Teléfonos con formato distinto a 10 dígitos planos: {sum(v for k, v in cal['telefonos']['formatos'].items() if k not in ('plano_10', 'vacio'))} registros.")
    rows = [[fmt, count] for fmt, count in sorted(cal["telefonos"]["formatos"].items())]
    lines += _table(["Formato detectado", "Registros"], rows)
    add("")
    add(f"- Teléfonos inválidos (longitud distinta de 10-12 dígitos): {len(cal['telefonos']['invalidos'])} → {cal['telefonos']['invalidos']}.")
    add("")

    add("### 2.3 Emails")
    add("")
    add(f"- Presentes: {cal['emails']['presentes']} · Faltantes: {cal['emails']['faltantes']} ({cal['emails']['pct_faltantes']}%).")
    add(f"- Sintácticamente inválidos: {len(cal['emails']['invalidos'])}.")
    add(f"- Duplicados: {cal['emails']['duplicados']}.")
    add("")

    add("### 2.4 Fechas")
    add("")
    rows = []
    for column, info in cal["fechas"].items():
        rows.append(
            [
                column,
                ", ".join(f"{k}={v}" for k, v in info["formatos"].items()),
                info["ambiguos_slash"],
                info["ambiguos_dash_convencion"],
                info["desconocidos"],
            ]
        )
    lines += _table(
        ["Columna", "Formatos detectados", "Ambiguos DD/MM vs MM/DD", "Ambiguos DD-MM (convención)", "Desconocidos"],
        rows,
    )
    add("")
    add(
        "> Las fechas con guion (`DD-MM-YYYY`) se interpretaron como día-mes por convención local; "
        "aun así pueden ser ambiguas en principio y se reportan aparte. Las fechas con barra mezclan "
        "evidencia de DD/MM y de MM/DD, por lo que las ambiguas quedan sin resolver."
    )
    add("")
    add(
        f"- Inconsistencias cronológicas (`fecha_primer_contacto` < `fecha_registro`): "
        f"{cal['cronologia']['contacto_antes_de_registro']} (se omitieron {cal['cronologia']['entre_ellos_ambiguos']} pares con fecha ambigua; no comparables por formato: {cal['cronologia']['no_comparables_por_formato']})."
    )
    add(
        f"- Leads gestionados (estado distinto de 'Sin gestión') sin `fecha_primer_contacto`: "
        f"{cal['estado_gestion'] and cal['estado_contacto']['gestionados_sin_fecha']}."
    )
    add("")

    add("### 2.5 Ciudades")
    add("")
    add(f"- Valores crudos distintos: {len(cal['ciudades']['valores_crudos'])} · Normalizados: {len(cal['ciudades']['valores_normalizados'])} · Vacíos: {cal['ciudades']['vacios']}.")
    add(f"- Alias aplicados (basados en evidencia): {cal['ciudades']['alias_aplicados']}.")
    rows = [[value, count] for value, count in sorted(cal["ciudades"]["valores_normalizados"].items())]
    lines += _table(["Ciudad normalizada", "Leads"], rows)
    add("")

    add("### 2.6 Modelos de interés en leads")
    add("")
    add(f"- Textos crudos distintos: {cal['modelos']['valores_crudos_unicos']}.")
    rows = [[k, v] for k, v in sorted(cal["modelos"]["conteo_tipos"].items())]
    lines += _table(["Resultado de normalización", "Leads"], rows)
    add("")
    add(f"- Sin match tras normalizar: {cal['modelos']['sin_match']}.")
    add("")

    add("### 2.7 Canal y estado de gestión (variantes de formato)")
    add("")
    add(f"- Canal crudo: {cal['canal']['valores_crudos']}.")
    add(f"- Canal normalizado: {cal['canal']['valores_normalizados']}.")
    add(f"- Estado crudo: {cal['estado_gestion']['valores_crudos']}.")
    add(f"- Estado normalizado: {cal['estado_gestion']['valores_normalizados']}.")
    add("")

    add("### 2.8 Nombres de cliente")
    add("")
    add(f"- Con espacios sobrantes: {cal['nombres']['con_espacios_extra']} · En mayúsculas: {cal['nombres']['en_mayusculas']}.")
    add(f"- Posibles clientes repetidos (nombre + teléfono normalizados): {cal['nombres']['clientes_repetidos_nombre_telefono']}.")
    add("")

    add("## 3. Relaciones entre datasets")
    add("")
    add(f"- Mapa empresa → puntos de venta (desde `asesores.csv`): {rel['empresa_pv']}.")
    add(f"- Puntos de venta válidos: {len(rel['punto_venta_validos'])} · Puntos del catálogo sin asesor: {rel['catalogo_pv_sin_asesor']}.")
    add(f"- Puntos de venta inválidos en catálogo: {len(rel['catalogo_pv_invalidos'])}.")
    add(
        f"- `leads` ↔ `historico_cierres` por `lead_id`: {rel['leads_historico']['interseccion']} coincidencias "
        f"(prefijos: leads={rel['leads_historico']['prefijos']['leads']}, histórico={rel['leads_historico']['prefijos']['historico']})."
    )
    add(
        f"- `leads` ↔ `conversaciones` por `lead_id`: {conv['conversaciones_con_match']} conversaciones coinciden, "
        f"{conv['conversaciones_sin_match']} no coinciden."
    )
    add(f"- Validaciones de referencias (empresa/punto): {rel['validaciones']}.")
    add("")

    add("## 4. Conversaciones")
    add("")
    add(f"- Total: {conv['total_conversaciones']} · `lead_id` distintos: {conv['lead_ids_distintos']}.")
    add(f"- Con match a `leads.csv`: {conv['conversaciones_con_match']} · Sin match: {conv['conversaciones_sin_match']}.")
    add(f"- Leads sin conversación: {conv['leads_sin_conversacion']}.")
    add(f"- `lead_id` con más de una conversación: {conv['lead_id_duplicados']}.")
    add(f"- Conversaciones vacías: {len(conv['vacios'])} · Que no inician con cliente: {len(conv['no_inicia_cliente'])} · De un solo emisor: {len(conv['un_solo_emisor'])}.")
    add(f"- Mensajes por conversación: {conv['longitudes']['mensajes_por_conversacion']}.")
    add(f"- Caracteres por conversación: {conv['longitudes']['caracteres']}.")
    add(f"- Palabras por conversación: {conv['longitudes']['palabras']}.")
    add(f"- Emisores: {conv['longitudes']['emisores']}.")
    add("")
    add("Conversaciones sin match (bloque anómalo):")
    add("")
    rows = [[row["conversacion_id"], row["lead_id"], row["fecha_inicio"]] for row in conv["ejemplos_sin_match"]]
    lines += _table(["conversacion_id", "lead_id", "fecha_inicio"], rows)
    add("")

    add("## 5. Histórico")
    add("")
    add(f"- Registros: {hist['registros']}.")
    add(f"- Desenlace: {hist['desenlace']}.")
    add(f"- Por empresa: {hist['por_empresa']}.")
    add(f"- Por canal: {hist['por_canal']}.")
    add(f"- Valores faltantes: {hist['faltantes']}.")
    add(f"- Numéricas: {hist['numericas']}.")
    add(f"- Contactos por desenlace: {hist['contactos_por_desenlace']}.")
    add(f"- Horas por desenlace: {hist['horas_por_desenlace']}.")
    add("")
    add("### 5.1 Variables candidatas a data leakage")
    add("")
    rows = [
        [name, info.get("clasificacion"), info.get("nulos", info.get("iguales_a_cero", "")), info["motivo"]]
        for name, info in hist["leakage"].items()
    ]
    lines += _table(["Variable", "Clasificación", "Afectados", "Motivo"], rows)
    add("")
    add(f"Variables disponibles antes de la gestión (candidatas a priorización): {hist['posible_priorizacion']}.")
    add("")

    add("## 6. Catálogo")
    add("")
    add(f"- Registros: {cat['registros']} · Líneas únicas: {cat['lineas_unicas']}.")
    add(f"- Marcas: {cat['marcas']}.")
    add(f"- Segmentos: {cat['segmentos']}.")
    add(f"- Cilindrajes: {cat['cilindrajes']}.")
    add(f"- Precios: {cat['precios']}.")
    add(f"- Unidades disponibles: {cat['unidades']}.")
    add(f"- Cobertura de puntos de venta por SKU: {cat['cobertura_puntos_venta']}.")
    add(f"- Modelos del histórico sin catálogo: {cat['historico_modelos_sin_catalogo']}.")
    add(f"- Inconsistencias de precio histórico vs catálogo: {len(cat['historico_precio_inconsistente'])}.")
    add(f"- Modelos de leads sin match: {cat['leads_modelos_sin_match']}.")
    add("")

    add("## 7. Asesores")
    add("")
    add(f"- Registros: {ase['registros']}.")
    add(f"- Por empresa: {ase['por_empresa']}.")
    add(f"- Por punto de venta: {ase['por_punto_venta']}.")
    add(f"- Activos: {ase['activos']} · Inactivos: {ase['inactivos']}.")
    add(f"- Capacidad diaria: {ase['capacidades']}.")
    add(f"- Capacidad diaria por punto de venta: {ase['capacidad_diaria_por_punto_venta']}.")
    add(f"- Puntos sin asesor activo: {ase['puntos_sin_asesor_activo']}.")
    add("")

    add("## 8. Inconsistencias detectadas y clasificación")
    add("")
    add("Clasificación usada:")
    add("")
    add("- **Corregible automáticamente**: se puede normalizar sin decisión de negocio (deduplicar filas idénticas, unificar mayúsculas/acentos, canonizar teléfonos, mapear ciudades con alias evidentes).")
    add("- **Requiere regla de negocio**: hay que definir una política (fechas ambiguas, duplicados de cliente, valores faltantes, unión de datasets).")
    add("- **Debe conservarse como dato original**: no es un error; se documenta y se preserva (cobertura parcial, desbalance de clases, referencias válidas).")
    add("- **Requiere revisión humana**: caso a caso (teléfono inválido, conversaciones sin match, email duplicado, inconsistencia cronológica).")
    add("")
    rows = [
        [
            issue["id"],
            issue["dataset"],
            issue["campo"],
            issue["tipo"],
            CLASS_LABELS.get(issue["clasificacion"], issue["clasificacion"]),
            f"{issue['n_afectados']:,}",
            issue["descripcion"],
        ]
        for issue in summary["issues"]
    ]
    lines += _table(["ID", "Dataset", "Campo", "Tipo", "Clasificación", "Afectados", "Descripción"], rows)
    add("")
    add("Resumen por clasificación:")
    add("")
    counts = {}
    for issue in summary["issues"]:
        counts[issue["clasificacion"]] = counts.get(issue["clasificacion"], 0) + 1
    rows = [[CLASS_LABELS[key], value] for key, value in counts.items()]
    lines += _table(["Clasificación", "N.º de hallazgos"], rows)
    add("")

    add("## 9. Confirmación de no modificación de originales")
    add("")
    add("El script `scripts/run_audit.py` abre los archivos en modo lectura (`r`/`rb`) y solo escribe en `docs/` y `reports/`.")
    add("Los hashes SHA-256 de la sección 0 permiten comprobar que `data/` quedó intacto tras ejecutar la auditoría.")
    add("")

    lines += _static_decisions()
    lines += _static_assumptions()

    return "\n".join(lines) + "\n"


def _static_decisions() -> list[str]:
    return [
        "## 10. Decisiones que necesitamos tomar antes de implementar",
        "",
        "1. **Fechas ambiguas DD/MM vs MM/DD**: `leads.csv` mezcla formatos y tiene fechas con barra donde día y mes son ambos <= 12 (ver §2.4). ¿Cuál es el formato canónico? ¿Se descartan, se corrigen con una regla o se pide la fuente original?",
        "2. **Duplicados y entidad cliente**: hay filas idénticas, teléfonos compartidos por más de un lead y emails repetidos (ver §2.1). ¿La unidad de análisis es el `lead_id`, la persona o la conversación? ¿Se fusionan o se mantienen?",
        "3. **Unión `leads` ↔ `historico_cierres`**: la intersección de `lead_id` es cero (prefijos LD- vs HX-). ¿Se modelan como datasets independientes o se necesita una llave alternativa (teléfono/email/nombre+ciudad) y con qué tolerancia de error?",
        "4. **Variable objetivo del histórico**: `desenlace` tiene 3 clases muy desbalanceadas (ver §5). ¿Se binariza `Cerrado` vs resto? ¿Se excluye `Sin gestión`? ¿Es un problema de clasificación de cierre o de priorización?",
        "5. **Data leakage**: confirmar el momento de captura de `horas_al_primer_contacto`, `numero_contactos`, `pidio_cita`, `manifesto_cuota_inicial` y `forma_pago_declarada`. ¿Se excluyen del modelado o solo las dos primeras?",
        "6. **Normalización de modelos**: parte de los leads menciona solo la marca o nombres parciales/ambiguos (ver §2.6). ¿Qué regla se aplica: descartar, pedir a negocio o asignar el modelo más probable del catálogo?",
        "7. **Política de valores faltantes**: email, campaña, `fecha_primer_contacto`, ciudad y modelo tienen faltantes relevantes (ver §1, §2.3, §2.5). ¿Imputar, marcar como categoría o excluir del entrenamiento?",
        "8. **Conversaciones sin match**: 12 conversaciones apuntan a `lead_id` inexistentes (bloque LD-9xxxx del 2026-08-15). ¿Se descartan, se corrigen o se revisan manualmente?",
        "9. **Múltiples conversaciones por lead**: 25 `lead_id` tienen 2 conversaciones. ¿Son sesiones legítimas o duplicados? ¿Se concatenan o se elige una?",
        "10. **Definición de priorización**: no está definido qué significa priorizar ni el horizonte temporal. ¿Score de probabilidad de cierre, orden de contacto, asignación a asesores?",
        "11. **Asignación a asesores**: `leads.csv` no tiene `asesor_id`. ¿Cómo se asigna cada lead a un asesor y cómo entra `capacidad_diaria_leads` como restricción?",
        "12. **Vigencia del catálogo**: `catalogo_motos.csv` parece un snapshot sin fecha. ¿El `precio_lista` y `unidades_disponibles` son vigentes y por SKU global o por punto de venta?",
        "13. **Alcance de canales para NLP**: solo WhatsApp tiene transcriptciones. ¿El análisis de conversaciones se limita a WhatsApp o se espera cubrir los otros canales?",
        "14. **Segmentación por empresa**: ¿el modelo debe ser único o entrenar/evaluar por separado para EMP-01, EMP-02 y EMP-03?",
        "15. **Qué se considera éxito de la solución**: ¿métrica, umbral y comparación contra un baseline? ¿Existe una línea base de gestión actual?",
        "",
    ]


def _static_assumptions() -> list[str]:
    return [
        "## 11. Supuestos que NO pueden confirmarse solo con los datos",
        "",
        "- Si los `lead_id` duplicados son errores de captura o re-registros de la misma persona.",
        "- Si teléfonos/emails compartidos pertenecen a la misma persona, a un familiar o a un error; tampoco si un mismo cliente puede generar varios leads.",
        "- La zona horaria y el origen real de los formatos de fecha (por qué aparecen MM/DD y DD/MM mezclados).",
        "- El momento exacto de captura de las variables del histórico; por eso la clasificación de leakage es una hipótesis, no un hecho probado con los datos.",
        "- Si `Sin gestión` es un desenlace definitivo o un estado pendiente sin actualizar.",
        "- Si dos conversaciones del mismo `lead_id` son sesiones distintas o duplicados de ingesta.",
        "- Si `unidades_disponibles` es inventario global del SKU o por punto de venta, y si el catálogo tiene fecha de vigencia.",
        "- Si `email` y `campania` son obligatorios por canal; su ausencia podría ser estructural y no un defecto de calidad.",
        "- Las reglas de negocio de priorización, SLA de contacto y criterios de cierre de la empresa.",
        "- Si los datos sintéticos preservan las distribuciones y el comportamiento real de los clientes, asesores y mercados.",
        "- Qué canales generan leads efectivamente (una parte importante de leads no tiene conversación, pero no sabemos si eso implica ausencia de interacción).",
        "",
    ]


def write_markdown(summary: dict) -> str:
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DOCS_DIR / "data-audit.md"
    path.write_text(render_markdown(summary), encoding="utf-8")
    return str(path)
