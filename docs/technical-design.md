# Diseño técnico — Priorización diaria de leads

Documento de diseño. **No contiene implementación**: describe qué se va a construir,
por qué y con qué criterios. Se apoya en los hallazgos reales de `docs/data-audit.md`
y `reports/audit_summary.json`.

---

## 1. Problema y objetivo

La empresa comercializa motos a través de tres empresas (`EMP-01`, `EMP-02`, `EMP-03`)
y 15 puntos de venta. Los leads llegan por tres canales (`WhatsApp`, `Meta Ads`,
`Formulario Web`) y se atienden de forma manual. El objetivo es que cada día cada
asesor reciba una **lista corta, ordenada y explicable** de leads a gestionar.

La solución debe responder, para cada usuario, una sola pregunta:

> ¿Qué leads debo gestionar hoy y por qué?

Todo lo demás (extracción de conversaciones, histórico, métricas) existe para
alimentar esa decisión, no como fin en sí mismo.

### Restricciones del ejercicio

- 5 días, ~10–12 horas de trabajo real.
- Una solución **terminada, clara y defendible** supera a una sobre-arquitecturada.
- No se modifica nada en `data/`.
- No se inventan relaciones entre datasets.
- No se oculta ambigüedad ni se fabrica confianza de la IA.
- Sin leakage.

---

## 2. Principios derivados del audit

Cinco hechos del audit condicionan el diseño. No son supuestos, están medidos:

1. **No hay llave individual entre leads actuales e histórico.** La intersección de
   `lead_id` es **0** (prefijos `LD-` vs `HX-`). El histórico se usa solo para
   tasas agregadas, nunca para joins por nombre o teléfono.
2. **El desenlace histórico está muy desbalanceado y es casi uniforme por segmento.**
   `Cerrado` 197 / 2.200 (8,95%). Conversión ajustada (excluyendo `Sin gestión`):
   WhatsApp ~10,4%, Meta Ads ~8,7%, Formulario Web ~9,7%; por empresa ~9,2%–10,5%.
   Es decir, **el histórico discrimina poco**. Por eso no se construye un modelo ML
   complejo ni se usa como predictor: queda como fuente de patrones agregados,
   planeación de capacidad y línea base.
3. **Hay leakage claro en el histórico.** `horas_al_primer_contacto` es nulo y
   `numero_contactos` es 0 exactamente para los 179 `Sin gestión`. El momento de
   captura de `manifesto_cuota_inicial`, `forma_pago_declarada` y `pidio_cita` no
   está confirmado. Ninguno de esos campos se usa como predictor.
4. **La calidad de datos es irregular pero acotada.** 2 filas exactas duplicadas,
   265 fechas ambiguas, 487 sin fecha de contacto, 140 teléfonos compartidos,
   93 posibles clientes repetidos, 80 modelos faltantes, 115 modelos ambiguos.
   El diseño debe **conservar el dato original** y marcar la incertidumbre.
5. **Solo WhatsApp tiene transcripciones.** 677 conversaciones, 665 con match,
   12 huérfanas, 861 leads sin conversación. La IA enriquece solo donde hay texto,
   y un lead sin conversación sigue siendo priorizable con el score inicial.

---

## 3. Arquitectura general

Arquitectura de **una sola aplicación** (monolito modular) con base de datos
relacional y un único punto de entrada automatizable. Nada de microservicios,
agentes, colas ni orquestadores.

```
                         ┌──────────────────────────── fuentes ────────────────────────────┐
                         │  data/leads.csv · conversaciones.json · catalogo_motos.csv        │
                         │  asesores.csv · historico_cierres.csv   (solo lectura)            │
                         └───────────────────────────────┬──────────────────────────────────┘
                                                         │
                                   ┌─────────────────────▼─────────────────────┐
                                   │  ÚNICO DISPARADOR                          │
                                   │  scheduler (cron) ──► endpoint autenticado │
                                   │  o CLI  `pipeline run`                     │
                                   └─────────────────────┬─────────────────────┘
                                                         │
   ┌─────────────┐   ┌──────────────┐   ┌───────────────▼┐   ┌──────────────┐   ┌───────────────┐
   │ 1. Ingesta  │──►│ 2. Normaliz. │──►│ 3. Dedupe +    │──►│ 4. Extracc.  │──►│ 5. Scoring    │
   │  hashing    │   │  raw/norm    │   │  enlace convs  │   │  IA (JSON)   │   │ inicial+enriq.│
   └─────────────┘   └──────────────┘   └───────────────┘   └──────────────┘   └───────┬───────┘
                                                         ┌────────────────────────────▼───────┐
                                                         │ 6. Asignación a asesores por       │
                                                         │    empresa / punto / capacidad      │
                                                         └────────────────────────────┬───────┘
                                                                                      │
                                            ┌─────────────────────────────────────────▼───────┐
                                            │ PostgreSQL (company_id + RLS parcial)           │
                                            │ + FastAPI (backend + render Jinja2)             │
                                            └─────────────────────────────────────────┬───────┘
                                                                                      │
                                                                      ┌───────────────▼───────────────┐
                                                                       │ Lista diaria / dashboard       │
                                                                       │ (cola, detalle, métricas)      │
                                                                      └───────────────────────────────┘
```

