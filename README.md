# Analista IA — Priorización inteligente de leads

Sistema para convertir los leads comerciales de tres empresas en una lista diaria
de gestión priorizada para los asesores, apoyándose en los datos de leads y en las
conversaciones de WhatsApp.

## Estado actual: bootstrap

Este repositorio está en su etapa inicial. Hoy solo existe un esqueleto ejecutable:

- aplicación FastAPI con página inicial mínima y `/health`;
- configuración centralizada por variables de entorno;
- conexión a PostgreSQL preparada (SQLAlchemy + `psycopg`);
- Alembic configurado (sin tablas de dominio todavía);
- tests mínimos;
- `Dockerfile` y `docker-compose.yml` opcional para Postgres local.

**Todavía no están implementados**: ingesta de los archivos de `data/`,
normalización, deduplicación, procesamiento de conversaciones, extracción con IA,
scoring, asignación a asesores, dashboard ni autenticación.

El diseño completo y los hallazgos del análisis de datos están en `docs/`.

## Stack

- Python 3.11
- uv para gestión de entorno y dependencias
- FastAPI + Jinja2 (HTML server-side)
- PostgreSQL + SQLAlchemy 2 + Alembic, con driver `psycopg` 3
- pydantic-settings para configuración
- pytest + httpx para pruebas

## Dependencias

`pyproject.toml` junto con `uv.lock` es la única fuente de verdad de dependencias:
runtime en `dependencies` y pruebas en el grupo `dev`. No hay `requirements.txt`.

```bash
uv add <paquete>          # dependencia de runtime
uv add --dev <paquete>    # dependencia de desarrollo/pruebas
uv sync                   # instala/actualiza .venv segun el lock
```

## Cómo ejecutar localmente

Requiere [uv](https://docs.astral.sh/uv/). El proyecto fija Python 3.11 en
`.python-version` y las versiones en `uv.lock`.

```bash
uv sync                # crea .venv con Python 3.11 e instala dependencias
cp .env.example .env   # ajusta DATABASE_URL si es necesario
uv run uvicorn app.main:app --reload
```

- Página inicial: http://127.0.0.1:8000/
- Salud: http://127.0.0.1:8000/health

PostgreSQL local opcional (no obligatorio):

```bash
docker compose up -d db
```

## Desarrollo local

Un solo comando para entorno + migraciones + servidor (nunca borra datos):

```bash
uv run dev
```

Entrar a http://127.0.0.1:8000 → login demo (solo desarrollo):

```text
advisor.demo@motos.local / demo-asesor-123      → vista asesor (sus leads)
supervisor.demo@motos.local / demo-supervisor-123 → supervisión (su empresa)
admin.demo@motos.local / demo-admin-123         → supervisión global
```

Las credenciales demo se configuran por entorno (`ADVISOR_DEMO_*`,
`SUPERVISOR_DEMO_*`); en la base solo se guarda el hash. El aislamiento por
empresa/POS/asesor se aplica siempre en backend desde el usuario autenticado.

Procesar datos:

```bash
uv run pipeline        # pipeline completo sin IA
uv run pipeline-ai     # pipeline completo con IA (todo lo pendiente)
uv run pipeline-ai --ai-limit 100   # prueba controlada
uv run supervisor      # como dev; el rol lo determina el login
```

## Variables de entorno

Ver `.env.example`. Como mínimo: `APP_ENV`, `SECRET_KEY`, `DATABASE_URL`, `PORT`.
El archivo `.env` no se versiona.

## Tests

```bash
uv run pytest
```

Las pruebas no necesitan una base de datos externa.

## Migraciones

```bash
uv run alembic upgrade head
```

Alembic está configurado, pero en esta etapa no hay revisiones de dominio.

## Documentación

- `docs/data-audit.md` — auditoría reproducible de los datasets.
- `docs/technical-design.md` — diseño técnico y funcional.
- `docs/scoring-design.md` — diseño del scoring explicable.
