# Groq GPT-OSS-20B — Controlled Benchmark

Model: openai/gpt-oss-20b | Provider: groq | Prompt: v2 | Schema: v1 | Validation: producción | Persistence: none

## Executive summary

- conversaciones: 10/10 (CONV-00058, CONV-00001, CONV-00002, CONV-00011, CONV-00003, CONV-00004, CONV-00005, CONV-00006, CONV-00007, CONV-00008)
- requests HTTP: 10 (máx. 15)
- disponibilidad: ok=8/10 (rate=0.8), rate_limited=2, timeouts=0, errors=0, 429s=2
- detención anticipada: False (None)
- schema válido: 8/8 (rate=1.0)
- latencia ok (ms): avg=1657.9 median=1554.0 min=1369 max=2313 p95=2313.0 n=8
- calidad (graded=8): accuracy=0.7571 precision=0.7273 recall=0.75

## Results

| Campo | Accuracy | Precision | Recall | TP | FP | FN |
| ----- | -------: | --------: | -----: | -: | -: | -: |
| model_interes | 1.0 | 1.0 | 1.0 | 8 | 0 | 0 |
| intencion_compra | 0.375 | 0.375 | 0.5 | 3 | 5 | 3 |
| forma_pago | 0.875 | 0.8 | 0.8 | 4 | 1 | 1 |
| objecion | 0.375 | 0.0 | 0.0 | 0 | 3 | 4 |
| presupuesto | 1.0 | None | None | 0 | 0 | 0 |
| cuota_inicial | 1.0 | 1.0 | 1.0 | 3 | 0 | 0 |
| solicitud_cita | 1.0 | 1.0 | 1.0 | 2 | 0 | 0 |
| solicitud_cotizacion | 1.0 | 1.0 | 1.0 | 4 | 0 | 0 |

## Per-conversation results

| Conversation | Status | Latency | Schema | Correct fields |
| ------------ | ------ | ------: | ------ | -------------: |
| CONV-00058 | ok | 1778 | True | 7/8 |
| CONV-00001 | ok | 1439 | True | 8/8 |
| CONV-00002 | ok | 1480 | True | 6/8 |
| CONV-00011 | ok | 1776 | True | 6/8 |
| CONV-00003 | ok | 1508 | True | 8/8 |
| CONV-00004 | ok | 2313 | True | 6/8 |
| CONV-00005 | rate_limited | None | None | - |
| CONV-00006 | ok | 1369 | True | 5/8 |
| CONV-00007 | rate_limited | None | None | - |
| CONV-00008 | ok | 1600 | True | 7/8 |

## Error analysis

- modelo: {'mismatches': []} — posible confusión entre primer modelo mencionado y modelo vigente
- intencion: {'mismatches': ['CONV-00002', 'CONV-00011', 'CONV-00004', 'CONV-00006', 'CONV-00008']} — informativa convertida en alta, o señales ('me sirve', 'voy') ignoradas
- presupuesto: {'mismatches': [], 'cuota_confudida_como_presupuesto': []} — gold presupuesto es null en todo el Gold Set: cualquier valor es invención
- inicial: {'mismatches': []} — cuota mensual del asesor convertida en inicial, o inicial del cliente ignorada
- forma_pago: {'mismatches': ['CONV-00006'], 'cuota_implica_financiacion': []} — mencionar inicial no implica financiacion si el cliente no lo dijo
- objecion: {'mismatches': ['CONV-00058', 'CONV-00002', 'CONV-00011', 'CONV-00004', 'CONV-00006']} — 'muy cara' / 'mas economico' / 'cuota alta' detectadas o ignoradas
- cita: {'mismatches': []} — 'los visito' / 'puedo pasar' detectadas; solo cliente cuenta como evidencia
- cotizacion: {'mismatches': []} — 'dale' / 'ok' / 'listo' no son solicitud de cotización

## CONV-00058

status=ok validation_errors={}

| field | gold | groq | evidencia | veredicto |
|---|---|---|---|---|
| model_interes | AKT NKD 125 | AKT NKD 125 | tipo la AKT NKD 125 | correcto |
| intencion_compra | alta | alta | Esa sí me sirve | correcto |
| forma_pago | None | None | None | correcto |
| objecion | precio | None | None | incorrecto |
| presupuesto | None | None | None | correcto |
| cuota_inicial | 1000000.0 | 1000000.0 | Tengo como 1 millonzitos de inicial | correcto |
| solicitud_cita | True | True | ¿Mañana los visito? | correcto |
| solicitud_cotizacion | None | None | None | correcto |

## Comparison

Solo datos observados, sin ranking ni recomendación automática.

| model | accuracy | precision | recall | n |
|---|---|---|---|---|
| qwen2.5:3b | 0.644 | 0.8673 | 0.4033 | 110 |
| llama3.2:3b | 0.6488 | 0.7477 | 0.4938 | 110 |
| qwen2.5:7b | 0.6524 | 0.6758 | 0.6091 | 110 |
| z-ai/glm-5.2:free (controlled,20) | None | None | None | 0 |
| openai/gpt-oss-20b (controlled, 8 graded) | 0.7571 | 0.7273 | 0.75 | 8 |

## Engineering interpretation

1. ¿Groq respondió de manera consistente? ok=8/10, rate_limited=2, 429s=2.
2. ¿El schema fue válido? 8/8 (rate=1.0).
3. ¿La latencia es razonable para una demo? avg=1657.9 ms, median=1554.0 ms, max=2313 ms (n=8).
4. ¿Hubo rate limiting? rate_limited=2, detención anticipada=False (None).
5. ¿Qué campos parecen más confiables? model_interes (acc=1.0), presupuesto (acc=1.0), cuota_inicial (acc=1.0), solicitud_cita (acc=1.0), solicitud_cotizacion (acc=1.0).
6. ¿Qué campos siguen siendo problemáticos? intencion_compra, forma_pago, objecion.
7. ¿El modelo cometió inferencias peligrosas? cuota→presupuesto: []; cuota→financiación: [].
8. ¿Qué diferencias hay frente a los benchmarks locales? Ver tabla Comparison (bases distintas: 110 vs slice de 10; GLM-5.2 sin calidad observable por 429).

> Prompt, schema y validator intactos. Patrones nuevos van como hallazgo, no como parche.
