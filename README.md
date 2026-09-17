# Analista IA

Sistema para priorizar la gestión diaria de leads comerciales de tres empresas
comercializadoras de motos. Recibe leads de tres canales (WhatsApp, Meta Ads y
Formulario Web), cruza esa información con las conversaciones de WhatsApp y
genera una lista diaria de trabajo con una prioridad explicable para cada lead.

Responde una sola pregunta operativa:

> ¿Qué leads debería gestionar hoy cada asesor y por qué?

## En pocas palabras

Analista IA ayuda a un equipo comercial con muchos leads y varias empresas a
decidir qué atender primero. Los leads llegan por WhatsApp, Meta Ads y Formulario
Web; la IA lee las conversaciones de WhatsApp y extrae señales (modelo,
intención, presupuesto, cuota inicial, forma de pago, objeciones, cita,
cotización) respaldadas por una cita del cliente. El scoring es determinista y
explicable: convierte esas señales y los datos del CRM en una prioridad Alta,
Media o Baja, y funciona aunque un lead no tenga conversación. Cada asesor ve su
lista del día ordenada y solo los leads de su empresa y punto de venta.

## El problema

- Llegan muchos leads y por canales distintos.
- Los datos vienen de fuentes diferentes y con formatos inconsistentes.
- Hay registros duplicados o incompletos (teléfonos repetidos, emails vacíos,
  fechas ambiguas).
- Parte de la información importante está en las conversaciones de WhatsApp y no
  siempre termina estructurada en el CRM.
- Con esa base, es difícil decidir qué leads atender primero.
- Conviven tres empresas comercializadoras y varios puntos de venta que no deben
  mezclar su información.

## Qué hace el sistema

El recorrido de un lead es:

```text
datos (leads, conversaciones, catálogo, asesores)
  → normalización
  → detección de duplicados
  → asociación de conversaciones
  → análisis de IA (opcional, por conversación)
  → validación de evidencia
  → cálculo de prioridad
  → asignación a asesores
  → gestión diaria
  → cierre y liberación de capacidad
```

Cada paso hace lo siguiente:

- **Ingesta y normalización**: carga los archivos originales, unifica formatos de
  teléfono, email, ciudad y modelo, y guarda el dato original junto al
  normalizado.
- **Detección de duplicados (`identity`)**: agrupa registros que parecen ser la
  misma persona usando reglas deterministas (teléfono/email exactos, nombre
  similar, nombre + ciudad). Marca un registro como canónico y deja los demás
  como miembros del grupo.
- **Asociación de conversaciones**: enlaza cada conversación de WhatsApp con su
  lead cuando existe una llave fiable. Las conversaciones huérfanas se conservan
  pero no se fuerzan a un lead.
- **Análisis de IA**: lee la conversación y propone señales estructuradas (ver
  más abajo). Es opcional: si no hay conversación o no se ejecuta, el lead sigue
  su curso.
- **Validación de evidencia**: el sistema comprueba que cada valor propuesto
  esté respaldado por una cita literal del cliente. Lo que no cumple se descarta.
- **Cálculo de prioridad (scoring)**: con reglas deterministas convierte la
  información disponible en un puntaje y una banda.
- **Asignación**: reparte los leads entre los asesores de la misma empresa y
  punto de venta, según su capacidad.
- **Gestión diaria**: el asesor ve sus leads de hoy ordenados; el supervisor ve
  los de su empresa, incluidos los que quedaron sin cupo.
- **Cierre**: el lead se marca Cerrado, Perdido o Descartado, y su cupo se libera
  para el siguiente ciclo.

El pipeline completo se ejecuta con uno o dos comandos:

```bash
uv run pipeline        # pipeline sin IA
uv run pipeline-ai     # pipeline con IA (solo conversaciones pendientes)
```

## Dónde se usa la IA

La IA se usa para una sola cosa: interpretar conversaciones de WhatsApp y
convertir texto libre en información estructurada. No decide a quién vender ni
modifica el CRM.

De cada conversación puede extraer ocho campos:

