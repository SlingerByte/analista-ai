# Auditoría de calidad de la extracción IA

> Fase 2.7 — Auditoría. **No se modificó código de producción.**
> Fecha de análisis sobre el repositorio en `2e91957`.
> Proveedor evaluado: `ollama` / `qwen2.5:3b` (prompt `v2`, schema `v1`).

---

## 1. Resumen ejecutivo

La extracción es **estructuralmente válida** (schema, evidencia y no-invención se
cumplen), pero **semánticamente incompleta**: el modelo evaluado deja en `null`
señales que el cliente declaró de forma explícita. En las 10 conversaciones con
salida IA real disponible (80 decisiones de campo), hay **59 aciertos, 20 falsos
negativos, 0 falsos positivos estrictos y 1 ambiguo**. El patrón dominante es la
**sub-extracción conservadora**, no la alucinación: `intencion_compra` 0/8,
`forma_pago` 0/5, `objecion` 1/5 y `solicitud_cita` 0/1 oportunidades capturadas.
`model_interes` (9/10) y `solicitud_cotizacion` (4/4) funcionan bien. El caso
CONV-00058 confirma el patrón: se captura el modelo inicial (Honda CB 125F
Twister) y no el vigente (AKT NKD 125), y se pierde la inicial de ~1.000.000. El
impacto comercial es **alto** porque varias señales perdidas alimentan el scoring
(forma de pago, intención, cita) y la gestión del asesor (modelo). Limitación
metodológica: solo 10 conversaciones tienen salida IA persistida/reproducible en
el repositorio; no se reprocesó el corpus (fuera de alcance), por lo que las
métricas son de esa muestra y no extrapolables sin un nuevo benchmark.

---

## 2. Metodología

- **Fuente de verdad:** la conversación original (`conversaciones.json`), leída
  mensaje a mensaje; el ground truth se anotó manualmente campo por campo.
- **Salida IA auditada:** `reports/ai_benchmark.json` (proveedor `ollama`,
  `qwen2.5:3b`, prompt `v2`). Es la **única** salida IA real disponible en el
  repositorio.
- **Tamaño de muestra AI:** 10 conversaciones × 8 campos = **80 decisiones**.
- **Análisis de exposición:** se recorrieron **las 677 conversaciones** con
  tooling de auditoría determinista (regex sobre texto normalizado, sin IA) para
  medir cuántas contienen cada patrón comercial. Esto da el denominador de
  oportunidades del corpus, **no** accuracy de IA.
- **Ground truth:** derivado de lo que el cliente dice, no de lo que el asesor
  ofrece. Ejemplos: “Financiada” ⇒ `forma_pago`; “otra marca” ⇒ `objecion`;
  “solo mirando precios” ⇒ `intencion_compra` baja; “¿a qué hora los puedo
  visitar?” ⇒ cita; “1 millonzitos de inicial” ⇒ cuota inicial.
- **Limitaciones (explícitas):**
  - No hay base de datos ni extracciones IA persistidas en el repositorio; el
    corpus de 677 no tiene salida IA disponible y **no se reprocesó**.
  - Las métricas (n=10) **no deben extrapolarse** al corpus.
  - El proveedor auditado es un modelo local pequeño (3B). Producción usa un
    proveedor remoto configurable, que puede comportarse distinto.
  - El benchmark existente mide validez de schema y presencia de evidencia,
    **no** corrección semántica.

### Exposición del corpus (677 conversaciones)

| Patrón (declarado por el cliente) | Conversaciones | % |
|---|---:|---:|
| Menciona inicial/cuota inicial con monto | 235 | 34,7 % |
| Declara forma de pago (financiada/crédito/contado) | 349 | 51,5 % |
| Marcadores de objeción (otra marca, muy cara, más económico, solo mirando, etc.) | 288 | 42,5 % |
| Marcadores de cita/visita | 162 | 23,9 % |
| Solicitud/aceptación de cotización | 225 | 33,2 % |
| Menciona ≥ 2 modelos distintos del catálogo | 84 | 12,4 % |
| Solo cortesía del cliente (todo el turno) | 0 | 0,0 % |
| El último turno es del asesor (quedó sin respuesta) | 73 | 10,8 % |
| Intención alta explícita (“me sirve”, “ya voy”, “la separo”) | 130 | 19,2 % |
| Intención baja/ambigua explícita (“solo mirando”, “otra marca”, “más económico”) | 340 | 50,2 % |
| “No tengo inicial” | 19 | 2,8 % |
| Menciona “cuota” (posible confusión con inicial) | 60 | 8,9 % |

