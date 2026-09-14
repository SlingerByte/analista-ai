# AI extraction benchmark (AI-0)

- generated_at: 2026-09-14T18:23:28+00:00
- schema_version: v1
- prompt_version: v1
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

## Provider: ollama

- model: qwen2.5:3b
- available: True (ok)
- request_success_rate: 1.0 · schema_valid_rate: 0.8
- latency: avg 6146.1 ms · median 5950.5 ms
- fields_extracted: 18 · fields_with_evidence: 18 · evidence_rate: 1.0
- errors: ['schema validation failed: 1 error(s)', 'schema validation failed: 1 error(s)']

### Manual review

| case | ok | schema | model_interes | presupuesto | cuota_inicial | forma_pago | intencion | objecion | cita | cotizacion | ev |
|---|---|---|---|---|---|---|---|---|---|---|---|
| modelo_claro | True | True | Bajaj Pulsar RS 200 | None | None | None | None | None | None | None | 1 |
| modelo_variacion | True | True | AKT TTR 200 | None | None | None | None | None | None | True | 2 |
| presupuesto | True | True | Honda Navi | None | 480000.0 | None | None | None | None | True | 3 |
| cuota | True | True | Honda CB 125F Twister | None | 480000.0 | None | None | cuota | None | True | 4 |
| financiacion | True | False | None | None | None | None | None | None | None | None | 0 |
| solicitud_cita | True | True | Hero Eco Deluxe 100 | None | 2000000.0 | None | None | None | True | None | 3 |
| cotizacion_contexto | True | False | None | None | None | None | None | None | None | None | 0 |
| objecion | True | True | AKT NKD 125 | None | None | None | None | None | None | None | 1 |
| ambigua | True | True | Suzuki GN 125 | None | None | None | None | None | None | True | 2 |
| poca_evidencia | True | True | Hero Eco Deluxe 100 | None | None | None | None | None | None | True | 2 |

## Provider: openrouter

- model: None
- available: False (OPENROUTER_API_KEY not configured)