| Campo | Qué representa |
|---|---|
| `model_interes` | Modelo de moto mencionado por el cliente. |
| `presupuesto` | Límite o rango de presupuesto declarado por el cliente. |
| `cuota_inicial` | Monto que el cliente declara tener o aportar como inicial. |
| `forma_pago` | Forma de pago que el cliente declara. |
| `intencion_compra` | Alta, media, baja o informativa. |
| `objecion` | Barrera o resistencia expresada por el cliente. |
| `solicitud_cita` | Si el cliente pidió o aceptó una visita. |
| `solicitud_cotizacion` | Si el cliente pidió o aceptó una cotización. |

Reglas que aplica el sistema:

- Cada valor viaja junto a su **evidencia**: una cita literal de un mensaje del
  **cliente**.
- Los mensajes del asesor sirven como contexto para entender la conversación,
  pero no cuentan como evidencia de un dato del cliente.
- La IA no debe inventar. Si no hay evidencia del cliente, el campo queda vacío
  (`null`).
- Antes de guardar, el sistema valida la evidencia de forma determinista
  (`app/ai/validation.py`). Acepta la cita si corresponde a un mensaje del
  cliente, tolerando mayúsculas, acentos, espacios y puntuación. En los campos
  monetarios exige además que la cita contenga el monto. Lo que no cumple se
  anula y no llega al scoring.

En resumen: la IA interpreta la conversación; el sistema valida y decide qué se
guarda. La gestión sigue bajo control del sistema y del equipo comercial.

## IA y prioridad son cosas distintas

Conviene separar dos conceptos que suenan parecidos:

- **IA**: interpreta la conversación y obtiene señales.
- **Scoring**: aplica reglas deterministas y explicables para convertirlas en una
  prioridad.

La prioridad **no depende únicamente de la IA**. Un lead puede tener un score
calculado aunque todavía no tenga análisis de conversación, porque el sistema usa
también datos que ya están en el CRM (estado de gestión, antigüedad, teléfono,
email, ciudad, modelo de catálogo, precio). Cuando existe análisis de IA, esas
señales enriquecen el cálculo.

Por eso es normal encontrar en el dashboard leads con prioridad pero sin
extracción de IA.

## Cómo se calcula la prioridad

El scoring es determinista y explicable: los mismos datos producen siempre el
mismo resultado. No es aprendizaje automático y no predice ventas. Tampoco usa el
histórico de cierres.

El cálculo se separa en tres dimensiones:

| Dimensión | Qué mide | Cómo se usa |
|---|---|---|
| Comercial | Intención, cita, cotización, presupuesto, cuota, forma de pago, objeción y precio del modelo. | Define la banda de prioridad. |
| Urgencia | Estado de gestión y antigüedad del lead. | Ajusta el orden del día. |
| Calidad del dato | Completitud (teléfono, modelo, email, ciudad, fecha confiable). | Se muestra aparte y **no** modifica el orden. |

El orden de la cola es `0.7 · comercial + 0.3 · urgencia`. La banda de prioridad
se calcula sobre el puntaje comercial:

- **Alta**: 70 o más.
- **Media**: entre 45 y 69.
- **Baja**: menos de 45.

Los pesos y los cortes son decisiones de diseño orientadas al negocio, no
resultados de aprendizaje automático. Se le da más peso a la dimensión comercial
(0,7) porque la pregunta operativa es qué oportunidad merece atención; la
urgencia (0,3) complementa, para que un lead antiguo o sin gestión no quede
relegado en la cola. Los cortes (70 y 45) son umbrales de calibración del sistema,
no probabilidades de conversión.

Cada score guarda sus razones (código, dimensión, texto y contribución) y una
copia de los parámetros usados, de modo que el resultado se puede reconstruir y
explicar. En el detalle del lead se ve la prioridad comercial y la urgencia por
separado de la calidad del dato.

## Los datos del reto

- `leads.csv`: 1.503 filas con 1.501 `lead_id` únicos (hay 2 duplicados exactos).
- `conversaciones.json`: 677 conversaciones de WhatsApp, 4.310 mensajes.
  665 conversaciones enlazan con un lead y 12 no; 25 leads tienen más de una
  conversación.