### Stack propuesto (mínimo, justificado)

| Capa | Elección | Por qué |
|---|---|---|
| Lenguaje | Python 3.11+ | Ya hay un audit en Python; sin cambio de ecosistema. |
| Web/API | FastAPI | Sirve el dashboard renderizado y expone el disparador con auth. Un solo proceso. |
| Vistas | Jinja2 + HTML server-side (HTMX opcional) | Evita compilar un SPA; suficiente para una tabla del día y un detalle. HTMX solo si aporta. |
| DB | PostgreSQL | Operaciones concurrentes y defensa en profundidad con RLS parcial. El aislamiento principal es `company_id` + capa de acceso. SQLite no permite RLS. |
| ORM/migr. | SQLAlchemy + Alembic | Esquema versionado y reproducible. |
| IA | 1 API de LLM con salida JSON estructurada | No hay embeddings ni vector DB en el problema. |
| Scheduler | Cron del proveedor o GitHub Actions | Un solo disparador; no se necesita orquestador. |
| Deploy | Contenedor único + Postgres gestionado | Realista en 5 días, URL pública. |

**Qué NO se usa y por qué**: microservicios, agentes, embeddings/vector DB,
XGBoost/redes, Kafka/Redis/Airflow/Celery. No existe en los datos una necesidad
(volumen, búsqueda semántica, tiempo real, varias colas) que lo justifique.

---

## 4. Flujo de datos de una sola entrada

Un único comando/endpoint ejecuta las etapas en orden. Cada etapa escribe su
resultado y su estado, y puede volver a ejecutarse sin efectos duplicados.

```
fuentes → ingesta → normalización → dedupe → enlace de conversaciones
        → extracción IA → scoring → asignación → lista diaria
```

Cada corrida produce un registro en `pipeline_runs` con el detalle de pasos en
`steps` (JSONB). Si una etapa falla, las anteriores quedan confirmadas y las
posteriores no corren; al re-ejecutar, las etapas idempotentes no repiten trabajo.

La extracción IA **no corre dentro de un request HTTP**: se ejecuta por CLI o como
proceso en background, con estado en `pipeline_runs`, para evitar timeouts. El
endpoint del disparador solo inicia la corrida y responde de inmediato.

---

## 5. Ingesta

### 5.1 Fuente

Los cinco archivos de `data/` se tratan como fuente inmutable. La ingesta:

1. Calcula `sha256` y tamaño de cada archivo y los guarda en `pipeline_runs`.
2. Si el hash ya existe en una corrida anterior, **no reprocesa** el archivo.
3. Guarda el contenido crudo de cada fila en `leads.raw_payload` (JSONB) y un
   `record_hash` para detectar cambios fila a fila. El original sigue en `data/`;
   no se crea una capa de staging aparte.

La ingesta **nunca** escribe en `data/`. El mismo criterio aplica a conversaciones
(`conversations.content_hash` + mensajes en JSONB) y a catálogo/asesores.

### 5.2 Detección de cambios

| Archivo | Unidad de cambio | Clave |
|---|---|---|
| `leads.csv` | fila | `lead_id` + `record_hash` de campos |
| `conversaciones.json` | conversación | `conversacion_id` + hash del contenido |
| `catalogo_motos.csv` | fila | `sku` + hash |
| `asesores.csv` | fila | `asesor_id` + hash |
| `historico_cierres.csv` | fila | `lead_id` (`HX-*`) + hash |

---

## 6. Normalización

Regla central: **el valor original nunca se sobrescribe**. Para cada campo
relevante se conservan cuatro cosas: `raw`, `normalizado`, `método` e indicador
de `calidad/ambigüedad`.

### 6.1 Representación

- La fila canónica de `leads` guarda las columnas normalizadas (para consultar) y
  el `raw_payload` (JSONB) con los valores originales.
- `leads.normalization_meta` (JSONB) guarda, por campo, `raw_value`,
  `normalized_value`, `method`, `is_ambiguous` y `reason`.
- Nada se resuelve "en silencio": si no hay certeza, `normalized_value` queda
  nulo o parcial y `is_ambiguous = true` con un `reason` legible.

### 6.2 Reglas por campo

