from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from audit import config
from audit import report


def main() -> int:
    summary = report.build_summary()
    auxiliary = report.write_auxiliary_reports(summary)
    markdown = report.write_markdown(summary)

    print("Auditoría de datos completada (solo lectura).")
    print(f"Reporte: {markdown}")
    for path in auxiliary:
        print(f"Auxiliar: {path}")

    issues = summary["issues"]
    print("")
    print(f"Inconsistencias registradas: {len(issues)}")
    for issue in issues:
        if issue["n_afectados"]:
            print(f"  - [{issue['id']}] {issue['clasificacion']}: {issue['descripcion']} ({issue['n_afectados']})")

    for name, info in summary["archivos"].items():
        print(f"sha256 {name}: {info['sha256']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