- `catalogo_motos.csv`: 24 modelos.
- `asesores.csv`: 42 asesores en 15 puntos de venta de 3 empresas.
- `historico_cierres.csv`: 2.200 cierres históricos.

El histórico de cierres (2.200 registros) se auditó y se decidió no usarlo como
predictor individual de un lead actual. La razón principal es que no existe una
llave fiable que lo relacione con los leads vigentes (`LD-*` frente a `HX-*`).
Además, algunas variables del histórico, como el tiempo hasta el primer contacto
o el número de contactos, ocurren después del ingreso del lead y podrían
introducir filtración de información (leakage) si se usaran como entrada al
priorizar. En una evolución futura sí podría aprovecharse de forma agregada, por
ejemplo para estudiar o calibrar pesos por modelo, canal, rango de precio o
empresa, separando el periodo de análisis y evitando el leakage.

## CRM y conversación pueden no coincidir

El CRM guarda el dato operativo registrado. La IA aporta una señal independiente
obtenida de la conversación. El sistema **no sobrescribe** el CRM con lo que dice
la IA.

Si ambos difieren, conserva los dos datos y muestra la discrepancia para que una
persona la revise. Un caso real de la prueba:

```text
CRM:          Honda Navi
Conversación: Bajaj Boxer CT 100
```

La diferencia se muestra como "inconsistencia detectada"; no se trata
automáticamente como un error.

## Leads sin conversación

No todos los leads tienen una conversación disponible, y eso es normal: solo
WhatsApp tiene transcripciones. En ese caso el sistema no inventa datos ni
ejecuta una extracción que no existe. El lead sigue dentro del sistema, mantiene
sus campos de IA como desconocidos y puede recibir prioridad con los datos que sí
tiene. Si más adelante aparece una conversación, se puede analizar.

## Separación por empresa

El sistema está preparado para tres empresas comercializadoras y sus puntos de
venta. Cada lead pertenece a una empresa y a un punto de venta, y esa relación se
valida tanto al normalizar como en la base de datos, de modo que no se creen
asociaciones inválidas.

El aislamiento se aplica en el servidor a partir del usuario autenticado, nunca
desde el navegador:

- **Asesor**: solo ve sus propios leads asignados. No accede a supervisión.
- **Supervisor**: solo ve su empresa, incluidos los leads sin cupo.
- **Admin**: ve todo, con filtros por empresa, punto de venta o asesor.

Para el negocio esto significa que la información de cada comercializadora se
mantiene separada y que un asesor no puede ver leads de otra empresa ni de otro
punto de venta.

## Ciclo de vida del lead

Los estados abiertos son:

- Sin gestión
- Contactado
- No contesta
- Cotización enviada
- En proceso

Los estados terminales son:

- **Cerrado**: la oportunidad terminó en conversión (venta).
- **Perdido**: era una oportunidad válida pero no se convirtió.
- **Descartado**: el lead no debía continuar como oportunidad comercial.

`Perdido` y `Descartado` no son lo mismo y no se deben mezclar, porque afectan
distinto las métricas comerciales.

El cierre se hace desde el detalle del lead (`POST /leads/{lead_id}/status`, con
un motivo). Registra la fecha y el motivo de cierre, y nunca borra el lead ni su
historial. Un lead terminal no se reabre y no vuelve a ser candidato de
asignación. Al cerrarse libera su cupo, que puede reasignarse a un lead del mismo
grupo que había quedado sin capacidad.

## Gestión diaria

- **Asesor** (`/`): "Mis leads de hoy" ordenados por prioridad, con modelo,
  estado, banda, score y el detalle de por qué.
- **Supervisión** (`/supervision`): leads asignados de su empresa con filtros por
  empresa, punto de venta y asesor. Incluye la sección **Pendientes de
  asignación** para los leads que quedaron sin cupo, con su motivo
  (`sin_capacidad`), y contadores por estado.
- **Reintentar asignación**: supervisor y admin pueden relanzar el reparto con el
  mismo algoritmo. Es idempotente: si nada cambió, no reescribe.
