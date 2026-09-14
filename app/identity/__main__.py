from __future__ import annotations

import json

from app.db import SessionLocal
from app.identity.service import run_identity


def _print_summary(report: dict) -> None:
    steps = report["steps"]
    print("=== Reporte de identidad ===")
    print(f"Run #{report['run_id']} ({report['status']})")
    print(f"Leads evaluados: {steps['leads_evaluated']}")
    print(
        f"Clusters creados: {steps['clusters_created']} · "
        f"reutilizados: {steps['clusters_reused']} · total: {steps['clusters_total']}"
    )
    print(
        f"Miembros creados: {steps['members_created']} · "
        f"actualizados: {steps['members_updated']} · "
        f"sin cambios: {steps['members_unchanged']} · total: {steps['members_total']}"
    )
    print(f"Relaciones por regla: {steps['relations_by_rule']}")
    print(f"Relaciones descartadas: {steps['relations_discarded']}")
    print(f"Tamaños de cluster: {steps['cluster_size_distribution']}")
    print(f"Conversaciones con lead: {steps['conversations_with_lead']}")
    print(f"Conversaciones huérfanas: {steps['conversations_orphan']}")
    print(f"Leads con múltiples conversaciones: {steps['leads_with_multiple_conversations']}")


def main() -> None:
    with SessionLocal() as session:
        report = run_identity(session)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print()
    _print_summary(report)


if __name__ == "__main__":
    main()
