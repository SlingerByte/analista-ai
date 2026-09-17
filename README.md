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
  `OpenRouter`/`Groq` para producción; el pipeline no depende de un proveedor
  concreto.
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
- **Proveedores**: `ollama`/`local` (desarrollo) u `openrouter`/`groq`
  (producción). En producción no se admite Ollama/local y, para el proveedor
  remoto configurado, se exigen sus credenciales (`OPENROUTER_*` o `GROQ_*`);
  si faltan, la app y los entrypoints batch fallan con un mensaje claro.
- El **modelo es configurable por entorno** (`OPENROUTER_MODEL`/`GROQ_MODEL`).
  No se garantiza disponibilidad de ningún modelo concreto: los modelos
  gratuitos pueden devolver `HTTP 429` (rate limit). El sistema lo registra
  como error de extracción (no bloquea ni duplica la conversación) y el
  reintento es idempotente.
- **IA local en el navegador (opcional).** Si el usuario tiene Ollama corriendo
  en su equipo, `/supervision` lo detecta **desde el navegador**
  (`http://127.0.0.1:11434/api/tags`) y permite ejecutar la extracción sin
  enviar la conversación a un proveedor remoto. El backend **no** contacta a
  Ollama: el navegador llama a Ollama con el mismo prompt V8/schema v1 (que el
  backend entrega) y envía el resultado de vuelta, donde se valida y persiste
  con la lógica existente (evidencia, `input_hash`, `is_current`, scoring).

  Configuración **en la PC del usuario** (no en Render):

  ```bash
  # 1) Permitir el origen de la aplicación desplegada en Ollama.
  #    Windows (PowerShell, sesión actual):
  setx OLLAMA_ORIGINS "https://<tu-dominio>"
  #    macOS/Linux (antes de arrancar Ollama):
  export OLLAMA_ORIGINS="https://<tu-dominio>"
  # 2) Reiniciar Ollama y verificar que responde:
  #    http://127.0.0.1:11434/api/tags
  ```

  Si Ollama no responde, la UI muestra “⚪ Ollama local no disponible” (sin
  errores técnicos). Nota: el navegador solo expone un fallo genérico, no
  distingue CORS/red; ver la consola del navegador (`[ollama] …`) para el
  diagnóstico durante desarrollo. El backend nunca usa `127.0.0.1`.

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

## IA y scoring (cómo se combinan)

- La **IA interpreta** la conversación y extrae señales (modelo, presupuesto,
  cuota inicial, forma de pago, intención, objeción, cita, cotización) junto con
  su **evidencia** (cita del cliente).
- El **scoring es determinista y explicable**: **no** es "el resultado de la IA".
  La IA **aporta señales** que el scoring pondera junto con datos que **no**
  dependen de la conversación (estado de gestión, antigüedad, teléfono/email/
  ciudad, modelo de catálogo, ticket).
- Por eso un lead **puede tener score aunque todavía no tenga análisis IA**: se
  calcula con las señales deterministas disponibles y mejora cuando llega el
  análisis de la conversación.

## CRM vs IA (sin sobrescritura)

- El **CRM** es el dato operativo registrado (p. ej. el modelo cotizado).
- La **IA** es una **señal independiente** interpretada desde la conversación.
- La IA **nunca sobrescribe** el CRM: si el modelo registrado y el mencionado por
  el cliente difieren, la interfaz **muestra la discrepancia** y conserva ambos.
  Ejemplo real de la prueba: CRM `Honda Navi` vs conversación `Bajaj Boxer CT 100`.

## Leads sin conversación

No todos los leads tienen una conversación disponible. En ese caso el sistema
**no inventa información**: los campos de IA quedan desconocidos y el lead se
prioriza con las **señales deterministas** disponibles. Es un escenario normal y
ocurrió de forma real en la prueba con Ollama (**10 de 12** leads no tenían
conversación asociada).

## Presentación de nombres (solo visual)

Los nombres de cliente se muestran de forma consistente con
`app/presentation.display_name` (expuesto como filtro Jinja). Es **solo
presentación**:

- **no** modifica la base de datos, ni el valor original, ni agrega columnas ni
  migraciones;
- conserva tildes y Unicode, quita espacios externos y colapsa espacios repetidos;
- normaliza palabras **completamente mayúsculas o completamente minúsculas** y
  **deja intacta** la capitalización mixta; no usa IA.

Auditoría real: **329 / 1.501** nombres (21,9%) cambian de formato visual.
**No es deduplicación:** `identity` usa su propia normalización y no cambió
(43 clústeres / 86 miembros).

## Prueba real con IA local (Ollama, controlada)

Prueba puntual con **Ollama local** (`qwen2.5:3b`, proveedor `local`) sobre 12
leads seleccionados:

- solo **2** tenían conversación: se procesaron **2** conversaciones, **2
  exitosas, 0 errores**;
- los **10** restantes no se tocaron (sin conversación; **no se inventó** ninguna);
- los resultados quedaron **persistidos** en PostgreSQL/Supabase con la lógica
  existente (validación + `is_current` + scoring);
- ejemplo `LD-01085`: banda **Baja (C21.16 / U60 / Q32.81) → Alta (C71.16 / U100 /
  Q79.81)** por señales reales (intención alta, cuota inicial, solicitud de visita);
- ejemplo `LD-00214`: detectó un modelo distinto al del CRM; el **score no cambió**
  porque el resto de señales no fue suficiente.