| Campo | Regla de normalización | Método | Ambigüedad |
|---|---|---|---|
| `telefono` | Quitar no-dígitos; quitar prefijo `57`/`+57` solo si quedan 10 dígitos. Resultado de 10 dígitos. | `phone_canonical` | `true` si longitud ∉ {10} tras prefijo, o si es el caso `300123`. Se conserva el crudo. |
| `email` | `trim` + `lower`. Validación de forma con regex. | `email_canonical` | `true` si no cumple formato; nunca se inventa corrección. |
| `ciudad` | Minúsculas sin acentos, colapsar espacios, mapa de alias **basado en evidencia** (`bogota d.c.→bogota`, `sta marta→santa marta`, `b/quilla→barranquilla`, `rio negro→rionegro`, `cartagena de indias→cartagena`). | `city_canonical` | `true` si no está en el diccionario y no es un alias conocido. |
| fechas | Ver 6.3. | `date_parse` | `true` cuando hay evidencia de mezcla DD/MM y MM/DD. |
| `canal` | Minúsculas sin acentos → `WhatsApp` / `Meta Ads` / `Formulario Web`. | `channel_canonical` | `true` si queda vacío. |
| `estado_gestion` | Mapa de equivalentes (`contactado`, `sin gestión`, `no contesta`, `cotización enviada`, `en proceso`, `descartado`). | `status_canonical` | `true` si no reconoce el valor. |
| marca/modelo | Normalizar marca con typos (`bajai→bajaj`, `hnda→honda`, `heroo→hero`, `suzuky→suzuki`), quitar sufijo de año (`2026`), unificar `A.K.T→AKT`, colapsar espacios. Emparejar contra catálogo por `marca+linea` y por `linea`. | `model_to_sku` | `true` si es solo marca, prefijo ambiguo o no hay match (115 + 80 casos del audit). |
| referencias catálogo | Lista `puntos_venta_disponibles` (pipe-separated) → `catalog_items.availability` (JSONB `{pv: unidades}`). Validar contra `points_of_sale`. | `catalog_split` | `true` si aparece un PV inexistente (el audit no encontró ninguno). |

### 6.3 Fechas (el punto más delicado)

El audit encontró **265** fechas de registro y **216** de primer contacto
realmente ambiguas, además de mezcla de ISO con T, ISO con espacio, `DD-MM-YYYY`
y `MM/DD`/`DD/MM`. La solución **no adivina**:

Por cada fecha se guarda:

```
raw_value           "05/06/2026 10:00"
parsed_date         NULL si ambigua, o la fecha segura
format_detected     "ISO_T" | "ISO_SPACE" | "DD-MM-YYYY" | "MM/DD" | "DD/MM" | "vs"
is_ambiguous        true
ambiguity_reason    "barra con día y mes <= 12; no se puede decidir"
```

Uso posterior:

- Si `is_ambiguous = false` → la fecha se usa en scoring/urgencia.
- Si `is_ambiguous = true` → **no** alimenta urgencia ni antigüedad; el lead se
  marca y se muestra "fecha no confiable". **No se asume `DD/MM` ni `MM/DD`**
  cuando hay ambigüedad: se conserva el valor original, `parsed_date` queda nulo y
  el motivo se guarda en `normalization_meta`.
- El caso imposible `2026-08-33` queda con `parsed_date = null` y `reason` visible.
- Las 29 inconsistencias `contacto < registro` se conservan y se marcan como
  `chronology_flag`, sin corregirlas.

---

## 7. Deduplicación conservadora

Objetivo: **evitar doble gestión** sin borrar nada y sin asumir que un teléfono
compartido implica la misma persona.

### 7.1 Niveles

El scope es **siempre intra-empresa**: nunca se agrupan leads de empresas
distintas, aunque compartan teléfono o email.

| Regla (`rule_id`) | Evidencia | Resultado |
|---|---|---|
| **Ingesta / PK** | Mismo `lead_id` y contenido idéntico. Audit: 2 filas (`LD-00011`, `LD-00251`). | No usa clusters: lo resuelve el upsert por PK. Queda una sola fila canónica. |
| **Fuerte · `PHONE_EMAIL_EXACT`** | Mismo teléfono normalizado **y** mismo email normalizado, ambos presentes. | Cluster `auto`, `match_strength = strong`. Se conservan todos los leads. |
| **Media · `PHONE_NAME_SIMILAR`** | Mismo teléfono normalizado **y** nombre con Jaro-Winkler ≥ 0,90. | Cluster `possible_pending`, `match_strength = possible`. Requiere revisión. |
| **Débil · `NAME_CITY_MATCH`** | Nombre normalizado **y** ciudad normalizada iguales. | Cluster `possible_pending`, `match_strength = weak`. **Nunca** se auto-consolida. |
| **Insuficiente** | Mismo teléfono solo, o email solo, o nombre solo. | No se crea relación. |

**Decisiones explícitas**:
- Un teléfono compartido **por sí solo** no relaciona leads (el audit mostró como
  máximo 2 leads por teléfono y es compatible con un mismo hogar/negocio).
- `status = auto` **solo** cuando todas las relaciones del cluster son fuertes;
  cualquier relación media o débil deja el cluster en `possible_pending`.
- No se calcula un score probabilístico: `identity_clusters.score` queda `NULL` y
  la evidencia se expresa con hechos (`phone_match`, `email_match`,
  `name_similarity`), sin `confidence`.
- El canónico es el `lead_id` mínimo del componente (determinista y estable).
- Componentes por union-find solo entre leads relacionados; no se crean clusters
  para leads aislados.

Implementación: `app/identity/` (`python -m app.identity`, o `python -m app.pipeline`
para ingesta + identidad).

### 7.2 Entidad de identidad

No se fusionan filas. Se modela identidad aparte, con dos tablas:

