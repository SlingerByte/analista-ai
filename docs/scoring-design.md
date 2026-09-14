# Diseño de scoring — Prioridad y urgencia

Documento de diseño. **No implementa código.** Define cómo se prioriza un lead,
por qué, cómo se explica y cómo se evita el leakage. Se apoya en el audit real.

---

## 1. Objetivo

Convertir cada lead en dos señales separadas y explicables:

- **Prioridad comercial**: qué tan valioso/atendible es el lead.
- **Urgencia operativa**: qué tan pronto debe gestionarse.

Y en dos momentos:

- **Score inicial**: se calcula cuando el lead llega, solo con datos de llegada.
  **No usa variables posteriores a la gestión ni el histórico como predictor.**
- **Score enriquecido**: se recalcula después de analizar las conversaciones.

La cola del día usa ambos conceptos, pero nunca los mezcla en un "número mágico"
sin desglose.

---

## 2. Por qué NO un modelo de ML complejo

Es una decisión basada en los datos, no una preferencia.

Conversión histórica ajustada (excluyendo `Sin gestión`: `Cerrado / (Cerrado + Perdido)`):

| Segmento | Conversión |
|---|---|
| WhatsApp | 114 / 1.101 = **10,4 %** |
| Meta Ads | 54 / 621 = **8,7 %** |
| Formulario Web | 29 / 299 = **9,7 %** |
| EMP-01 | 74 / 702 = **10,5 %** |
| EMP-02 | 60 / 656 = **9,1 %** |
| EMP-03 | 63 / 663 = **9,5 %** |

Además, `Cerrado` es 8,95 % del total (197 de 2.200). La señal es **débil y casi
uniforme**. Un XGBoost no tendría de dónde aprender y sería difícil de defender.
Por eso:

- Score **explicable** por componentes con pesos configurables.
- Histórico como **referencia agregada y línea base**, nunca como predictor.

Si más adelante se acumulan outcomes de los leads actuales, se podrá evaluar un
modelo calibrado. Hoy no.

---

## 3. Universo de variables por momento

| Variable | ¿Disponible al llegar? | Uso permitido |
|---|---|---|
| `canal` | Sí | Score inicial |
| `empresa_id`, `punto_venta_id` | Sí | Score inicial |
| `ciudad` | Sí (o faltante) | Score inicial (débil) |
| `modelo_interes_texto` → SKU / segmento / precio | Sí (o ambiguo) | Score inicial |
| `campania` | Sí | Score inicial débil (sin histórico asociado) |
| `fecha_registro` | Sí (si no ambigua) | Urgencia |
| `estado_gestion` | Estado operativo actual | Urgencia (no "valor") |
| `fecha_primer_contacto` | Solo si no ambigua | Urgencia / SLA |
| Banderas de calidad (teléfono, modelo, fecha) | Sí | Ajuste de atendibilidad |
| Señales de conversación (IA) | No | Score enriquecido |
| `desenlace` | No (es el target) | **Prohibido** |

---

## 4. Score inicial

### 4.1 Componentes de prioridad comercial (cada uno en [0, 1])

| Código | Componente | Definición | Peso |
|---|---|---|---|
| P1 | `valor_ticket` | Precio de lista del SKU normalizado al rango del catálogo (4,99M–24,9M). | 0,40 (configurable) |
| P2 | `calidad_dato` | Atendibilidad: teléfono válido + modelo resuelto a un SKU único + ciudad presente + email presente. | 0,60 |

`priority_score = 100 × (0,40·P1 + 0,60·P2)`

Bandas: **Alta ≥ 70**, **Media 45–69**, **Baja < 45** (configurables).

Notas:

- **El histórico no entra en el score v1** (se eliminó `prior_conversion`). La
  conversión histórica (~9–10,5 %) discrimina poco y no justifica un componente;
  queda como referencia descriptiva y línea base en métricas.
- `valor_ticket` **no asume que un ticket mayor siempre sea mejor**: es una **regla
  de negocio configurable**. Por defecto pesa 0,40; si el objetivo es volumen, su
  peso baja a 0 y sube `calidad_dato`.