---

## 3. Métricas (muestra con IA real, n = 10)

Accuracy por campo (aciertos / 10 conversaciones). Donde no hay oportunidades
positivas, el valor es “true negative” y no mide poder de detección.

| Campo | Accuracy (n=10) | Oportunidades positivas | Capturadas | Recall |
|---|---:|---:|---:|---:|
| `model_interes` | 90 % | 10 | 9 | 90 % |
| `intencion_compra` | 20 % | 8 | 0 | 0 % |
| `presupuesto` | 100 % | 0 | – | n/a |
| `cuota_inicial` | 90 % | 2 | 1 | 50 % |
| `forma_pago` | 50 % | 5 | 0 | 0 % |
| `objecion` | 50 % | 5 | 1 | 20 % |
| `solicitud_cita` | 90 % | 1 | 0 | 0 % |
| `solicitud_cotizacion` | 100 % | 4 | 4 | 100 % |

Tasas globales (80 decisiones):

```text
false_positive_rate = 0 / 80  = 0 %  (1 caso borderline, ver abajo)
false_negative_rate = 20 / 80 = 25 %
unknown_rate        = 20 / 80 = 25 %  (20 campos nulos donde había señal)
```

> Nota: la “accuracy” de `presupuesto` (100 %) es engañosa: no había ningún
> presupuesto declarado en la muestra; solo refleja que no se inventó nada.
> La métrica relevante es **recall sobre oportunidades positivas**.

---

## 4. Matriz de errores (n = 10 conversaciones)

| Campo | Correctos | Falsos positivos | Falsos negativos | Ambiguos | No determinables |
|---|---:|---:|---:|---:|---:|
| Modelo | 9 | 0 | 1 | 0 | 0 |
| Intención | 2 | 0 | 8 | 0 | 0 |
| Presupuesto | 10 | 0 | 0 | 0 | 0 |
| Cuota inicial | 9 | 0 | 1 | 0 | 0 |
| Forma de pago | 5 | 0 | 5 | 0 | 0 |
| Objeción | 5 | 0 | 4 | 1 | 0 |
| Cita | 9 | 0 | 1 | 0 | 0 |
| Cotización | 10 | 0 | 0 | 0 | 0 |
| **Total** | **59** | **0** | **20** | **1** | **0** |

---

## 5. Principales hallazgos (ordenados por impacto)

1. **`forma_pago` nunca se captura aunque el cliente la declare** (0/5). En
   CONV-00229, CONV-00613, CONV-00060, CONV-00502 el cliente dice “Financiada”; en
   CONV-00018 dice “A crédito”. Todas quedaron `null`. **Causa: MODEL.**
2. **`intencion_compra` es sistemáticamente `null`** (0/8). Ejemplos claros:
   “Solo estaba mirando precios” (baja), “ya voy en camino” (alta), “estoy
   comparando / otra marca” (media). **Causa: MODEL + PROMPT** (guía demasiado
   conservadora: “en caso de duda elige el menor o null”).
3. **`solicitud_cita` se pierde por evidencia mal atribuida.** CONV-00502: el
   cliente pregunta “¿A qué hora los puedo visitar hoy?” (evidencia válida), pero
   el modelo citó un mensaje del asesor; la validación lo anuló correctamente.
   **Causa: MODEL.**
4. **Modelo inicial vs. modelo vigente no está representado.** En 84
   conversaciones (12,4 %) el cliente menciona ≥ 2 modelos. El schema tiene un
   único `model_interes`. CONV-00060 pierde el modelo por falta de evidencia, y
   CONV-00058 (control) captura el inicial, no el vigente. **Causa: PROMPT /
   diseño de schema.**
5. **`objecion` se pierde** (1/5), incluida la conversación designada para
   objeción (CONV-00271: “estoy mirando también otra marca”). **Causa: MODEL.**
6. **Cuota inicial `1 palos` no detectada** (CONV-00229). El modelo no convierte
   expresiones coloquiales de monto en cuota inicial. **Causa: MODEL.**
7. **`solicitud_cotizacion` correcta pero con matiz semántico**: en 2 casos el
   cliente **acepta** una oferta del asesor (“Bueno, mándela y yo le digo”) y se
   marca `true`. El prompt pide “solo si el cliente la pide explícitamente”.
   **Causa: PROMPT** (definición de aceptación vs. solicitud).