- **Análisis de IA bajo demanda**: desde supervisión se pueden analizar las
  conversaciones pendientes.

La asignación es determinista y respeta siempre empresa y punto de venta; nunca
mueve un lead a otro punto de venta y solo usa asesores activos. El cupo de un
asesor es su capacidad diaria menos los leads abiertos que ya tiene asignados, así
que cerrar leads libera cupo. Un lead abierto que ya tiene asesor lo conserva en
las siguientes corridas.

## Arquitectura

La aplicación es un único servicio web:

- **Python 3.11** con **uv** para entorno y dependencias.
- **FastAPI** con plantillas **Jinja2** (HTML generado en el servidor).
- **PostgreSQL** con **SQLAlchemy 2** y **Alembic** (driver `psycopg` 3).
- **Módulo de IA** con una interfaz común de proveedor, de modo que el pipeline no
  depende de un proveedor concreto.
- **Autenticación por roles** (asesor, supervisor, admin) con sesión firmada.

```text
Navegador
  → FastAPI (app/dashboard.py, app/auth.py)
      → pipeline de datos (app/pipeline, app/ingestion, app/canonical,
                           app/identity)
      → scoring (app/scoring)
      → asignación (app/assignment)
      → IA (app/ai)
  → PostgreSQL (SQLAlchemy + Alembic)
```

No se usan agentes autónomos, RAG, bases vectoriales, LangChain/LangGraph,
aprendizaje automático ni microservicios.

## Base de datos

Los grupos principales de tablas:

- **leads**: el lead normalizado, con sus datos originales, su estado y su cierre.
- **conversations**: las conversaciones y sus mensajes, enlazadas al lead cuando
  corresponde.
- **catalog_items**: el catálogo de modelos y precios.
- **companies**, **points_of_sale**, **advisors**, **users**: la organización
  (empresas, puntos de venta, asesores y usuarios de la aplicación).
- **identity_clusters** e **identity_members**: los grupos de duplicados y el
  registro canónico de cada grupo.
- **ai_extractions**: cada análisis de IA, con su proveedor, modelo, versiones,
  resultado, evidencia y estado.
- **lead_scores**: el score vigente de cada lead, con sus razones y parámetros.
- **assignments**: el reparto diario por lead, asesor, empresa y punto de venta.
- **pipeline_runs**: cada ejecución del pipeline y sus resultados.

Las versiones del esquema se gestionan con migraciones de Alembic.

## Seguridad

- **Autenticación** con contraseñas guardadas como hash PBKDF2-SHA256 (nunca en
  texto plano) y sesión firmada con HMAC-SHA256.
- **Sesión en cookie** `HttpOnly` y `SameSite=Lax`, con `Secure` activado en
  producción (HTTPS obligatorio). Solo guarda el identificador de usuario y su
  expiración; la identidad y el rol se cargan desde la base de datos.
- **Separación por empresa**: como se describió antes, se aplica en el servidor y
  no depende de lo que envíe el navegador. Consultar un lead fuera del alcance
  devuelve 404/403.
- **Variables sensibles fuera del repositorio**: `.env` no se versiona y
  `.env.example` solo contiene valores de ejemplo.
- **Claves de IA**: en los proveedores remotos (OpenRouter, Groq) la clave vive en
  el servidor y no se envía al navegador. La ruta de Ollama local desde el
  navegador no usa claves de proveedores remotos.

Los formularios que cambian estado (cierre de lead, reintento de asignación,
análisis de IA) usan `POST` y verifican la sesión, pero no incluyen un token CSRF
propio. Está documentado como limitación en la sección de limitaciones.

## Proveedores de IA

El módulo de IA soporta varios proveedores intercambiables:

- **OpenRouter** (remoto, API).
- **Groq** (remoto, API compatible con OpenAI).
- **Ollama** (`ollama`): habla directo con un Ollama local, útil en desarrollo.
- **Proveedor `local`**: es una variante de desarrollo que también usa Ollama en
  el mismo equipo. No es un sistema distinto: reutiliza el mismo adaptador, con su
  propio modelo (`LOCAL_AI_MODEL`) y mensajes de disponibilidad más claros. El
  backend habla directo con Ollama y no necesita el agente local.

