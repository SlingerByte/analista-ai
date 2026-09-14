from __future__ import annotations

import json

from app.db import SessionLocal
from app.ingestion.service import run_ingestion


def _print_summary(report: dict) -> None:
    leads = report["steps"]["leads"]
    conversations = report["steps"]["conversations"]

    print("=== Reporte de ingesta ===")
    print(f"Run #{report['run_id']} ({report['status']})")
    print(f"Leads leídos: {leads['read']}")
    print(f"Leads persistidos: {leads['persisted']}")
    print(f"  insertados={leads['inserted']} actualizados={leads['updated']} sin cambios={leads['unchanged']}")
    print(f"IDs duplicados detectados: {leads['duplicate_count']} {leads['duplicate_ids']}")
    print(f"Fechas ambiguas (registro): {leads['ambiguous_registration_dates']}")
    print(f"Fechas ambiguas (primer contacto): {leads['ambiguous_first_contact_dates']}")
    print(f"Fechas ambiguas por convención (guion): {leads['ambiguous_by_convention_dates']}")
    print(f"Fechas desconocidas: {leads['unknown_dates']}")
    print(f"Inconsistencias cronológicas: {leads['chronology_inconsistencies']}")
    print(f"Gestionados sin fecha de primer contacto: {leads['managed_without_first_contact']}")
    print(f"Teléfonos inválidos: {leads['invalid_phones']}")
    print(f"Ciudades normalizadas: {leads['cities_normalized']} (sin match: {leads['cities_unmatched']})")
    print(f"Modelos matched: {leads['models_matched']}")
    print(f"Modelos ambiguos: {leads['models_ambiguous']}")
    print(f"Modelos no identificados: {leads['models_unmatched']}")
    print(f"Modelos vacíos: {leads['models_empty']}")
    print(f"Referencias empresa/punto inválidas: {leads['invalid_references']}")
    print(f"Conversaciones leídas: {conversations['read']}")
    print(f"Conversaciones asociadas: {conversations['linked']}")
    print(f"Conversaciones huérfanas: {conversations['orphan']}")
    print(f"Leads con más de una conversación: {conversations['multiple_conversations_per_lead']}")


def main() -> None:
    with SessionLocal() as session:
        report = run_ingestion(session)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print()
    _print_summary(report)


if __name__ == "__main__":
    main()
