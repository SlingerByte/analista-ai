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