- `identity_clusters`: `cluster_id`, `company_id`, `canonical_lead_id`, `status`
  (`auto` / `possible_pending` / `reviewed_confirmed` / `reviewed_discarded`),
  `match_strength`, `score`, `matched_rules` (JSONB) y la decisión humana
  (`decided_by`, `decided_at`, `note`). No hay tabla de revisiones aparte.
- `identity_members`: `cluster_id`, `lead_id`, `role` (`canonical`/`member`),
  `rule_id`, `match_strength`, `evidence` (JSONB).

Cada cluster explica **por qué** agrupa: `rule_id` + evidencias concretas. Cada
`identity_member.evidence` guarda, por ejemplo:

```json
{ "rule": "PHONE_EMAIL_EXACT", "phone_match": true, "email_match": true, "name_similarity": null, "related_lead_id": "LD-00123" }
{ "rule": "PHONE_NAME_SIMILAR", "phone_match": true, "email_match": false, "name_similarity": 0.94, "related_lead_id": "LD-00124" }
{ "rule": "NAME_CITY_MATCH", "name_match": true, "city_match": true, "name_similarity": 1.0, "related_lead_id": "LD-00125" }
```

### 7.3 Efecto en la operación

- Un cluster `auto` o `possible_pending` presenta **un solo lead** en la cola
  (el canónico) para no duplicar gestión.
- El detalle del lead muestra todos los miembros y el motivo.
- La decisión humana (confirmar/descartar) actualiza el `status` del cluster. Al
  descartar, todos vuelven a ser priorizables por separado.

---

## 8. Conversaciones

### 8.1 Relación con leads

- Se enlazan por `lead_id`. Si el `lead_id` no existe en `leads`
  (12 huérfanas del bloque `LD-9xxxx`, todas `2026-08-15 11:00:00`), la
  conversación se guarda con `status = orphan` y `lead_id` nulo. **No se reasigna
  artificialmente.** Queda trazable en una vista de administración y el
  `source_lead_id` original se conserva en `pipeline_runs.steps`.
- 25 `lead_id` tienen 2 conversaciones → se conservan **separadas** (nunca se
  fusionan mensajes físicamente), con `conversation_id` y orden cronológico
  preservados. `app/identity/conversations.py::cluster_conversations` devuelve la
  combinación cronológica por cluster para la futura extracción IA.

### 8.2 Consolidación

- `messages` se guarda como arreglo JSONB dentro de `conversations`, con `seq`,
  `sender`, `hora` y texto para cada mensaje.
- La extracción IA se hace **por conversación** (evidencia localizable por `seq`).
- El consolidado por lead **es una vista** (`lead_signal_view`), no una tabla: para
  cada campo toma el valor con mayor jerarquía de estado
  (`explícito > inferido > ambiguo > no mencionado`) y, a igualdad, el más
  reciente, conservando de qué `extraction_id` provino.

### 8.3 Casos

| Caso | Manejo |
|---|---|
| Conversación nueva | Ingesta → link/orphan → extracción → resumen del lead. |
| Conversación repetida (mismo contenido) | Hash igual → se ignora. |
| Conversación huérfana | Se conserva, `status=orphan`, aparece en admin y en métricas. |
| Conversación que cambia | Hash distinto → nueva versión; se re-extrae; la anterior queda histórica. |
| Múltiples por lead | Separadas; el resumen consolida con procedencia. |

---

## 9. Extracción mediante IA

### 9.1 Contrato de salida (por conversación)

```jsonc
{
  "schema_version": "1.0.0",
  "extractor_version": "1.0.0",
  "conversation_id": "CONV-00587",
  "language": "es",
  "fields": {
    "modelo_interes":       { "state": "explicito", "value_text": "Bajaj Pulsar RS 200",
                              "sku_candidato": "SKU-010",
                              "evidence": { "message_seq": 1, "quote": "me interesa la Bajaj Pulsar RS 200" } },
    "presupuesto":          { "state": "ambigua",   "value_text": "no sé, algo económico", "value_num": null },
    "cuota_inicial":        { "state": "no_mencionado" },
    "forma_pago":           { "state": "inferido",  "value_text": "credito",
                              "evidence": { "message_seq": 3, "quote": "financiada" } },
    "intencion_compra":     { "state": "ambigua",   "value_text": "baja" },
    "objecion":             { "state": "explicito", "value_text": "precio",
                              "evidence": { "message_seq": 5, "quote": "estoy mirando otra marca" } },
    "solicitud_cita":       { "state": "no_mencionado" },
    "solicitud_cotizacion": { "state": "explicito", "value_text": "si",
                              "evidence": { "message_seq": 2, "quote": "¿me la puede cotizar?" } }
  },
  "warnings": []
}
```

Reglas del contrato:

- `state` ∈ `{explicito, inferido, ambiguo, no_mencionado}`. **No se pide
  `confidence`**: el estado es la única señal de certeza y no se fabrican números.
- Todo `explicito`/`inferido` debe traer `evidence` (mensaje + cita breve).
  Sin evidencia → se degrada a `ambiguo` o `no_mencionado`.