Para los proveedores remotos se configura la clave y el modelo por variables de
entorno (`OPENROUTER_API_KEY`/`OPENROUTER_MODEL` o `GROQ_API_KEY`/`GROQ_MODEL`).
En producción solo se admiten proveedores remotos; si falta la configuración, la
aplicación falla al arrancar con un mensaje claro y sin exponer valores.

Rendimiento y límites:

- No se garantiza la disponibilidad de ningún modelo concreto. Los proveedores
  gratuitos pueden responder `HTTP 429` (límite de solicitudes).
- Si una conversación falla, se registra el error y se puede reintentar. El
  reintento es idempotente: no duplica la conversación ni la extracción.
- El modelo es configurable y los resultados dependen del modelo usado.

Ollama local también puede usarse como alternativa experimental para desarrollo.
Existe una ruta opcional en la que el navegador detecta Ollama en el equipo del
usuario y ejecuta la extracción sin enviar la conversación a un proveedor remoto.
Depende de la configuración local (CORS con `OLLAMA_ORIGINS`) y del navegador
(Private Network Access puede bloquear HTTPS hacia localhost), por lo que puede no
funcionar en todos los equipos. No es necesaria para producción: la instancia
desplegada usa proveedores remotos.

## Procesamiento por tandas pequeñas

El tamaño de las tandas no es una limitación de la arquitectura. Depende de la
capacidad del proveedor y del modelo de IA que se use.

Hoy los recursos disponibles son limitados, y los proveedores o modelos pueden
tener límites de solicitudes, límites de consumo, tiempos de respuesta variables
y límites de procesamiento. Por eso se recomienda analizar en tandas pequeñas:

```text
1 → 2 → 5 → posteriormente aumentar
```

Procesar poco a poco ayuda a:

- no sobrecargar al proveedor;
- detectar errores temprano;
- controlar el consumo de tokens;
- aprovechar el reintento idempotente cuando algo falla;
- verificar la calidad de las extracciones de forma progresiva;
- evitar perder una tanda grande por un fallo puntual.

El sistema no está limitado estructuralmente a tandas pequeñas. Si más adelante
se dispone de un modelo o servicio con mayor capacidad, las tandas pueden crecer
sin cambiar la lógica principal. El ajuste actual responde a los recursos
disponibles, no al diseño del sistema.

## Validación durante el desarrollo

El módulo de IA se probó durante el desarrollo, bastante más allá de la prueba
final de 12 leads.

- **Gold set anotado**: se anotaron 110 conversaciones (selección estratificada,
  no las primeras) contra la conversación original y se compararon tres modelos
  locales (`qwen2.5:3b`, `llama3.2:3b`, `qwen2.5:7b`) sobre las mismas 110, con
  el mismo prompt, schema y validación (880 decisiones de campo). El detalle está
  en `docs/ai-extraction-benchmark.md`.
- **Auditoría de calidad**: sobre la salida real de `qwen2.5:3b` en 10
  conversaciones persistidas (80 decisiones), más un análisis de exposición de las
  677 conversaciones con reglas deterministas (sin IA); ver
  `docs/ai-extraction-quality-audit.md`.
- **Lotes de ajuste del prompt**: alrededor de 50 conversaciones más reprocesadas
  en lotes (piloto y dos tandas) para comparar versiones del prompt (de v2 a v7)
  con Ollama local.
- **Pruebas con proveedores remotos**: un benchmark controlado con Groq
  (`openai/gpt-oss-20b`, 10 conversaciones, 8 evaluadas) y un intento controlado
  con OpenRouter que se topó con el límite del modelo gratuito (0 de 20
  disponibles, con respuestas 429). De ahí salen las reglas de reintento
  idempotente y la recomendación de trabajar por tandas pequeñas.