- `calidad_dato` castiga leads no contactables o con modelo/ciudad faltantes (80
  modelos y 79 ciudades faltantes en el audit; 1 teléfono inválido; 115 modelos
  ambiguos).

### 4.2 Componentes de urgencia operativa

| Código | Componente | Definición | Peso |
|---|---|---|---|
| U1 | `sla_sin_contacto` | Tiempo desde `fecha_registro` sin primer contacto, en bandas: <4 h = 0,30; 4–24 h = 0,60; 24–48 h = 0,85; >48 h = 1,00. | 0,55 |
| U2 | `estado_operativo` | `Sin gestión` = 1,00; `No contesta` = 0,80; `Cotización enviada` = 0,70; `Contactado` = 0,50; `En proceso` = 0,40. | 0,45 |

`urgency_score = 100 × (0,55·U1 + 0,45·U2)`

Reglas de **override** de banda:

- `cita_solicitada` = sí (inicial solo si el CRM lo sabe) → **Hoy**.
- `estado_gestion = Sin gestión` con fecha segura > 48 h → **Hoy**.
- Si `fecha_registro` es ambigua → U1 se fija en 0,50 y se marca urgencia
  **"no confiable"** (nunca se adivina la antigüedad).

Bandas de urgencia: **Hoy**, **24 h**, **Semana**.

**Fallback**: la urgencia no depende solo de fechas. Con 265 fechas de registro
ambiguas, 216 de contacto ambiguas y 487 sin fecha de contacto, `U1` puede quedar
neutral o marcado "no confiable" en una fracción grande de leads. En ese caso la
urgencia se sostiene con `U2` (`estado_gestion`), para que ningún lead quede sin
señal de urgencia.

### 4.3 Leakage en el score inicial

El score inicial **no** usa `horas_al_primer_contacto`, `numero_contactos`,
`manifesto_cuota_inicial`, `forma_pago_declarada` ni `pidio_cita` del histórico
(véase §7). `estado_gestion` sí se usa, pero solo como urgencia operativa, no como
valor comercial.

---

## 5. Score enriquecido (post-conversación)

Se recalcula cuando hay extracción IA. Los campos con `state` aportan según su
jerarquía:

| `state` | Factor de aplicación |
|---|---|
| `explicito` | 1,00 |
| `inferido` | 0,60 |
| `ambiguo` | 0,25 |
| `no_mencionado` | 0,00 |

Ajustes sobre la prioridad comercial (aditivos, acotados a [0, 1] al final):

| Señal | Ajuste | Condición |
|---|---|---|
| `intencion_compra` alta | +0,30 | state aplicable |
| `intencion_compra` media | +0,15 | |
| `intencion_compra` baja | −0,10 | |
| `solicitud_cotizacion` | +0,10 | |
| `presupuesto`/`cuota_inicial` informados y ≥ modelo más barato | +0,10 | |
| `presupuesto` por debajo del modelo más barato | −0,15 | y marca objeción de precio |
| `objecion` = precio | −0,10 | |
| `objecion` = competencia | −0,15 | |
| `objecion` = tiempo | −0,05 | |
| `modelo_interes` distinto al registrado (up-sell) | +0,05 | solo si la regla de ticket está activa y mejora ticket |
| Todos los campos `ambiguo`/`no_mencionado` | 0,00 | marca `sin_enriquecer_efectivo` |

Ajustes sobre la urgencia:

| Señal | Efecto |
|---|---|
| `solicitud_cita` = sí | urgencia **Hoy** (override) |
| `solicitud_cotizacion` = sí | +0,15 |
| Cliente pide precio y lleva > 24 h sin respuesta | +0,10 |

`enriched_priority = clip(priority_inicial + Σ ajustes, 0, 1)`
`enriched_urgency  = clip(urgency_inicial  + Σ ajustes, 0, 1)`

El detalle del lead guarda cada ajuste como **contribución con su evidencia**
(cita del mensaje), de modo que la prioridad sea reconstruible.

> Nota importante sobre leakage: las señales de conversación son **estado actual
> del lead**, no resultado. Usarlas para reordenar mañana la gestión no es leakage.
> Serían leakage si se usaran para *predecir* el cierre en un entrenamiento sin
> respetar el instante de captura. Por eso cada señal se guarda con su mensaje de
> origen y su momento.

