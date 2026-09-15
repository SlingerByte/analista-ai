# Benchmark comparativo de extracción IA (gold set)

> Fase 2.8 — Benchmark. **No se modificó producción.**
> Repositorio base: `2e91957`. Prompt `v2`, schema `v1`, validación determinista
> productiva aplicada a la salida de cada modelo. Datos sintéticos.

---

## 1. Objetivo

Construir un **gold set reproducible** anotado sobre la conversación original y
comparar objetivamente varios modelos locales de extracción, para responder:

> ¿Qué modelo + prompt produce la extracción semánticamente más confiable para
> este negocio y qué errores afectan realmente la priorización comercial?

Esta fase **no implementa correcciones**: deja evidencia para decidir Phase 2.9.

---

## 2. Metodología

- **Fuente de verdad:** `data/conversaciones.json` (conversación original,
  mensaje a mensaje). El gold se derivó de lo declarado por **el cliente**, no de
  lo que ofrece el asesor.
- **Selección estratificada** de 110 conversaciones (ver §3), no las primeras.
- **Mismo input para todos los modelos:** mismo prompt, schema, transcript y
  validación determinista (`app/ai/validation.py`). Se registran `raw` y
  `validated`.
- **Motor:** Ollama local (`http://localhost:11434`), sin coste externo.
- **Tooling separado de producción:** `scripts/build_gold_set.py`,
  `scripts/run_ai_benchmark.py`, `scripts/evaluate_ai_benchmark.py`,
  `scripts/ai_gold_rules.py`. No escriben en la base de datos productiva.
- **Artefactos:** `reports/gold_set.json`, `reports/ai_gold_benchmark.json`,
  `reports/ai_gold_metrics.json` (detalle por conversación y por campo).

**Limitación central (declarada):** el gold es **asistido por reglas y revisado
por el analista** leyendo las 110 conversaciones y ajustando las reglas
generales. No es un gold 100 % humano independiente. Por eso las métricas son
útiles sobre todo **de forma comparativa** entre modelos y como cota
conservadora, no como accuracy absoluta del negocio.

---

## 3. Composición del gold set

110 conversaciones seleccionadas con cuotas deterministas (las primeras que
cumplen la condición, ordenadas por `conversation_id`; se incluye el caso de
control `CONV-00058`). Incluye diversidad explícita: inicial explícita, forma de
pago, objeciones, cita, cotización, cambio de modelo, intención alta/baja,
conversaciones cortas y largas, y casos informativos.

| Señal en el cliente | Conversaciones (gold no nulo) |
|---|---:|
| `model_interes` | 110 |
| `intencion_compra` | 97 (47 alta, 31 baja, 14 informativa, 5 media) |
| `presupuesto` | 0 |
| `cuota_inicial` | 68 (23× 1.000.000, 19× 0, 9× 2.000.000, …) |
| `forma_pago` | 66 (58 financiación, 8 contado) |
| `objecion` | 48 (32 precio, 8 financiación, 6 disponibilidad, 2 otra) |
| `solicitud_cita` | 47 |
| `solicitud_cotizacion` | 41 |

Confianza de anotación: 58 alta, 46 media, 6 baja. `presupuesto = null` en todas
(conservador: no se declara presupuesto total en la muestra).

---

## 4. Reglas de anotación (resumen)

- **Modelo:** solo menciones del **cliente** contra `catalogo_motos.csv`. Con un
  solo modelo → ese. Con varios → el **vigente** solo si el cliente lo confirma
  después (“esa sí me sirve”, aceptación); si no, `null` ambiguo.
- **Intención:** se evalúa el contexto completo; la última señal decide.
  Cortesías (`ok`, `dale`, `gracias`) no generan intención. `alta`/`media`/`baja`
  /`informativa`/`null`.
- **Presupuesto:** solo capacidad/presupuesto total del cliente; nunca precio del
  asesor, cuota mensual ni cuota inicial.
- **Cuota inicial:** monto de entrada/inicial explícito; “no tengo inicial” → 0.
  Cuota mensual y precio total **no** se convierten en inicial.
- **Forma de pago:** solo si el cliente la declara (“financiada”, “a crédito”,
  “de contado”). La pregunta del asesor no cuenta.
