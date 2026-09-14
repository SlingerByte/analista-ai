"""Corre el scoring v1 sobre los datos reales de `data/` (solo lectura).

Las señales IA van en null: la extracción aún no se persiste, y un lead sin
conversación no se penaliza (ver `BASE_GESTIONABLE`). La fecha de referencia
es la máxima fecha de registro confiable del propio archivo (determinista).
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.ingestion import loaders
from app.ingestion.catalog import build_catalog_index, match_model
from app.ingestion.normalizers import (
    classify_date,
    is_valid_email,
    normalize_city,
    normalize_estado,
    normalize_phone,
    normalized_date_value,
)
from app.scoring.engine import score_lead
from app.scoring.signals import LeadSignals


def _load_catalog(data_dir: Path) -> tuple[dict[str, float], list[tuple[str, str, str]]]:
    prices: dict[str, float] = {}
    entries: list[tuple[str, str, str]] = []
    with open(data_dir / "catalogo_motos.csv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                prices[row["sku"]] = float(row["precio_lista"])
                entries.append((row["sku"], row.get("marca", ""), row.get("linea", "")))
            except (KeyError, TypeError, ValueError):
                continue
    return prices, entries


def main() -> None:
    data_dir = loaders.DATA_DIR
    with open(data_dir / "leads.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    prices, catalog_entries = _load_catalog(data_dir)
    catalog_index = build_catalog_index(catalog_entries)

    with open(data_dir / "conversaciones.json", encoding="utf-8") as fh:
        raw_conversations = json.load(fh)
    with_conversation = {
        str(item.get("lead_id")) for item in raw_conversations if item.get("lead_id")
    }

    # Fecha de referencia determinista: máximo registro confiable.
    reg_values: list[datetime] = []
    for row in rows:
        value = normalized_date_value(classify_date(row.get("fecha_registro")))
        if value is not None:
            reg_values.append(value.replace(tzinfo=None))
    reference = max(reg_values) if reg_values else datetime.now()

    results = []
    for row in rows:
        lead_id = (row.get("lead_id") or "").strip()
        phone_norm = normalize_phone(row.get("telefono") or "")
        phone_valid = phone_norm is not None and len(phone_norm) == 10
        email_raw = (row.get("email") or "").strip()
        city_raw = (row.get("ciudad") or "").strip()
        _, _, city_matched = normalize_city(city_raw or None)
        model_match = match_model((row.get("modelo_interes_texto") or "").strip() or None,
                                  catalog_index)
        sku = model_match["sku"]
        reg_info = classify_date(row.get("fecha_registro"))
        reg_value = normalized_date_value(reg_info)
        trustworthy = reg_value is not None
        days = (reference - reg_value.replace(tzinfo=None)).days if trustworthy else None
        first_contact_raw = (row.get("fecha_primer_contacto") or "").strip()

        signals = LeadSignals(
            lead_id=lead_id,
            list_price=prices.get(sku) if sku else None,
            model_resolved=sku is not None,
            has_conversation=lead_id in with_conversation,
            phone_valid=phone_valid,
            email_present=is_valid_email(email_raw or None),
            city_present=bool(city_raw),
            registration_trustworthy=trustworthy,
            estado_gestion=normalize_estado(row.get("estado_gestion")),
            days_since_registration=days,
            has_first_contact=bool(first_contact_raw),
        )
        results.append(score_lead(signals))

    commercials = [r.commercial for r in results]
    queues = [r.queue for r in results]
    bands = Counter(r.band for r in results)
    urgencies = Counter(r.urgency_band for r in results)

    print(f"Leads procesados: {len(results)} (señales IA en null: extracción aún no persistida)")
    print(f"Commercial: min {min(commercials)} · max {max(commercials)} · "
          f"media {sum(commercials) / len(commercials):.1f}")
    print(f"Queue: min {min(queues)} · max {max(queues)}")
    print(f"Bandas: {dict(bands)} · Urgencia: {dict(urgencies)}")
    for label in ("Alta", "Media", "Baja"):
        sample = [r for r in results if r.band == label][:2]
        for r in sample:
            top = sorted(r.reasons, key=lambda x: -abs(x.contribution))[:3]
            detail = "; ".join(f"{x.code}({x.contribution:+g})" for x in top)
            print(f"  [{label}] {r.lead_id}: commercial={r.commercial} urgency={r.urgency} "
                  f"queue={r.queue} quality={r.quality} :: {detail}")


if __name__ == "__main__":
    main()