- `sku_candidato` se valida contra el catálogo; si no existe, se conserva
  `value_text` y se marca `warning`.

### 9.2 Validaciones

- Esquema JSON estricto (pydantic). Respuesta inválida = extracción fallida.
- Valores enumerados (`forma_pago`, `objecion`, `intencion_compra`) contra listas.
- Fechas/números coherentes; nada de texto vacío con `state=explicito`.

### 9.3 Fallback

- Reintentos con backoff (máx. 2) por error transitorio.
- Si sigue fallando: `status = failed`, sin valores fabricados. El lead conserva
  el **score inicial** y se marca `sin_enriquecer`; se reintenta en la próxima corrida.
- Si la respuesta es parcial, se guarda lo válido y lo ausente queda
  `no_mencionado`.

### 9.4 Idempotencia y no reprocesar

- `input_hash = sha256(texto_de_la_conversación + extractor_version + prompt_version)`.
- Índice único `(conversation_id, input_hash)`. Si ya existe con `status=ok`, se
  omite la llamada. Si falló, se permite reintento.
- Si la conversación cambia, cambia el hash → nueva extracción; la anterior queda
  con `is_current = false`.

### 9.5 Versionado

- `ai_extractions` guarda `prompt_version`, `schema_version` y `model_name` como
  columnas. No hay tabla de versiones aparte. Reproducibilidad y auditoría de
  "con qué versión se extrajo esto".

Los ocho campos objetivo del extractor son: `modelo_interes`, `forma_pago`,
`intencion_compra`, `solicitud_cita`, `solicitud_cotizacion`, `objecion`,
`presupuesto` y `cuota_inicial`.

### 9.6 Costo y alcance

- Solo se envían conversaciones de WhatsApp (las 677; 4.310 mensajes).
- Tope de conversaciones por corrida y registro de tokens/tiempo.
- El proveedor/modelo concreto queda como **decisión abierta** (ver §18); el
  contrato no depende de él.

---

## 10. Scoring

El diseño detallado está en `docs/scoring-design.md`. Resumen:

- Dos conceptos separados y visibles: **prioridad comercial** y **urgencia operativa**.
- Dos momentos: **score inicial** (solo datos de llegada) y **score enriquecido**
  (tras la extracción IA).
- Score explicable por componentes; sin caja negra. **El histórico no entra en el
  score**: se usa solo para patrones agregados, capacidad y línea base.
- La urgencia tiene **fallback por `estado_gestion`** y no depende solo de fechas.
- Prohibido usar como predictor: `desenlace`, `horas_al_primer_contacto`,
  `numero_contactos`, `manifesto_cuota_inicial`, `forma_pago_declarada`,
  `pidio_cita` (del histórico) y cualquier variable posterior a la gestión.

---

## 11. Asignación a asesores

Los leads no traen `asesor_id`. Se asigna **después** de priorizar.

Entradas: fecha, empresa, leads candidatos y asesores activos del punto de venta
con su `capacidad_diaria_leads`.

Algoritmo (determinista):

1. Filtrar leads de la empresa: activos, no descartados, no asignados hoy,
   colapsando cada cluster de identidad a su canónico.
2. Agrupar por `punto_venta_id`.
3. Ordenar leads por `queue_score` desc; desempate por `lead_id` asc (determinismo).
4. Asesores del punto: solo `activo = SI`; ordenar por capacidad restante desc y
   `asesor_id` asc.
5. Asignación greedy con cola de prioridad: cada lead va al asesor con más
   capacidad restante; se descuenta 1.
6. Si no hay capacidad: `status = overflow`, `reason = sin_capacidad`. **No se
   desborda a otro punto de venta** por defecto (respeto geográfico).

Casos:

| Situación | Comportamiento |
|---|---|
| Más leads que capacidad | El excedente queda `overflow` y se muestra en el tablero y las métricas. |
| Capacidad sobrante | Los asesores reciben menos; el sistema reporta utilización < 100%. |
| Varios asesores en un punto | Reparto proporcional a la capacidad (greedy por capacidad restante). |
| Asesor inactivo | Excluido (audit: `AS-037`, `AS-040`). |
| Re-ejecución del día | Nueva `assignment_run`; se marca la anterior `is_current=false`. |

Todo dentro de la empresa correspondiente, garantizado en la capa de acceso
(que siempre aplica el contexto de empresa) y con RLS adicional en `assignments`.

---

## 12. Seguridad y separación por empresa

Tres empresas. Cada usuario solo ve su empresa. El aislamiento es real, no un
filtro visual, pero **sin montar RLS en todo el esquema**:

1. **`company_id` obligatorio** en todas las entidades de negocio (FK, no nulo).
2. **Una sola capa de acceso a datos** (repositorio) que siempre aplica el
   contexto de empresa tomado del usuario autenticado. La API **nunca** confía en
   un `company_id` enviado por el cliente.
3. **RLS de PostgreSQL solo como defensa adicional** en tres tablas:
   `leads`, `conversations` y `assignments`. Políticas con
   `current_setting('app.current_company')`; sin contexto, no hay filas.