8. **La validación determinista no es la causa de los errores**: no creó falsos
   positivos y solo anuló campos cuya evidencia era ausente (CONV-00060) o del
   asesor (CONV-00502). Es un control que funciona; los datos de origen estaban
   mal.

---

## 6. Caso CONV-00058 (control)

```text
[cliente] me interesa la Honda CB 125F Twister
[asesor ] Honda CB 125F Twister … $7.990.000 … ¿contado o financiada?
[cliente] ¿Y no tienen algo más económico? tipo la AKT NKD 125
[asesor ] Claro. la AKT NKD 125 está en $5.290.000 …
[cliente] Esa sí me sirve. Tengo como 1 millonzitos de inicial
[cliente] ¿Mañana los visito?
```

Ground truth (de la conversación):

| Campo | Ground truth |
|---|---|
| `model_interes` (vigente) | **AKT NKD 125** (Escenario C: el cliente confirma “esa sí me sirve” sobre la oferta del asesor). Modelo inicial: Honda CB 125F Twister. |
| `cuota_inicial` | **≈ 1.000.000** (“1 millonzitos de inicial”). |
| `intencion_compra` | **alta** (“esa sí me sirve” + “¿mañana los visito?”). |
| `solicitud_cita` | **true** (“¿Mañana los visito?”). |
| `objecion` | precio (implícita: “¿algo más económico?” → objeción suave). |
| `forma_pago` | `null` (no se declara en esta conversación). |
| `presupuesto` | `null`. |
| `solicitud_cotizacion` | `null`. |

La extracción reportada por el usuario (`model_interes = Honda CB 125F Twister`,
`intent = alta`, `down_payment = null`, `appointment = true`) **no está
persistida en el repositorio** (no hay base de datos ni extracción de CONV-00058),
por lo que no puede verificarse aquí; se toma como reporte del solicitante. Bajo
el ground truth anterior, el caso confirma el **patrón general**:

- modelo **inicial** capturado en lugar del **vigente** (riesgo de gestión:
  el asesor llamaría por la moto equivocada);
- `cuota_inicial` de ~1.000.000 perdida (señal de capacidad de pago);
- cita e intención se reportan correctas (coherente con la conversación).

Este caso **no** se convirtió en regla específica; es un ejemplo del problema
general de modelo múltiple y extracción monetaria coloquial.

---

## 7. Casos representativos (anonimizados por `conversacion_id`)

| Conversación | Evidencia del cliente | Campo | GT | IA | Clasificación |
|---|---|---|---|---|---|
| CONV-00229 | “Financiada. Tengo como 1 palos…” | forma_pago | financiacion | null | FN (MODEL) |
| CONV-00229 | “1 palos” | cuota_inicial | ≈1.000.000 | null | FN (MODEL) |
| CONV-00229 | “¿No tienen usadas?” | objecion | disponibilidad (dudoso) | null | AMBIGUITY |
| CONV-00502 | “Financiada”; “¿A qué hora los puedo visitar hoy?” | forma_pago / cita | financiacion / true | null / null | FN (MODEL; cita anulada por evidencia del asesor) |
| CONV-00502 | “tengo 2,0 millones para la inicial” | cuota_inicial | 2.000.000 | 2.000.000 | Correcto |
| CONV-00060 | “vi el anuncio de la AKT Dynamic R3 125” | model_interes | AKT Dynamic R3 125 | null (evidencia ausente) | FN (MODEL) |
| CONV-00271 | “estoy mirando también otra marca” | objecion | otra | null | FN (MODEL) |
| CONV-00210 | “Solo estaba mirando precios” | intencion_compra | baja | null | FN (MODEL/PROMPT) |
| CONV-00018 | “A crédito”; “Esa tasa está muy alta” | forma_pago / objecion | credito / cuota | null / cuota | FN (MODEL) / Correcto |
| CONV-00613 | “Financiada”; “Esa tasa está muy alta” | forma_pago / objecion | financiacion / cuota | null / null | FN (MODEL) |
| CONV-00587 | “Solo estaba mirando precios” | intencion_compra | baja | null | FN (MODEL/PROMPT) |

Ningún caso presentó **falso positivo estricto**. El único matiz: en CONV-00229 y
CONV-00613 `solicitud_cotizacion = true` corresponde a **aceptación** de una
oferta del asesor, no a una petición explícita.

---

## 8. Causa probable (taxonomía)