- **Casos revisados a propósito**: señales positivas (intención, presupuesto,
  cuota inicial, forma de pago, objeción, cita, cotización y modelo) y casos
  negativos que debían quedar en `null`. En particular: que la evidencia del
  asesor no valga como dato del cliente; que el precio de la moto no se confunda
  con presupuesto; que una cuota mensual no se confunda con cuota inicial; y que
  una pregunta del cliente no se convierta por sí sola en intención alta.

Fue trabajo de desarrollo, no una evaluación estadística formal. El gold set se
anotó con apoyo de reglas y revisión del analista, así que los números del
benchmark son útiles sobre todo de forma comparativa entre modelos y no se
presentan como precisión absoluta del negocio.

Sobre las extracciones visibles en la instancia pública: la base desplegada
muestra pocas extracciones porque el procesamiento masivo de IA no quedó
ejecutado ni sincronizado en la instancia pública antes del cierre, ya que
dependía de las cuotas y los tiempos del proveedor. No significa que la IA no se
haya probado. Las ejecuciones visibles son una muestra pequeña frente a las
pruebas de desarrollo.

## Prueba controlada final con Ollama

Como cierre se hizo una prueba pequeña y acotada con Ollama local (`qwen2.5:3b`)
sobre 12 leads seleccionados:

- Solo 2 tenían conversación. Esos 2 se procesaron correctamente (2 exitosos, 0
  errores) y quedaron guardados en PostgreSQL con la lógica existente (validación,
  vigencia y recálculo del score).
- Los otros 10 no tenían conversación, así que no se procesaron. Esto también
  confirmó que el sistema no inventa conversaciones ni extracciones.
- `LD-01085` cambió de forma clara su score por señales reales de la conversación
  (intención alta, cuota inicial y solicitud de visita): pasó de banda Baja
  (comercial 21.16 / urgencia 60 / cola 32.81) a Alta (comercial 71.16 / urgencia
  100 / cola 79.81).
- `LD-00214` permitió detectar un modelo distinto al registrado en el CRM; el
  score no cambió porque el resto de señales no fue suficiente.

En `LD-01085` se vio además una limitación real del modelo: extrajo bien
`model_interes = "Bajaj Boxer CT 100"`, pero eligió como evidencia una frase del
cliente que no justifica ese campo (`"Tengo 1 palos de inicial"`). La cita era
literal y pertenecía al cliente, así que la validación la acepta, pero no era la
mejor evidencia semántica para el campo. El validador comprueba que la evidencia
sea literal y del cliente; todavía no comprueba del todo que sea la más adecuada
para el campo. Queda como observación de calidad y mejora futura, no como error
crítico.

## Presentación de nombres

Los nombres de cliente se muestran de forma consistente con
`app/presentation.display_name`, expuesto como filtro de Jinja2. Es solo
presentación:

- no modifica la base de datos ni el valor original, y no agrega columnas ni
  migraciones;
- conserva tildes y caracteres Unicode;
- quita espacios externos y colapsa espacios repetidos;
- normaliza palabras que están completamente en mayúsculas o completamente en
  minúsculas, y deja intacta la capitalización mixta;
- no usa IA.

En la auditoría de la base de datos de desarrollo, 329 de 1.501 nombres (21,9%)
cambian de formato visual. Esto no es deduplicación: la deduplicación (`identity`)
usa su propia normalización y no cambió (43 grupos y 86 miembros).

## Ejecutar en local

Requisitos: [uv](https://docs.astral.sh/uv/) y un PostgreSQL accesible (puede ser
el del `docker-compose.yml` del proyecto).

```bash
uv sync
cp .env.example .env          # Windows: Copy-Item .env.example .env
docker compose up -d db       # PostgreSQL local opcional
uv run alembic upgrade head   # migraciones
uv run python -m app.seed     # datos maestros y usuarios demo
uv run uvicorn app.main:app --reload
```

- Aplicación: http://127.0.0.1:8000/
- Salud: http://127.0.0.1:8000/health

Atajo de desarrollo (entorno, migraciones y servidor; no borra datos):

```bash
uv run dev
```

Usuarios demo (solo desarrollo):