4. **Autenticación/autorización**: `users` con `company_id` y rol
   (`admin_empresa`, `supervisor`, `asesor`). El asesor, además, solo ve lo asignado.
5. **Frontend**: los filtros son cosméticos; nunca son el control.
6. **Pruebas explícitas**: un usuario de `EMP-01` no puede leer datos de `EMP-02`
   por consulta directa ni por API; y una consulta sin contexto de empresa
   devuelve 0 filas.

`companies`, `points_of_sale`, `advisors`, `leads`, `identity_clusters`,
`conversations`, `assignments` y `users` llevan `company_id` (o lo derivan por FK).
Las conversaciones huérfanas no tienen empresa (no hay lead): quedan visibles solo
para un rol de servicio/admin, no para usuarios de empresa.

**Supuesto documentado**: el catálogo es **global** (los 24 SKU se ofrecen en los
15 PV de las tres empresas). Es lo que respaldan los datos actuales
(`puntos_venta_disponibles` cubre todos los PV). Si negocio confirma que el
catálogo varía por empresa, `catalog_items` necesitaría `company_id`.

---

## 13. Modelo de datos

Esquema mínimo: **13 tablas**. Los datos crudos, los metadatos de normalización,
los pasos del pipeline, la extracción IA y las razones del score viven en columnas
JSONB, no en tablas hijas.

### 13.1 Núcleo multiempresa

| Tabla | Propósito | Clave | Relaciones | Campos críticos |
|---|---|---|---|---|
| `companies` | Catálogo de empresas. | `company_id` | 1—N `points_of_sale`, `users` | `name` |
| `points_of_sale` | Puntos de venta por empresa. | `point_of_sale_id` | FK `company_id` | `name` |
| `users` | Acceso al dashboard con alcance de empresa. | `user_id` | FK `company_id` | `email`, `password_hash`, `role`, `advisor_id` (opcional) |

### 13.2 Catálogo y asesores

| Tabla | Propósito | Clave | Relaciones | Campos críticos |
|---|---|---|---|---|
| `catalog_items` | Producto/SKU (global, supuesto §12). | `sku` | — | `brand`, `line`, `engine_cc`, `segment`, `list_price`, `availability` (JSONB: `{pv: unidades}`) |
| `advisors` | Asesores y capacidad. | `advisor_id` | FK `point_of_sale_id`, `company_id` | `name`, `daily_capacity`, `active`, `start_date`, `raw_fields` (JSONB) |

### 13.3 Operación e ingesta

| Tabla | Propósito | Clave | Campos críticos |
|---|---|---|---|
| `pipeline_runs` | Una corrida del pipeline y su observabilidad. | `run_id` | `trigger`, `started_at`, `finished_at`, `status`, `source_hashes` (JSONB), `steps` (JSONB), `error` |

### 13.4 Leads y normalización

| Tabla | Propósito | Clave | Campos críticos |
|---|---|---|---|
| `leads` | Fila canónica por lead, con original y normalizado. | `lead_id` | `company_id`, `point_of_sale_id`, `channel`, `status`, campos normalizados, `raw_payload` (JSONB), `normalization_meta` (JSONB), `record_hash`, `content_hash`, `first_seen_run`, `last_seen_run`, `is_current` |

### 13.5 Identidad (intra-empresa)

| Tabla | Propósito | Clave | Campos críticos |
|---|---|---|---|
| `identity_clusters` | Identidad agrupada dentro de una empresa. | `cluster_id` | `company_id`, `canonical_lead_id`, `status`, `match_strength`, `score`, `matched_rules` (JSONB), `decided_by`, `decided_at`, `note` |
| `identity_members` | Pertenencia y motivo. | `id` | FK `cluster_id`, FK `lead_id`, `role`, `rule_id`, `match_strength`, `evidence` (JSONB) |

### 13.6 Conversaciones

| Tabla | Propósito | Clave | Campos críticos |
|---|---|---|---|
| `conversations` | Conversación, vínculo y mensajes. | `conversation_id` | FK `lead_id` (nullable), `company_id` (nullable), `channel`, `started_at`, `content_hash`, `status` (`linked`/`orphan`), `messages` (JSONB), `first_seen_run`, `last_seen_run` |

### 13.7 IA

| Tabla | Propósito | Clave | Campos críticos |
|---|---|---|---|
| `ai_extractions` | Extracción de una conversación con su versión. | `extraction_id` | FK `conversation_id`, `prompt_version`, `schema_version`, `model_name`, `status`, `input_hash`, `fields` (JSONB), `raw_response` (JSONB), `latency_ms`, `is_current` |

### 13.8 Priorización y asignación

| Tabla | Propósito | Clave | Campos críticos |
|---|---|---|---|
| `lead_scores` | Score por lead y corrida, con su explicación. | `score_id` | FKs `lead_id`, `run_id`, `score_version`, `priority_score`, `urgency_score`, `queue_score`, `band`, `reasons` (JSONB), `params_snapshot` (JSONB), `is_current` |
| `assignments` | Lead → asesor. | `assignment_id` | FKs `lead_id`, `advisor_id`, `company_id`, `point_of_sale_id`, `run_id`, `run_date`, `strategy_version`, `priority_rank`, `status` (`assigned`/`overflow`), `reason`, `is_current` |