- **Objeción:** barrera real del cliente (precio, cuota, financiación,
  disponibilidad, otra). Una pregunta de precio no es objeción por sí sola.
- **Cita:** el cliente pide/indica visita o confirma que va; el ofrecimiento del
  asesor no cuenta.
- **Cotización:** petición explícita del cliente (incluye “mándela/envíemela”).
- **Evidencia:** cada valor positivo exige cita del cliente (la validación
  productiva se aplica después).

---

## 5. Modelos evaluados

| Modelo | Provider | Parámetros | Disponibilidad |
|---|---|---|---|
| `qwen2.5:3b` | Ollama (local) | 3B | disponible |
| `llama3.2:3b` | Ollama (local) | 3B | descargado para el benchmark |
| `qwen2.5:7b` | Ollama (local) | 7B | descargado para el benchmark |

OpenRouter no se evaluó: **no hay `OPENROUTER_API_KEY`** en el entorno (no se
solicitaron ni usaron credenciales).

---

## 6. Métricas (110 conversaciones × 8 campos = 880 decisiones)

Global (validado; `FP` incluye valor equivocado; `presupuesto` con gold nulo
penaliza cualquier valor inventado):

| Modelo | Accuracy | Precision | Recall | TP | FP | FN | TN | Latencia media |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen2.5:3b` | 0,644 | **0,867** | 0,403 | 196 | **30** | 290 | 383 | **5,8 s** |
| `llama3.2:3b` | 0,649 | 0,748 | 0,494 | 240 | 81 | 246 | 364 | 6,7 s |
| `qwen2.5:7b` | **0,652** | 0,676 | **0,609** | 296 | 142 | **190** | 327 | 13,9 s |

Por campo (accuracy / precision / recall):

| Campo | qwen2.5:3b | llama3.2:3b | qwen2.5:7b |
|---|---|---|---|
| `model_interes` | 0,791 / 0,845 / 0,791 | 0,682 / 0,790 / 0,682 | **0,955 / 1,00 / 0,955** |
| `intencion_compra` | 0,182 / 1,00 / 0,082 | 0,427 / 0,603 / 0,418 | 0,436 / 0,469 / **0,469** |
| `presupuesto` | 0,900 / 0,00 / – | 0,900 / 0,00 / – | 0,700 / 0,00 / – |
| `cuota_inicial` | 0,564 / 1,00 / 0,294 | 0,627 / 0,935 / **0,426** | 0,564 / 1,00 / 0,294 |
| `forma_pago` | 0,436 / 1,00 / 0,061 | 0,755 / 0,710 / **0,742** | **0,773 / 0,804 / 0,621** |
| `objecion` | 0,518 / 0,500 / 0,054 | 0,482 / 0,00 / 0,00 | 0,373 / 0,190 / 0,196 |
| `solicitud_cita` | 0,909 / 1,00 / 0,787 | 0,918 / 1,00 / 0,809 | **0,982 / 1,00 / 0,957** |
| `solicitud_cotizacion` | **0,964 / 1,00 / 0,902** | 0,700 / 1,00 / 0,195 | 0,882 / 1,00 / 0,683 |

Tasa de `schema_valid` = **1,0** en los tres modelos. Todos los campos pasaron la
validación determinista, de modo que los FP de `presupuesto`/`objecion` son
falsos positivos que **sobreviven la validación** (no son falta de evidencia).

---

## 7. Matriz de errores (principal, `qwen2.5:7b`)

| Campo | Modelo | FP | FN | Principal causa | Impacto |
|---|---|---:|---:|---|---|
| `presupuesto` | qwen2.5:7b | **33** | 0 | MODEL: confunde inicial/precio con presupuesto | HIGH |
| `intencion_compra` | qwen2.5:7b | 52 | 52 | MODEL/PROMPT: umbral y señales ambiguas | HIGH |
| `objecion` | qwen2.5:7b | 47 | 45 | MODEL: etiqueta preguntas como objeción | MEDIUM |
| `model_interes` | qwen2.5:7b | 0 | 5 | MODEL: solo 5 fallos (cambio de modelo) | HIGH |
| `cuota_inicial` | qwen2.5:7b | 0 | 48 | MODEL: no detecta montos coloquiales | MEDIUM |
| `forma_pago` | qwen2.5:7b | 10 | 25 | MODEL: omite declaraciones del cliente | HIGH |
| `solicitud_cita` | qwen2.5:7b | 0 | 2 | MODEL: casi perfecto | MEDIUM |
| `solicitud_cotizacion` | qwen2.5:7b | 0 | 13 | MODEL: omite aceptación explícita | LOW |

Comparativa de FP por campo (donde difieren los modelos):

| Campo | 3b FP/FN | llama FP/FN | 7b FP/FN |
|---|---|---|---|
| `presupuesto` | 11 / 0 | 11 / 0 | 33 / 0 |
| `intencion_compra` | 0 / 90 | 27 / 57 | 52 / 52 |
| `objecion` | 3 / 53 | 1 / 56 | 47 / 45 |
| `cuota_inicial` | 0 / 48 | 2 / 39 | 0 / 48 |
| `forma_pago` | 0 / 62 | 20 / 17 | 10 / 25 |

---

## 8. Análisis por campo

- **`model_interes`:** `qwen2.5:7b` es casi perfecto (105/110) y resuelve el
  cambio de modelo (CONV-00058 → AKT NKD 125). Los modelos 3B tienden a quedarse
  con el **modelo inicial** (error de mayor impacto para la gestión del asesor).
- **`intencion_compra`:** el punto más débil de todos. `qwen2.5:3b` es casi
  siempre `null` (recall 0,08) y `qwen2.5:7b` mejora recall pero con FP (0,47).
  Es un problema de **prompt + modelo**: falta una guía de calibración y el
  modelo pequeño no la infiere.
- **`presupuesto`:** el gold no tiene ningún presupuesto total, pero los tres
  modelos inventan valores (33 en 7b). Es confusión **inicial/precio vs
  presupuesto** que sobrevive la validación: riesgo de crear capacidad económica
  inexistente.
- **`cuota_inicial`:** `llama3.2:3b` es el mejor (recall 0,43, precision 0,94);
  `qwen2.5:7b` acierta las explícitas pero falla las coloquiales (“1 palos”).
- **`forma_pago`:** `qwen2.5:7b` y `llama3.2:3b` capturan bien “financiada/A
  crédito”; `qwen2.5:3b` la omite casi siempre.
- **`objecion`:** todos fallan; `qwen2.5:7b` sobre-etiqueta (47 FP), los 3B casi
  no detectan. Taxonomía ambigua (pregunta vs barrera).
- **`solicitud_cita`:** `qwen2.5:7b` excelente (0,96 recall, 1,0 precision);
  resuelve bien cliente-solicita vs asesor-ofrece.
- **`solicitud_cotizacion`:** `qwen2.5:3b` muy bueno (0,90); `llama3.2:3b` malo
  (0,20).

---

## 9. Impacto comercial (por error, sin modificar scoring)

Puntos reales de `SCORE_V1_PARAMS`:

| Error | Efecto en scoring | Prioridad |
|---|---|---|
| `forma_pago` FN | pierde `FORMA_PAGO_DECLARADA` (+5) | HIGH |
| `intencion_compra` FN | pierde alta +30 / media +15 / baja +5 | HIGH |
| `solicitud_cita` FN | pierde `CLIENTE_PIDIO_CITA` (+20) y urgencia “Hoy” (override 100) | HIGH |
| Modelo inicial vs vigente | el asesor gestiona la moto equivocada (no toca score, sí gestión) | HIGH |
| `cuota_inicial` FN | pierde `CUOTA_SUFICIENTE` (+5 si ≥20% del precio) | MEDIUM |
| `objecion` FP/FN | aplica/no aplica penalización errónea (−3 a −10) y no alerta al asesor | MEDIUM |
| `presupuesto` FP | activa `PRESUPUESTO_COMPATIBLE` (+10) con capacidad inventada | HIGH |
| `solicitud_cotizacion` FN | pierde +10 prioridad y +0,15 urgencia | LOW |

Ejemplo CONV-00058 (gold: inicial 1M, cita true, intención alta): `qwen2.5:3b`
pierde la inicial (0 puntos) y el modelo vigente; `qwen2.5:7b` inventa
`presupuesto=10.000.000` y `cuota_inicial=10.000.000` (FP), distorsionando la
capacidad de pago mostrada al asesor.

---

## 10. Caso CONV-00058

Gold: `model_interes = AKT NKD 125` (vigente, confirmado con “esa sí me sirve”),
`cuota_inicial = 1.000.000`, `intencion_compra = alta`, `solicitud_cita = true`,
`objecion = precio`, `forma_pago = null`.

| Modelo | modelo | intención | inicial | cita | objeción | presupuesto |
|---|---|---|---|---|---|---|
| gold | AKT NKD 125 | alta | 1.000.000 | true | precio | null |
| qwen2.5:3b | Honda CB 125F Twister ✗ | alta ✓ | null ✗ | true ✓ | null ✗ | null ✓ |
| llama3.2:3b | Honda CB 125F Twister ✗ | alta ✓ | 1.000.000 ✓ | true ✓ | null ✗ | null ✓ |
| qwen2.5:7b | AKT NKD 125 ✓ | alta ✓ | 10.000.000 ✗ | true ✓ | null ✗ | 10.000.000 ✗ |

El caso **no** se convirtió en regla especial: es el ejemplo general de (a) modelo
inicial vs vigente y (b) extracción monetaria coloquial / confusión
inicial-presupuesto.

---

## 11. Ranking de modelos

| Modelo | Accuracy | Recall | Precision | FP | FN | Latencia | Recomendación |
|---|---:|---:|---:|---:|---:|---:|---|
| `qwen2.5:7b` | 0,652 | **0,609** | 0,676 | 142 | **190** | 13,9 s | **Baseline recomendado** por recall comercial (modelo, cita, forma de pago) |
| `llama3.2:3b` | 0,649 | 0,494 | 0,748 | 81 | 246 | 6,7 s | Alternativa liviana; mejor inicial coloquial |
| `qwen2.5:3b` | 0,644 | 0,403 | **0,867** | **30** | 290 | **5,8 s** | Mayor precisión, recall insuficiente para priorizar |

Criterios más allá de accuracy: el sistema **prioriza reducir falsos negativos
comerciales**, manteniendo FP controlados; preservar evidencia; latencia
razonable en batch; coste cero local; reproducibilidad. `qwen2.5:7b` gana en
recall y en los campos de mayor impacto (modelo, cita, forma de pago), a costa de
más FP que deben contenerse con prompt/validación. Ninguno resuelve `objecion`.

---

## 12. Limitaciones

1. **Gold asistido por reglas** (revisado sobre las 110 conversaciones): mide
   acuerdo, no verdad absoluta. Los números son comparables entre modelos.
2. **Sin proveedor remoto** (no hay `OPENROUTER_API_KEY`): no se pudo evaluar un
   modelo mayor/API que probablemente mejore la calidad.
3. **Solo Ollama local** y modelos ≤7B; el benchmark es reproducible pero acotado.
4. El benchmark mide la extracción **después de la validación determinista**;
   los FP que sobreviven son errores semánticos reales.
5. La prevalencia del corpus (677) es mayor que la muestra; no extrapolar.

---

## 13. Recomendación para Phase 2.9

1. **Adoptar `qwen2.5:7b` como baseline local** de extracción (mejor recall de
   señales comerciales), manteniendo la validación determinista como contención
   de FP.
2. **Reformular el prompt** con: (a) regla explícita “inicial ≠ mensual ≠ precio ≠
   presupuesto” con ejemplos; (b) calibración de `intencion_compra`; (c) taxonomía
   de objeción (pregunta vs barrera).
3. **Representar modelo inicial vs vigente** (un solo `model_interes` no basta:
   era el error dominante de los 3B).
4. **Evaluar un modelo remoto** cuando exista clave, contra este mismo gold.
5. **Completar la anotación humana** del gold set (hoy asistida por reglas) para
   convertir las métricas en accuracy absoluta.

### Reproducibilidad

```bash
uv run python scripts/build_gold_set.py --target 110
uv run python scripts/run_ai_benchmark.py --model qwen2.5:3b
uv run python scripts/run_ai_benchmark.py --model llama3.2:3b
uv run python scripts/run_ai_benchmark.py --model qwen2.5:7b
uv run python scripts/evaluate_ai_benchmark.py
```

No escribe en la base de datos productiva ni modifica prompts/schema/scoring.