---

## 6. Uso legítimo del histórico

El histórico **no es un predictor** y no entra al score v1. Se usa para contexto,
patrones y medición. Reglas duras:

1. **No hay join individual.** La intersección de `lead_id` es 0. No se une por
   nombre, teléfono ni email.
2. **Solo agregados descriptivos** por canal, empresa, punto de venta, segmento y
   rango de precio. Sin suavizado ni fallback jerárquico: no alimentan ninguna
   fórmula, se muestran tal cual con su `n`.
3. **Campos prohibidos** como predictor o como insumo de agregados:
   `desenlace`, `horas_al_primer_contacto`, `numero_contactos`,
   `manifesto_cuota_inicial`, `forma_pago_declarada`, `pidio_cita`. Las tasas de
   conversión se calculan solo con `Cerrado` vs `Perdido` y campos permitidos
   (canal, empresa, PV, modelo, precio), presentadas con su conteo.

Usos recomendados:

- Referencia descriptiva de conversión por canal/empresa y línea base para
  comparar el desempeño del score.
- Planeación de capacidad (cuántos leads por canal y por mes).
- Peso de `Sin gestión` por canal (8,7 % WhatsApp, 7,3 % Meta, 7,7 % Formulario
  Web) como carga operativa no atendida.

---

## 7. Prevención de leakage (lista explícita)

| Variable | Por qué es leakage | Estado |
|---|---|---|
| `desenlace` | Es la etiqueta objetivo | Excluida siempre |
| `horas_al_primer_contacto` | Nulo exactamente para `Sin gestión` (179) | Excluida |
| `numero_contactos` | 0 exactamente para `Sin gestión` (179) | Excluida |
| `manifesto_cuota_inicial` | Momento de captura no confirmado | Excluida del score/agregados |
| `forma_pago_declarada` | Momento de captura no confirmado | Excluida del score/agregados |
| `pidio_cita` | Momento de captura no confirmado | Excluida del score/agregados |
| `estado_gestion` | Operativo, no outcome; puede reflejar avance | Permitida como urgencia |
| Señales IA del lead actual | Estado presente, no outcome | Permitidas en score enriquecido |

Si se construyera un modelo predictivo más adelante, cada campo necesitaría
timestamp y solo podría usarse si su captura precede al instante de predicción.

---

## 8. Explicabilidad

Cada score se acompaña de **razones** con código, texto y contribución numérica.

Ejemplos de códigos:

- `TICKET_ALTO_REGLA_NEGOCIO`
- `MODELO_AMBIGUO`
- `SIN_TELEFONO_VALIDO`
- `SIN_GESTION_MAS_48H`
- `NO_CONTESTA_REINTENTO`
- `COTIZACION_ENVIADA_SEGUIMIENTO`
- `CLIENTE_PIDIO_CITA`
- `OBJECION_PRECIO`
- `INTENCION_COMPRA_ALTA`
- `DUPLICADO_PROBABLE` (informativo; el cluster controla la gestión)
- `FECHA_AMBIGUA_URGENCIA_NO_CONFIABLE`

La vista del lead muestra: componente → contribución → razón → evidencia.

---

## 9. Ejemplos

### Ejemplo A — score inicial (datos reales de la primera fila relevante)

`LD-00011` (también duplicado exacto y, por tanto, ejemplo de dedup):
Meta Ads, `EMP-02`, `PV-008`, ciudad CARTAGENA, modelo `suzuki best 125`,
`estado_gestion = Sin gestión`, sin `fecha_primer_contacto`, campaña "Retoma tu moto".

- P1 `valor_ticket`: `Suzuki Best 125` es uno de los SKU más económicos (~4,99M) →
  valor bajo (con la regla de ticket activa).
- P2 `calidad_dato`: sin email, modelo resuelto (`Best 125`), teléfono válido,
  ciudad presente → medio.
- U1: sin contacto y sin fecha de contacto; como la fecha de registro es segura
  (`2026-08-26 04:25:00`) se calcula antigüedad.