> Es una prueba **controlada y pequeña**, **no** una evaluación estadística del
> modelo.

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
uv run pytest         # 568 passed
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
| `AI_PROVIDER` | `openrouter` o `groq` (Ollama/local no está permitido en producción). |
| `OPENROUTER_API_KEY` | Clave de OpenRouter (si `AI_PROVIDER=openrouter`). |
| `OPENROUTER_MODEL` | Modelo con salida JSON (OpenRouter). |
| `OPENROUTER_BASE_URL` | Opcional; por defecto `https://openrouter.ai/api/v1`. |
| `GROQ_API_KEY` | Clave de Groq (si `AI_PROVIDER=groq`). |
| `GROQ_MODEL` | Modelo con salida JSON (Groq). |
| `GROQ_BASE_URL` | Opcional; por defecto la API de Groq. |

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

## Limitaciones actuales y mejoras futuras

### El sistema funciona; hoy el límite está en el proveedor de IA

El flujo de negocio está completo y probado de extremo a extremo: **ingesta
automática → normalización → deduplicación → identificación de conversaciones →
extracción estructurada con IA → validación de evidencia → persistencia →
scoring → priorización → asignación → aislamiento por empresa → gestión del
ciclo de vida (cierre) → reintentos → recálculo del score tras el análisis**.
También está verificado el análisis bajo demanda y el soporte de varios
proveedores (Ollama local de desarrollo, OpenRouter y Groq remotos).

La limitación actual **no es un fallo del sistema**: es la **capacidad del
proveedor de IA** (cuota, rate limits, disponibilidad de modelos gratuitos y
latencia). Por eso **no se recomienda lanzar tandas grandes de análisis IA de
forma indiscriminada**.

Guía práctica (orientativa, **no** es un límite técnico universal):

1. Procesar **1 conversación** y verificar el resultado.
2. Continuar con **2**.
3. Subir a **~5** si el proveedor lo permite.
4. Tandas mayores **solo cuando exista capacidad suficiente**.

El tamaño adecuado del lote depende del **proveedor, el modelo, la cuota, la
latencia y la disponibilidad** del momento.

### Por qué conviene procesar en lotes pequeños

- Límites de cuota y **rate limits** del proveedor.
- Disponibilidad variable de modelos gratuitos.
- Latencia por llamada.
- Posibles respuestas **HTTP 429** (temporalmente limitado).
- Consumo de tokens.
- Capacidad limitada de la infraestructura.
- Necesidad de **controlar y diagnosticar errores**.
- Facilidad de **reintento** (idempotente por `input_hash`).
- **Evitar perder una tanda completa** por un fallo puntual.
- Poder **verificar progresivamente** la calidad de las extracciones.

> Procesar poco a poco **no** significa que el sistema no pueda procesar más
> datos. Significa que hoy el **proveedor de IA es el cuello de botella** y el
> sistema está diseñado para trabajar de forma **incremental**.

### La IA interpreta; el scoring no depende solo de la IA

La IA **interpreta conversaciones y extrae señales** (modelo, intención, cita,
cotización, presupuesto, cuota inicial, forma de pago, objeción). El **scoring
es determinista y explicable** y **no depende exclusivamente de la IA**: sigue
funcionando aunque no se analicen IA todas las conversaciones. Esto permite
operar con la capacidad disponible y ampliar el análisis cuando convenga.

### Implementado hoy

Ingesta y normalización automáticas; deduplicación / `identity`; scoring
determinista y explicable; asignación por empresa/POS con capacidad dinámica,
continuidad y overflow; ciclo de vida con cierre
(`Cerrado`/`Perdido`/`Descartado`) y liberación de capacidad; extracción IA
(prompt **V8**, schema **v1**) con validación de evidencia; proveedores
OpenRouter y Groq (remotos) y Ollama local; análisis bajo demanda; Ollama local
desde el navegador (**experimental**); aislamiento multiempresa; presentación de
nombres; deployment en Render con PostgreSQL gestionado (Supabase).

### Observación real: evidencia literal pero no siempre adecuada

En la prueba, el modelo extrajo correctamente
`model_interes = "Bajaj Boxer CT 100"`, pero eligió como evidencia una frase del
cliente que **no justifica** ese campo (`"Tengo 1 palos de inicial"`). El
validador **sí** comprueba que la evidencia sea una cita **literal del cliente**,
pero **no** valida por completo que sea **semánticamente adecuada** para el
campo. Se documenta como **mejora futura** (no es un bug crítico; en esta versión
**no** se modifica el prompt V8 ni el validador).

### Futuro / no implementado

Mejoras **futuras** (hoy **no** implementadas; se listan como hoja de ruta):
aumentar capacidad/cuota del proveedor, usar modelos con mayor disponibilidad,
**cola de trabajos**, procesamiento asíncrono, **reintentos con backoff**,
monitoreo de consumo/cuota, métricas de
calidad de extracción, evaluación automática de modelos, **fallback entre
proveedores**, automatización periódica de análisis, **mejoras del validador de
evidencia** (adecuación semántica de la cita), mayor **cobertura de pruebas de
extracción**, **observabilidad** y un uso más robusto de **IA local**.

### Ollama local desde el navegador (experimental, opcional)

Existe una **ruta experimental/alternativa** para usar Ollama del equipo del
usuario **desde el navegador** (ver la sección de IA). No es necesaria para usar
la aplicación: **producción funciona con proveedores remotos** (OpenRouter/Groq).
La detección depende del **navegador, CORS (`OLLAMA_ORIGINS`) y la configuración
local**; requiere Ollama instalada y ejecutándose en el equipo del usuario y
**no debe exponerse públicamente**. No se garantiza su funcionamiento en todos
los navegadores/redes (p. ej. *Private Network Access* en Chromium puede
bloquear HTTPS → localhost).
