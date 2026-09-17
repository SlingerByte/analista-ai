# Analista IA — Priorización inteligente de leads

Sistema que convierte los leads comerciales de tres empresas (WhatsApp, Meta Ads
y Formulario Web) en una **lista diaria de gestión priorizada, explicable y
aislada por empresa / punto de venta**, apoyándose en los datos del CRM y en las
conversaciones de WhatsApp.

Responde una sola pregunta operativa:

> ¿Qué leads debo gestionar hoy y por qué?

## Flujo

```text
ingesta → normalización → deduplicación → vinculación de conversaciones
       → extracción IA → validación de evidencia → scoring
       → asignación a asesores → gestión diaria (dashboard)
       → cierre (Cerrado / Perdido / Descartado) → liberación de capacidad
       → promoción de overflow en el siguiente ciclo de asignación
```

Cada etapa es determinista e idempotente y se ejecuta con un único comando:

```bash
uv run pipeline        # pipeline completo SIN IA
uv run pipeline-ai     # pipeline completo CON IA (pendientes)
uv run pipeline-ai --ai-limit 100   # prueba controlada
```

## Arquitectura

- **Python 3.11** + **uv** para entorno y dependencias.
- **FastAPI** + **Jinja2** (HTML server-side), un solo servicio.
- **PostgreSQL** con **SQLAlchemy 2** + **Alembic** (driver `psycopg` 3).
- **Abstracción de proveedor de IA**: `Ollama` para desarrollo local y
  `OpenRouter` para producción; el pipeline no depende de un proveedor concreto.
- **Autenticación por roles** (asesor, supervisor, admin) con sesión firmada.
- **Aislamiento por empresa** aplicado siempre en el backend.

No se usan (y no forman parte de la solución): agentes autónomos, RAG, vector
databases, LangChain/LangGraph, ML predictivo ni microservicios.

## Datos

- `leads.csv` — 1.503 filas (1.501 `lead_id` únicos; 2 duplicados exactos).
- `conversaciones.json` — 677 conversaciones de WhatsApp (4.310 mensajes;
  665 enlazadas, 12 huérfanas, 25 leads con más de una conversación).
- `catalogo_motos.csv` — 24 SKU.
- `asesores.csv` — 42 asesores en 15 puntos de venta de 3 empresas.
- `historico_cierres.csv` — 2.200 cierres históricos.

El **histórico de cierres se usa solo como dataset de referencia/auditoría** (y
en `docs/data-audit.md`). **No es un predictor individual**: la intersección de
`lead_id` entre leads actuales (`LD-*`) e histórico (`HX-*`) es 0, por lo que no
existe una llave fiable para hacer *join*, y no entra en el scoring.

## Extracción con IA y validación de evidencia

- Extracción **estructurada** por conversación (pydantic) con 8 campos:
  `modelo_interes`, `presupuesto`, `cuota_inicial`, `forma_pago`,
  `intencion_compra`, `objecion`, `solicitud_cita`, `solicitud_cotizacion`.
- Cada valor viaja con **evidencia**: una cita del **cliente**.
- **Validación determinista** (`app/ai/validation.py`): la IA interpreta, el
  sistema valida. Solo se persiste un campo si su evidencia corresponde
  literalmente a un mensaje del cliente (tolerando prefijo `cliente:`/`asesor:`,
  mayúsculas, acentos, espacios y puntuación). Para campos monetarios, la
  evidencia debe contener el monto. Lo que no cumple se anula (`null`) y no
  llega al scoring.
- **Persistencia** en `ai_extractions` con `provider`, `model_name`,
  `prompt_version`, `schema_version`, `input_hash`, `latency_ms` y errores
  sanitizados.
- **Idempotencia**: `input_hash = sha256(prompt_version + schema_version +
  transcripción)` + unique `(conversation_id, input_hash)`. Reutilizar una
  extracción **nunca** salta la validación: se revalida en el momento.