```text
advisor.demo@motos.local    / demo-asesor-123       → sus leads
supervisor.demo@motos.local / demo-supervisor-123   → su empresa
admin.demo@motos.local      / demo-admin-123        → global
```

Variables de entorno principales (todas en `.env`):

| Variable | Para qué sirve |
|---|---|
| `APP_ENV` | `development` o `production`. |
| `SECRET_KEY` | Firma de la sesión. En producción debe ser un valor real. |
| `DATABASE_URL` | URL de PostgreSQL. |
| `PORT` | Puerto del servidor. |
| `AI_PROVIDER` | `ollama`, `local`, `openrouter` o `groq`. |
| `AI_TIMEOUT_SECONDS` | Tiempo máximo de espera por llamada de IA. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Ollama local. |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` | OpenRouter. |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_BASE_URL` | Groq. |
| `LOCAL_AI_MODEL`, `LOCAL_AI_OLLAMA_URL` | Proveedor `local`. |
| `ADVISOR_DEMO_*`, `SUPERVISOR_DEMO_*`, `ADMIN_DEMO_*` | Usuarios demo. |

Para generar un `SECRET_KEY` real:

```bash
uv run python -c "from app.auth import fresh_secret; print(fresh_secret())"
```

En el pipeline, `--ai-limit` acota cuántas conversaciones se analizan en una
corrida:

```bash
uv run pipeline-ai --ai-limit 100
```

## Pruebas

```bash
uv run pytest         # 568 pruebas
uv run alembic check  # sin cambios de esquema pendientes (requiere BD)
```

Estado actual: 568 pruebas, 568 aprobadas, 0 fallidas, 0 omitidas.

Las 568 pruebas se ejecutan sin PostgreSQL y sin proveedores externos de IA. No
son 568 pruebas de IA: cubren distintas áreas del sistema.

- ingesta y normalización;
- deduplicación e identidad;
- IA y validación de evidencia;
- scoring;
- asignación y capacidad;
- ciclo de vida del lead;
- autenticación y roles;
- aislamiento por empresa;
- interfaz y presentación.

Entre los casos críticos están que la evidencia deba pertenecer al cliente, el
aislamiento entre empresas, la idempotencia de los procesos, la asignación con
capacidad y overflow, y el manejo de errores y reintentos de IA. El número de
pruebas es un dato, no una medida de calidad por sí mismo.

## Migraciones

```bash
uv run alembic upgrade head
```

Al agregar columnas o constraints se crea una revisión de Alembic; no se dejan
migraciones vacías. `uv run alembic check` debe reportar que no hay cambios
pendientes.

## Despliegue

El despliegue está preparado para **Render** con runtime Docker
(`render.yaml` + `Dockerfile`) y una base **PostgreSQL externa** (Render, Neon,
Supabase, etc.). El contenedor ejecuta `alembic upgrade head` antes de arrancar
`uvicorn`.

Producción requiere una base de datos externa y un proveedor remoto de IA
configurado. Variables necesarias:

| Variable | Descripción |
|---|---|
| `APP_ENV` | `production`. |
| `SECRET_KEY` | Secreto real (Render puede generarlo). La aplicación falla al arrancar si es un valor inseguro. |
| `DATABASE_URL` | URL de PostgreSQL (`postgresql+psycopg://...`). |
| `AI_PROVIDER` | `openrouter` o `groq` (Ollama/local no está permitido). |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` | Si se usa OpenRouter. |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_BASE_URL` | Si se usa Groq. |

Comportamiento en producción:

- Las cookies de sesión se emiten con `Secure` (requiere HTTPS).
- `/health` responde `{status, database, ai_provider}` y no expone secretos ni la
  `DATABASE_URL`.

## Documentación

- `docs/data-audit.md`: auditoría reproducible de los datasets.
- `docs/technical-design.md`: diseño técnico y funcional.
- `docs/scoring-design.md`: diseño del scoring explicable.
- `docs/ai-extraction-benchmark.md`: pruebas comparativas de extracción con IA.
- `docs/ai-extraction-quality-audit.md`: auditoría de calidad de la extracción.