### 13.9 Explicabilidad de la prioridad

La cola puede responder "¿por qué?" porque `lead_scores.reasons` (JSONB) guarda,
por corrida y lead: cada componente, su contribución numérica, un código, un texto
y la evidencia (p. ej. la cita de la conversación). El detalle del lead reconstruye
exactamente el cálculo con la versión de score usada.

---

## 14. Automatización

Un **único disparador** ejecuta las etapas. Tres formas de invocarlo, todas el
mismo código:

1. CLI: `python -m app.pipeline run` (recomendado para la extracción IA).
2. Endpoint autenticado `POST /admin/pipeline/run` (token de servicio) que inicia
   la corrida y responde de inmediato; la IA corre en background.
3. Cron del proveedor o GitHub Actions que llama al endpoint o al CLI.

### 14.1 Idempotencia por etapa

| Etapa | Clave de idempotencia |
|---|---|
| Ingesta | `sha256` de archivo en `pipeline_runs.source_hashes` |
| Normalización | `leads.content_hash` |
| Deduplicación | recomputación determinista (intra-empresa); `status` del cluster |
| Enlace de conversaciones | `conversations.content_hash` + `lead_id` |
| IA | `(conversation_id, input_hash)`; `is_current` |
| Scoring | `(lead_id, run_id, score_version)`; `is_current` |
| Asignación | `(run_date, company_id, strategy_version)`; `is_current` |

### 14.2 Escenarios

| Situación | Comportamiento |
|---|---|
| Un archivo no cambia | Hash igual → se omite la ingesta de ese archivo. |
| Lead nuevo | Se inserta, normaliza, puntúa y entra a la asignación del día. |
| Conversación nueva | Se enlaza o queda huérfana; se extrae y actualiza la vista consolidada y el score enriquecido. |
| Conversación cambia | Nuevo hash → nueva extracción; el score se recalcula. |
| IA falla | Extracción `failed`; el lead mantiene score inicial; reintento en la próxima corrida; alerta. |
| DB falla | Transacción con rollback; la corrida queda `failed`; re-ejecutar no duplica. |
| Se ejecuta dos veces | Upserts por clave; extracciones omitidas; asignación anterior marcada `is_current=false`. |

---

## 15. Dashboard

Interfaz mínima, orientada a la operación diaria. No es un BI.

### 15.1 Pantalla principal — "Mi día"

Responde "¿qué gestionar hoy y por qué?". Columnas:

- lead (nombre enmascarado si aplica), empresa, punto de venta;
- modelo; prioridad (banda) y urgencia (banda);
- **razones** (chips con `reason_text`);
- señales de conversación (intención, forma de pago, objeción, cita);
- evidencia (enlace a la cita del mensaje);
- estado de gestión y acción de marcar contacto.

### 15.2 Vista de detalle del lead

- Datos **raw vs normalizados** y banderas de calidad (fechas ambiguas, teléfono
  inválido, modelo ambiguo).
- Cluster de identidad y motivo de duplicado.
- Conversaciones y mensajes; extracción IA campo por campo con estado y evidencia.
- Desglose del score: componente, contribución, razón y versión.
- Historial de asignaciones y cambios de estado.
- `overflow`: si no se pudo asignar, con el motivo.

### 15.3 Vistas de administración

- Corridas del pipeline y estado por etapa.
- Conversaciones huérfanas (las 12).
- Cola de revisión de duplicados posibles.
- Métricas.

---

## 16. Métricas

Pocas y accionables:

- Leads procesados / leads con conversación / leads enriquecidos.
- Leads prioritarios (por banda) y leads sin gestión.
- Capacidad utilizada por asesor (asignados vs `daily_capacity`).
- Distribución por prioridad y urgencia.
- Porcentaje de extracciones con evidencia (calidad de la IA).
- Duplicados detectados por nivel (fuerte/posible/débil) y pendientes de revisión.
- Conversaciones huérfanas.
- Leads en `overflow` (demanda no cubierta).

Adicionales justificadas: **conversión histórica por canal/empresa** como
referencia descriptiva y **tiempo hasta primer contacto** como indicador de SLA
(este último se mide con datos seguros, no con la variable del histórico).

---

## 17. Despliegue

- Un servicio web (FastAPI, contenedor) + PostgreSQL gestionado (Neon/Supabase/Render).
- Un cron programado (del proveedor o GitHub Actions) que llama al disparador.
- Migraciones con Alembic; carga inicial de `data/` mediante un comando `seed`.
- Variables de entorno: `DATABASE_URL`, `APP_SECRET_KEY`, `SERVICE_TOKEN`,
  `LLM_API_KEY`, `LLM_MODEL`, `LLM_MAX_CALLS_PER_RUN`, `TZ`.
- URL pública con HTTPS. La DB no se expone públicamente.

---

## 18. Decisiones técnicas (y alternativas descartadas)