- **Proveedores**: `AI_PROVIDER=ollama` (desarrollo) u `openrouter`
  (producción). En producción no se admite Ollama y se exige
  `OPENROUTER_API_KEY` + `OPENROUTER_MODEL`; si falta, la app y los entrypoints
  batch fallan con un mensaje claro.

## Scoring

**Determinista y explicable**, sin caja negra. No usa el histórico. Dimensiones:

| Dimensión | Rol |
|---|---|
| `commercial_score` | Valor comercial (intención, cita, cotización, presupuesto, cuota, forma de pago, objeción, ticket). |
| `urgency_score` | Urgencia operativa (estado de gestión y antigüedad; fallback por estado). |
| `quality` | Calidad/completitud del dato. **Dimensión separada: no modifica `queue_score`.** |
| `queue_score` | `0.7 · commercial + 0.3 · urgency`; ordena la cola del día. |

Bandas de prioridad: **Alta ≥ 70**, **Media 45–69**, **Baja < 45**.
Cada `lead_score` guarda `reasons` (código, dimensión, texto y contribución) y
`params_snapshot` para reconstruir el cálculo. La UI muestra la explicación de
prioridad (comercial + urgencia) por separado de la calidad.

## Seguridad y aislamiento

- **Login** con sesión firmada (HMAC-SHA256) y contraseñas PBKDF2-SHA256.
- **Roles**: `asesor`, `supervisor`, `admin`.
- El aislamiento se aplica **server-side** desde el usuario autenticado; el
  frontend nunca aporta identidad ni empresa.
  - **asesor** → solo sus asignaciones; no accede a supervisión ni a overflow.
  - **supervisor** → solo su empresa (overflow incluido).
  - **admin** → global, con filtros por empresa/POS/asesor.
- Consultar un lead por ID fuera del alcance devuelve 404/403.
- Integridad empresa ↔ POS ↔ asesor: validación en el punto de escritura
  (`app/integrity.py`) y constraints compuestos en PostgreSQL.
- **Sin secretos en el repositorio**: `.env` no se versiona; `.env.example` solo
  tiene placeholders.

## Gestión diaria

- **Asesor** (`/`): "Mis leads de hoy" ordenados por prioridad, con modelo,
  estado, banda, score y detalle (razones + señales IA).
- **Supervisión** (`/supervision`): asignados por empresa/POS/asesor con filtros,
  y sección **Pendientes de asignación** (overflow) que muestra empresa, POS,
  cliente, modelo, prioridad, score, fecha de registro y motivo
  (`sin_capacidad`). Incluye la acción **Reintentar asignación** para
  supervisor/admin, y contadores del ciclo de vida (abiertos / cerrados /
  perdidos / descartados).
- La asignación es **determinista**, respeta `empresa + punto de venta`, nunca
  mueve un lead a otro POS y solo usa asesores activos. El reintento reutiliza
  el mismo algoritmo y es **idempotente**.
- **Capacidad dinámica**: el cupo de un asesor es
  `daily_capacity − leads abiertos con asignación operativa vigente`. Los estados
  terminales no consumen capacidad. No hay contador persistido.
- **Continuidad**: un lead abierto que ya tiene asesor vigente lo conserva en la
  siguiente corrida (no se rebalancea por capacidad).

## Ciclo de vida del lead

- Estados **abiertos**: `Sin gestión`, `Contactado`, `No contesta`,
  `Cotización enviada`, `En proceso`.
- Estados **terminales**: `Cerrado` (conversión positiva), `Perdido`
  (oportunidad válida no convertida) y `Descartado` (no debe continuar como
  oportunidad). `Perdido` y `Descartado` **no** son equivalentes.
- El cierre es una **transición de estado** desde el detalle del lead
  (`POST /leads/{lead_id}/status`, con motivo). Registra `closed_at` y
  `close_reason` en `leads`; **nunca borra** lead, conversaciones, extracciones,
  scores ni asignaciones.
