# AI extraction benchmark

- generated_at: 2026-09-14T19:51:43+00:00
- schema_version: v1
- prompt_version: v2
- cases: 10

## Benchmark cases

| case | conversation_id | lead_id | messages |
|---|---|---|---|
| modelo_claro | CONV-00587 | LD-01329 | 6 |
| modelo_variacion | CONV-00030 | LD-00122 | 3 |
| presupuesto | CONV-00229 | LD-00430 | 7 |
| cuota | CONV-00613 | LD-01377 | 7 |
| financiacion | CONV-00060 | LD-00068 | 7 |
| solicitud_cita | CONV-00502 | LD-00681 | 8 |
| cotizacion_contexto | CONV-00018 | LD-00273 | 7 |
| objecion | CONV-00271 | LD-00648 | 6 |
| ambigua | CONV-00210 | LD-01394 | 6 |
| poca_evidencia | CONV-00267 | LD-00498 | 3 |

## Baseline v1 vs actual v2

El baseline anterior se conserva (ver historial git de `reports/ai_benchmark.json`). Comparación de métricas por proveedor:

| provider | baseline válido | actual válido | baseline campos | actual campos |
|---|---|---|---|---|
| ollama | 0.8 (10 req) | 1.0 (10 req) | 18 | 17 |
| openrouter | None (0 req) | None (0 req) | 0 | 0 |

- baseline generated_at: 2026-09-14T18:23:28+00:00

## Provider: ollama

- model: qwen2.5:3b
- available: True (ok)
- request_success_rate: 1.0 · schema_valid_rate: 1.0
- latency: avg 6229.9 ms · median 5703.0 ms
- fields_extracted: 17 · fields_with_evidence: 16 · evidence_rate: 0.9412

### Manual review

| case | ok | schema | model_interes | presupuesto | cuota_inicial | forma_pago | intencion | objecion | cita | cotizacion | ev |
|---|---|---|---|---|---|---|---|---|---|---|---|
| modelo_claro | True | True | Bajaj Pulsar RS 200 | None | None | None | None | None | None | None | 1 |
| modelo_variacion | True | True | AKT TTR 200 | None | None | None | None | None | None | None | 1 |
| presupuesto | True | True | Honda Navi | None | None | None | None | None | None | True | 2 |
| cuota | True | True | Honda CB 125F Twister | None | None | None | None | None | None | True | 2 |
| financiacion | True | True | AKT Dynamic R3 125 | None | None | None | None | None | None | True | 1 |
| solicitud_cita | True | True | Hero Eco Deluxe 100 | None | 2000000.0 | None | None | None | True | None | 3 |
| cotizacion_contexto | True | True | Bajaj Dominar 400 | None | None | None | None | cuota | None | True | 3 |
| objecion | True | True | AKT NKD 125 | None | None | None | None | None | None | None | 1 |
| ambigua | True | True | Suzuki GN 125 | None | None | None | None | None | None | None | 1 |
| poca_evidencia | True | True | Hero Eco Deluxe 100 | None | None | None | None | None | None | None | 1 |

## Provider: openrouter

- model: None
- available: False (OPENROUTER_API_KEY not configured)