| # | Hallazgo | Categoría | Comentario |
|---|---|---|---|
| 1 | `forma_pago` no capturada | **MODEL** | El prompt es correcto (“solo si el cliente la declara”); el modelo no lo hace. |
| 2 | `intencion_compra` siempre null | **MODEL + PROMPT** | El modelo es ultraconservador; el prompt refuerza “en duda, null”. |
| 3 | `solicitud_cita` anulada por evidencia del asesor | **MODEL** | Valor correcto, cita equivocada; la validación hizo bien. |
| 4 | Modelo inicial vs. vigente | **PROMPT / SCHEMA** | Un solo campo no representa cambio de modelo. |
| 5 | `objecion` no capturada | **MODEL** | Incluye el caso de control de objeción. |
| 6 | “1 palos” no convertido | **MODEL** | Expresión monetaria coloquial. |
| 7 | Aceptación vs. solicitud de cotización | **PROMPT** | Definición de `solicitud_cotizacion`. |
| 8 | “¿No tienen usadas?” | **AMBIGUITY** | No es claramente una objeción. |

No se observaron errores de **CONSOLIDATION** (cada lead de la muestra tiene una
conversación) ni de **VALIDATION** (la validación evitó falsos positivos).
No se detectaron errores de **DATA** atribuibles a los datos originales.

---

## 9. Impacto comercial

| Hallazgo | Impacto | Razonamiento |
|---|---|---|
| `forma_pago` perdida | **HIGH** | Pierde `FORMA_PAGO_DECLARADA` (+5) y contexto de financiación; 349 conversaciones expuestas. |
| `intencion_compra` perdida | **HIGH** | Pierde 30/15/5 puntos por intención; 340 conversaciones con marcador bajo y 130 con alto. |
| `solicitud_cita` perdida | **HIGH** | No dispara urgencia “Hoy” (override 100); 162 conversaciones expuestas a cita/visita. |
| Modelo inicial vs. vigente | **HIGH** | El asesor puede gestionar el modelo equivocado; 84 conversaciones con ≥2 modelos. |
| `objecion` perdida | **MEDIUM** | No aplica penalización ni alerta al asesor; 288 conversaciones con marcadores. |
| Cuota inicial coloquial perdida | **MEDIUM** | Pierde `CUOTA_SUFICIENTE` (+5) y capacidad de pago; 235 conversaciones expuestas. |
| Aceptación vs. solicitud de cotización | **LOW** | No cambia el signo (+10) pero infla ligeramente el significado. |

**Regla de la investigación:** la extracción válida pero incompleta produce
**falsos negativos sistemáticos** que el scoring no puede compensar. El riesgo
principal no es que el sistema invente datos, sino que **descarta señales reales**.

---

## 10. Recomendaciones (sin implementar)

### Debe corregirse antes de la entrega
1. **Reforzar el prompt** con ejemplos explícitos de cliente para `forma_pago`
   (“Financiada”, “A crédito”), `objecion` (“otra marca”, “muy cara”, “tasa muy
   alta”) e `intencion_compra` (baja/media/alta), y aclarar evidencia de cita.
2. **Verificar el proveedor/modelo de producción**: `qwen2.5:3b` sub-extrae
   severamente; ejecutar el benchmark sobre el proveedor remoto real.
3. **Representar modelo inicial y vigente** (o definir la política de cuál es el
   `model_interes`) para las conversaciones con varios modelos.

### Conviene corregir si queda tiempo
4. **Añadir un gold set** (≥100 conversaciones anotadas) con precision/recall por
   campo; el benchmark actual no mide corrección semántica.
5. **Mejorar la extracción monetaria coloquial** (“1 palos”, “millonzitos”).
6. **Definir aceptación vs. solicitud** de cotización en el prompt.

### Puede quedar como limitación conocida
7. La ausencia de base de datos persistida impide calcular accuracy sobre las 677;
   el visor de conversación en la UI permite revisión humana caso a caso.
8. Los casos ambiguos como “¿no tienen usadas?” se mantienen en `null` (correcto:
   no inventar).

---

## Apéndice — Reproducibilidad

- Ground truth y volcado de la muestra: script de auditoría (fuera de `app/`),
  leyendo `data/conversaciones.json` y `reports/ai_benchmark.json` en modo lectura.
- Exposición del corpus: regex deterministas sobre texto normalizado
  (`app.text.normalize_key`), sin IA, sobre las 677 conversaciones.
- No se ejecutó el LLM, no se reprocesó IA, no se escribió en `data/` ni en la
  base de datos, y no se modificó código de producción.