- Un lead terminal **no se reabre** y **no vuelve a ser candidato** de asignación.
- Al cerrarse libera su cupo lógico: en el siguiente ciclo (`pipeline` o
  **Reintentar asignación**) ese cupo puede asignarse a un lead de `overflow`
  compatible (misma empresa y POS, asesor activo, orden `queue_score DESC,
  lead_id ASC`). No hay colas externas.
- La definición central de estados vive en `app/lead_status.py`
  (`is_lead_open` / `is_lead_terminal`); no hay listas duplicadas.

## Ejecución local

Requiere [uv](https://docs.astral.sh/uv/) y un PostgreSQL accesible.

```bash
uv sync
cp .env.example .env          # Windows: Copy-Item .env.example .env
docker compose up -d db       # PostgreSQL local opcional
uv run alembic upgrade head   # migraciones
uv run python -m app.seed     # datos maestros + usuarios demo
uv run uvicorn app.main:app --reload
```

- App: http://127.0.0.1:8000/
- Salud: http://127.0.0.1:8000/health

Atajo de desarrollo (entorno + migraciones + servidor, nunca borra datos):

```bash
uv run dev
```

Login demo (solo desarrollo):

```text
advisor.demo@motos.local    / demo-asesor-123       → sus leads
supervisor.demo@motos.local / demo-supervisor-123   → su empresa
admin.demo@motos.local      / demo-admin-123        → global
```

## Tests

```bash
uv run pytest         # 525 passed
uv run alembic check  # No new upgrade operations detected (requiere BD accesible)
```

Los tests no necesitan PostgreSQL ni proveedores externos de IA (Ollama/OpenRouter).

## Migraciones

```bash
uv run alembic upgrade head
```

Al agregar constraints/columnas, cree una revisión; no deje migraciones vacías.
`uv run alembic check` debe reportar que no hay cambios pendientes.

## Deployment (Render + PostgreSQL externo)

Configuración reproducible en `render.yaml` + `Dockerfile`; la base PostgreSQL
es gestionada externamente (Render, Neon, Supabase, etc.).

1. Cree la base PostgreSQL y copie su `DATABASE_URL`.
2. Cree el servicio web en Render desde `render.yaml` (runtime Docker).
   El `Dockerfile` ejecuta **`alembic upgrade head` antes de** arrancar
   `uvicorn`.
3. Configure las variables de entorno (ninguna en archivos versionados).

Variables obligatorias en producción:

| Variable | Descripción |
|---|---|
| `APP_ENV` | `production`. |
| `SECRET_KEY` | Secreto real (Render puede generarlo). La app **falla al arrancar** si es un valor inseguro. |
| `DATABASE_URL` | URL de PostgreSQL (`postgresql+psycopg://...`). |
| `AI_PROVIDER` | `openrouter` (Ollama no está permitido en producción). |
| `OPENROUTER_API_KEY` | Clave del proveedor remoto. |
| `OPENROUTER_MODEL` | Modelo con salida JSON. |
| `OPENROUTER_BASE_URL` | Opcional; por defecto `https://openrouter.ai/api/v1`. |

Comportamiento de producción:

- Las cookies de sesión se emiten con `Secure` (HTTPS obligatorio).
- `/health` responde `{status, database, ai_provider}`; no expone secretos ni
  `DATABASE_URL` ni realiza llamadas al LLM.
- `alembic upgrade head` corre en el arranque del contenedor.

## Documentación

- `docs/data-audit.md` — auditoría reproducible de los datasets.
- `docs/technical-design.md` — diseño técnico y funcional.
- `docs/scoring-design.md` — diseño del scoring explicable.

## Limitaciones conocidas

- El histórico de cierres no es un predictor individual (no hay llave).
- Fechas ambiguas (`DD/MM` vs `MM/DD`) no se adivinan: se marcan como no
  confiables y no alimentan la urgencia.
- La calidad del dato (`quality`) se muestra aparte y no entra en `queue_score`.
- La validación de evidencia es determinista y conservadora: puede rechazar
  citas reformuladas por el modelo.