- U2 = 1,00 (`Sin gestión`).
- Resultado: **prioridad comercial baja/media, urgencia alta**. Un lead barato y
  difícil de cerrar puede seguir siendo urgente porque nadie lo ha tocado.
- Además: entra como cluster de identidad fuerte con su duplicado; solo un registro
  va a la cola.

### Ejemplo B — fecha ambigua (datos reales)

`LD-00003`: WhatsApp, `EMP-02`, `PV-010`, MONTERIA, `suzuki best 125`,
`Contactado`, `fecha_registro = 01-08-2026`, `fecha_primer_contacto = 2026-08-04 14:47:00`.

- La fecha de registro con guion es ambigua (día y mes ≤ 12); no se asume un
  formato.
- U1 **no se calcula**: urgencia marcada "no confiable"; U2 = 0,50 (`Contactado`).
- El lead aparece con una advertencia visible, no con una antigüedad inventada.

### Ejemplo C — score enriquecido (ilustrativo, no es un dato del dataset)

Conversación hipotética donde el cliente dice explícitamente:
"me interesa la Bajaj Pulsar RS 200", "la quiero financiada", "¿me la cotiza?",
y luego "estoy mirando otra marca".

- `modelo_interes` explícito (`SKU` de Pulsar RS 200) → refuerza ticket si la
  regla de ticket está activa.
- `forma_pago` = crédito (`inferido`, factor 0,60).
- `solicitud_cotizacion` = sí (`explicito`) → +0,10 prioridad, +0,15 urgencia.
- `objecion` = competencia (`explicito`) → −0,15 prioridad.
- Todo con cita y `message_seq`. El neto se explica en el detalle.

---

## 10. Cómo evaluar si el score funciona

No se asume un backtest individual: los `lead_id` del histórico (`HX-*`) no
coinciden con los actuales (`LD-*`). Lo que sí es posible:

1. **Ranking sobre el histórico, sin join.** Se aplica la parte estructural del
   score inicial a las filas del histórico (canal, empresa, PV, modelo, precio,
   fecha) y se mide si ordena mejor que el azar con **precision@k** y **lift@k**
   (top 10 %/20 %), contra un baseline simple (aleatorio y "solo conversión por
   canal"). **No se usan AUC, PR-AUC ni Brier.** Limitación explícita: valida solo
   la parte estructural; no valida `calidad_dato` (el histórico no tiene
   ciudad/email/teléfono) ni el score enriquecido. Es un sanity check.
2. **Validación de la IA (validación principal).** Gold set pequeño de
   conversaciones anotadas a mano (de las 677): precisión por campo, cobertura,
   tasa de estados `explicito`/`inferido` y **porcentaje con evidencia**.
3. **Simulación operativa sobre los datos actuales:** demanda vs capacidad (326
   unidades, capacidades por PV) → cuántos `overflow` y utilización por asesor.
4. **Monitoreo operativo** cuando se capturen outcomes de los leads actuales:
   conversión por banda, tiempo hasta primer contacto, uso de capacidad y
   evolución de `Sin gestión`.
5. **Comparación de versiones:** al cambiar parámetros (`score_version`), comparar
   colas y métricas; poder revertir.

---

## 11. Versionado y parámetros

- Los pesos y umbrales viven como configuración versionada; cada fila de
  `lead_scores` guarda `score_version` y un `params_snapshot` (JSONB) con los
  valores usados.
- Cambiar un parámetro crea una nueva versión; los scores anteriores conservan su
  snapshot.
- Esto permite reconstruir por qué un lead tuvo cierta prioridad en una fecha.
- Estrategia de ajuste: empezar con pesos de negocio, revisar semanalmente con las
  métricas, mover un parámetro a la vez.

---

## 12. Resumen de decisiones de scoring

- Dos conceptos separados (prioridad / urgencia) y dos momentos (inicial/enriquecido).
- Explicable por componentes, con razones y evidencia.
- Histórico solo agregado y descriptivo; no es predictor ni entra al score v1.
- Ticket como regla de negocio configurable, no como verdad.
- Leakage bloqueado por lista explícita.
- Sin fechas inventadas: ambigüedad visible y urgencia con fallback por estado.
- Sin modelo ML complejo: los datos no lo justifican hoy.