## Limitaciones actuales

- **Capacidad de IA**: los proveedores gratuitos o locales tienen cuota, límites
  de solicitudes y disponibilidad variable. Por eso se recomienda procesar en
  tandas pequeñas.
- **Tiempos variables**: la latencia de cada llamada cambia según el proveedor y
  el modelo.
- **Recursos limitados**: el procesamiento es secuencial, sin colas ni workers.
- **Extracciones en la instancia pública**: hay pocas visibles porque el
  procesamiento masivo de IA no se ejecutó ni sincronizó allí antes del cierre; no
  refleja el volumen de las pruebas de desarrollo.
- **Ollama local**: es una alternativa experimental, dependiente de la
  configuración del equipo y del navegador.
- **Resultados según el modelo**: la calidad de la extracción depende del modelo
  usado; no se garantiza ningún modelo concreto.
- **Validación de evidencia**: comprueba que la cita sea literal y del cliente,
  pero no valida del todo que sea la más adecuada para el campo.
- **Diferencias CRM/IA**: algunas discrepancias requieren revisión humana.
- **Seguridad pendiente**: los formularios que cambian estado no incluyen un token
  CSRF propio (la cookie es `SameSite=Lax`, lo que cubre el caso común de POST
  entre sitios) y el login no tiene límite de intentos. Ambas cosas quedan como
  mejora de seguridad pendiente.
- **Histórico de cierres**: no es un predictor individual (no hay llave con los
  leads actuales).
- **Fechas ambiguas**: los formatos `DD/MM` y `MM/DD` no se adivinan; se marcan
  como no confiables y no alimentan la urgencia.

## Mejoras futuras

Nada de esta sección está implementado hoy. Se lista como posibles siguientes
pasos.

### Procesamiento de IA

- Aumentar el tamaño de las tandas cuando haya más capacidad.
- Procesamiento automático en segundo plano.
- Colas de trabajo si el volumen crece.
- Reintentos automáticos con espera creciente (backoff) ante límites del
  proveedor.
- Alternar entre proveedores (fallback) cuando uno falla.
- Monitoreo del consumo y de los límites.

### Calidad de IA

- Métricas periódicas de calidad.
- Conjuntos de evaluación más grandes.
- Comparación entre modelos.
- Seguimiento de los errores de extracción.
- Validaciones de evidencia más avanzadas (adecuación semántica de la cita).
- Mayor cobertura de pruebas de extracción.

### Operación

- Mayor observabilidad.
- Métricas de procesamiento.
- Alertas.
- Seguimiento del consumo y del costo de IA.
- Automatización de nuevos ciclos de procesamiento.

### Seguridad

- Token CSRF en los formularios que cambian estado.
- Límite de intentos en el login (rate limiting).

### Escalabilidad

El sistema funciona hoy como una aplicación integrada. Si el volumen creciera
mucho, se podrían incorporar componentes adicionales como procesamiento en
segundo plano o colas de trabajo. Esos componentes no existen todavía.

## Estado actual

El proyecto está funcional y listo para demostración. Hoy funcionan:

- carga y normalización de datos;
- detección de duplicados;
- asociación de conversaciones;
- análisis de IA bajo demanda y extracción estructurada con validación de
  evidencia;
- scoring determinista y explicable;
- asignación por empresa y punto de venta, con capacidad dinámica y overflow;
- gestión diaria (asesor y supervisor) y ciclo de vida con cierre;
- presentación de la información en la interfaz web;
- separación de la información por empresa;
- despliegue en Render con PostgreSQL gestionado.

El módulo de IA está implementado y se probó durante el desarrollo (gold set,
auditoría de calidad y pruebas con proveedor remoto). Su calidad depende del
modelo utilizado, y las extracciones visibles en la instancia pública son una
muestra pequeña, no el total de lo probado.

## Autoría

Desarrollado originalmente por **Emilson Oviedo Cardona** para una evaluación
técnica de Analista IA (septiembre de 2026). Repositorio original:
https://github.com/SlingerByte/analista-ai. Ver `AUTHORS.md`.