1. **Monolito modular en vez de microservicios**: el volumen (miles de filas) y el
   equipo (una persona, 5 días) no justifican distribuirlos.
2. **PostgreSQL con aislamiento por `company_id` + capa de acceso, y RLS parcial**:
   el aislamiento principal es del backend/repositorio; RLS solo en `leads`,
   `conversations` y `assignments` como defensa adicional. SQLite queda descartado
   por concurrencia y por no ofrecer RLS.
3. **Dashboard server-rendered en vez de SPA**: menos trabajo, suficiente para una
   tabla del día y un detalle.
4. **Score explicable en vez de modelo ML**: el histórico discrimina poco
   (~9%–10% uniforme); un modelo complejo no aportaría señal y sí riesgo de
   leakage y de no ser defendible. El histórico **no entra al score v1**: solo
   patrones agregados y línea base.
5. **Sin embeddings/vector DB**: no hay búsqueda semántica ni RAG en el problema;
   la extracción es estructurada por conversación.
6. **Sin orquestador**: un cron + un endpoint idempotente resuelven el caso.
7. **Proveedor LLM abierto**: se elige al implementar según costo, salida JSON y
   disponibilidad; el contrato es agnóstico.
8. **Fechas ambiguas no se resuelven**: no se asume `DD/MM` ni `MM/DD`. Se
   conserva el original, `parsed_date` nulo y el motivo. Decisión cerrada.
9. **Histórico solo agregado**: usarlo por fila es imposible sin llave; hacerlo por
   nombre/teléfono está prohibido y sería frágil.
10. **Catálogo global (supuesto)**: los datos actuales muestran los 24 SKU en los
    15 PV de las tres empresas. Se documenta el supuesto y el punto de cambio si
    negocio lo corrige.
11. **Extracción IA fuera del request**: se ejecuta por CLI/proceso en background
    para evitar timeouts; el disparador solo inicia la corrida.

---

## 19. README final (contenido definido, redacción pendiente)

El README final debe leerse natural y directo, contando decisiones. Secciones
obligatorias:

1. Qué problema resuelve.
2. Cómo funciona (flujo en pocas líneas).
3. Arquitectura (diagrama simple).
4. Decisiones importantes (y por qué).
5. Cómo se procesan los datos (raw vs normalizado, fechas ambiguas).
6. Cómo funciona la IA (contrato, estados, evidencia, idempotencia).
7. Cómo se calcula la prioridad (resumen de `scoring-design.md`).
8. Cómo se evita leakage.
9. Cómo se manejan duplicados.
10. Cómo se garantiza la separación entre empresas.
11. Cómo ejecutar localmente.
12. Variables de entorno.
13. Cómo ejecutar el pipeline.
14. Cómo ejecutar pruebas.
15. Cómo desplegar.
16. Limitaciones conocidas.
17. Decisiones y supuestos relevantes.

---

## 20. Estrategia de Git y trazabilidad

El historial debe contar la evolución real, con commits temáticos (no uno gigante).
Los commits existentes del paso de auditoría se conservan; a partir de aquí:

1. `chore: estructura y configuración del proyecto`
2. `docs: diseño técnico y de scoring`
3. `feat(db): modelos, migraciones y seeds multiempresa`
4. `feat(ingest): ingesta de fuentes con hashing e idempotencia`
5. `feat(normalize): normalización raw/normalizado con metadatos de calidad`
6. `feat(dedup): clustering de identidad conservador`
7. `feat(ai): extracción estructurada con evidencia y versionado`
8. `feat(scoring): score explicable inicial y enriquecido`
9. `feat(assign): asignación por empresa, punto y capacidad`
10. `feat(dashboard): cola del día, detalle y admin`
11. `feat(pipeline): disparador idempotente y observabilidad`
12. `test: cobertura de normalización, aislamiento por empresa, dedup y asignación`
13. `docs: README y limitaciones`
14. `chore(deploy): contenedor y despliegue`

Regla: cada commit debe pasar sus pruebas y dejar el repositorio coherente.

---

## 21. Orden de implementación (5 días)

| Día | Foco | Entregable verificable |
|---|---|---|
| 1 | Modelo de datos (~13 tablas), migraciones, ingesta y normalización | `leads` con `raw_payload`/`normalization_meta`; hashing idempotente |
| 2 | Dedupe intra-empresa y enlace de conversaciones | Clusters + huérfanas trazables; tests |
| 3 | Extracción IA (CLI/background) | Contrato, persistencia, idempotencia, fallback |
| 4 | Scoring y asignación | `lead_scores` con `reasons`; asignación con overflow; aislamiento por empresa + RLS parcial |
| 5 | Dashboard, automatización, despliegue, README, endurecimiento | URL pública; corrida programada; documentación |

---

## 22. Riesgos y supuestos (resumen)

El detalle se entrega como resumen al cierre del paso. Los riesgos principales:
ambigüedad de fechas no resuelta (afecta urgencia), calidad variable de la
extracción IA (mitigada con `state` y evidencia), capacidad insuficiente
(`overflow` visible), y baja señal del histórico (por eso el score no depende de él).
