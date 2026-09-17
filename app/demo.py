"""Comando único demo/entorno: DB + migraciones + pipeline (+ servidor).

Uso:
    uv run python -m app.demo --ai-limit 100
    uv run python -m app.demo --ai-limit 677
    uv run python -m app.demo --no-ai --no-serve

No hace operaciones destructivas: nunca borra volúmenes, nunca recrea la
base, nunca elimina datos. Todo lo que ejecuta es idempotente y seguro de
repetir. Delega el procesamiento en ``app.pipeline`` sin duplicar lógica.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Entry points `uv run dev|supervisor|pipeline|pipeline-ai` definidos en
# [project.scripts]; `python -m app.demo` sigue funcionando igual.


def _port_open(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=3).close()
        return True
    except OSError:
        return False


def ensure_database() -> str:
    """Verifica PostgreSQL; si está detenido, levanta solo el servicio db."""
    if _port_open("localhost", 5432):
        return "Database available (ya estaba en ejecución)"
    compose = PROJECT_ROOT / "docker-compose.yml"
    docker = shutil.which("docker")
    if docker is None or not compose.exists():
        raise SystemExit(
            "ERROR: PostgreSQL no disponible en localhost:5432 y no hay "
            "Docker Compose para levantarlo. Inicie PostgreSQL y reintente."
        )
    subprocess.run(
        [docker, "compose", "up", "-d", "db"], cwd=PROJECT_ROOT, check=True
    )
    for _ in range(45):
        if _port_open("localhost", 5432):
            return "Database available (servicio db iniciado)"
        time.sleep(2)
    raise SystemExit("ERROR: PostgreSQL no respondió tras iniciar el servicio db.")


def run_migrations() -> str:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return "Migrations up to date"


def run_flow(run_date: date | None, ai_limit: int | None, run_ai: bool) -> dict:
    from app.db import SessionLocal
    from app.pipeline import run_pipeline

    with SessionLocal() as session:
        report = run_pipeline(
            session, run_date=run_date, run_ai=run_ai, ai_limit=ai_limit
        )
    if report["status"] != "completed":
        raise SystemExit(f"ERROR: pipeline {report['status']}: {report['steps']}")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Demo: entorno + pipeline + dashboard")
    parser.add_argument("--ai-limit", type=int, default=None)
    parser.add_argument("--run-date", type=date.fromisoformat, default=None)
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--no-serve", action="store_true")
    args = parser.parse_args(argv)

    status = ensure_database()
    print("[OK] " + status)
    print("[OK] " + run_migrations())
    print("[OK] Reference data ready (etapa idempotente del pipeline)")
    report = run_flow(args.run_date, args.ai_limit, run_ai=not args.no_ai)
    steps = report["steps"]
    print(
        f"[OK] Pipeline completed (run {report['run_id']}: "
        f"{steps['scoring'].get('leads', '?')} scores, "
        f"{steps['assignment'].get('assigned', '?')} assigned, "
        f"{steps['assignment'].get('overflow', '?')} overflow)"
    )
    ai = steps.get("ai", {})
    if ai.get("status") == "skipped":
        print(f"[..] IA: omitida ({ai.get('reason', 'no disponible')})")
    elif not ai.get("candidates"):
        print("[..] IA: no hay conversaciones pendientes para analizar.")
    else:
        limit_note = (f" · límite {args.ai_limit}"
                      if args.ai_limit is not None else "")
        print(
            f"[OK] IA {ai.get('provider')}/{ai.get('model')}{limit_note}: "
            f"{ai.get('candidates', '?')} seleccionadas, "
            f"{ai.get('processed', '?')} procesadas, "
            f"{ai.get('reused', '?')} reutilizadas, "
            f"{ai.get('failed', '?')} fallidas"
        )

def _serve(host: str, port: int) -> None:
    from app.config import get_settings  # noqa: F401 - valida configuración

    print(f"[OK] Dashboard available at http://127.0.0.1:{port}")
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host,
         "--port", str(port)],
        cwd=PROJECT_ROOT,
        check=False,
    )


def _serve_args(argv: list[str] | None, hint: str | None = None) -> tuple[str, int]:
    parser = argparse.ArgumentParser(description="Serve the Analista IA dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    from app.config import get_settings

    port = args.port or get_settings().port
    if hint:
        print(hint)
    return args.host, port


def dev_main(argv: list[str] | None = None) -> None:
    """Entry point `uv run dev`: entorno + migraciones + servidor."""
    print("[OK] " + ensure_database())
    print("[OK] " + run_migrations())
    host, port = _serve_args(
        argv, "Inicie sesión con su usuario demo para entrar al dashboard.")
    _serve(host, port)


def serve_main(argv: list[str] | None = None) -> None:
    """Entry point `uv run supervisor`: igual que dev; el rol lo da el login."""
    print("[OK] " + ensure_database())
    print("[OK] " + run_migrations())
    host, port = _serve_args(
        argv, "Entre con el usuario supervisor para ver Supervisión comercial.")
    _serve(host, port)


if __name__ == "__main__":
    main()
