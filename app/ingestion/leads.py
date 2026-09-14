from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ingestion import loaders
from app.ingestion.catalog import build_catalog_index, match_model
from app.ingestion.normalizers import (
    classify_date,
    date_reason,
    is_valid_email,
    normalize_canal,
    normalize_city,
    normalize_email,
    normalize_estado,
    normalize_phone,
    normalized_date_value,
)
from app.models import CatalogItem, Company, Lead, PointOfSale


def _build_meta(row, reg_info, cont_info, phone_raw, phone_norm, phone_valid, email_raw, email_valid, city_raw, city_label, city_key, city_matched, canal_raw, canal_value, estado_raw, estado_value, model_match, anomalies):
    return {
        "phone": {
            "raw": phone_raw,
            "normalized": phone_norm,
            "method": "phone_canonical",
            "is_valid": phone_valid,
            "reason": None if phone_valid else "no queda en 10 dígitos tras quitar prefijo 57",
        },
        "email": {
            "raw": email_raw,
            "normalized": normalize_email(email_raw),
            "method": "email_canonical",
            "is_valid": email_valid,
        },
        "city": {
            "raw": city_raw,
            "normalized": city_label,
            "key": city_key,
            "method": "city_canonical",
            "matched": city_matched,
        },
        "channel": {"raw": canal_raw, "normalized": canal_value},
        "status": {"raw": estado_raw, "normalized": estado_value},
        "model": {
            "raw": model_match["raw"],
            "sku": model_match["sku"],
            "state": model_match["state"],
            "match_type": model_match["match_type"],
            "method": model_match["method"],
            "score": model_match["score"],
            "candidates": model_match["candidates"],
        },
        "registration_date": {
            "raw": row.get("fecha_registro"),
            "normalized": reg_info["parsed"].isoformat() if reg_info["parsed"] else None,
            "persisted": normalized_date_value(reg_info).isoformat() if normalized_date_value(reg_info) else None,
            "format": reg_info["format"],
            "is_ambiguous": reg_info["ambiguous"],
            "reason": date_reason(reg_info),
        },
        "first_contact_date": {
            "raw": row.get("fecha_primer_contacto"),
            "normalized": cont_info["parsed"].isoformat() if cont_info["parsed"] else None,
            "persisted": normalized_date_value(cont_info).isoformat() if normalized_date_value(cont_info) else None,
            "format": cont_info["format"],
            "is_ambiguous": cont_info["ambiguous"],
            "reason": date_reason(cont_info),
        },
        "anomalies": anomalies,
    }


def ingest_leads(session: Session, run_id: int, data_dir: Path) -> dict:
    rows = loaders.read_csv(data_dir / loaders.LEADS_FILE)

    catalog_rows = session.execute(
        sa.select(CatalogItem.sku, CatalogItem.brand, CatalogItem.line)
    ).all()
    catalog_index = build_catalog_index(catalog_rows)

    company_ids = set(session.scalars(sa.select(Company.company_id)).all())
    pv_company = dict(
        session.execute(
            sa.select(PointOfSale.point_of_sale_id, PointOfSale.company_id)
        ).all()
    )

    grouped: dict[str, list[tuple[int, dict]]] = {}
    for row_number, row in enumerate(rows, start=1):
        lead_id = (row.get("lead_id") or "").strip()
        grouped.setdefault(lead_id, []).append((row_number, row))

    inserted = updated = unchanged = 0
    duplicate_count = 0
    duplicate_ids: list[str] = []
    duplicates_detail: list[dict] = []
    ambiguous_registration = 0
    ambiguous_first_contact = 0
    ambiguous_by_convention = 0
    unknown_dates = 0
    chronology_inconsistencies = 0
    managed_without_first_contact = 0
    invalid_phones = 0
    cities_normalized = 0
    cities_unmatched = 0
    invalid_references = 0
    models_matched = models_ambiguous = models_unmatched = models_empty = 0
    anomalies: list[dict] = []

    for lead_id, occurrences in grouped.items():
        row_number, row = occurrences[0]
        extras = occurrences[1:]
        if extras:
            duplicate_count += len(extras)
            duplicate_ids.append(lead_id)

        company_id = (row.get("empresa_id") or "").strip()
        point_of_sale_id = (row.get("punto_venta_id") or "").strip()
        if (
            company_id not in company_ids
            or point_of_sale_id not in pv_company
            or pv_company[point_of_sale_id] != company_id
        ):
            invalid_references += 1
            anomalies.append(
                {
                    "type": "invalid_company_or_point_of_sale",
                    "lead_id": lead_id,
                    "company_id": company_id,
                    "point_of_sale_id": point_of_sale_id,
                }
            )
            continue

        phone_raw = row.get("telefono") or ""
        phone_norm = normalize_phone(phone_raw)
        phone_valid = phone_norm is not None and len(phone_norm) == 10
        if not phone_valid:
            invalid_phones += 1

        email_raw = (row.get("email") or "").strip() or None
        email_valid = is_valid_email(email_raw)

        city_raw = (row.get("ciudad") or "").strip() or None
        city_label, city_key, city_matched = normalize_city(city_raw)
        if city_raw:
            if city_matched:
                cities_normalized += 1
            else:
                cities_unmatched += 1

        canal_raw = row.get("canal")
        canal_value = normalize_canal(canal_raw)
        estado_raw = row.get("estado_gestion")
        estado_value = normalize_estado(estado_raw)

        model_raw = (row.get("modelo_interes_texto") or "").strip() or None
        model_match = match_model(model_raw, catalog_index)
        if model_match["state"] == "matched":
            models_matched += 1
        elif model_match["state"] == "ambiguous":
            models_ambiguous += 1
        elif model_match["state"] == "unmatched":
            models_unmatched += 1
        else:
            models_empty += 1

        reg_info = classify_date(row.get("fecha_registro"))
        cont_info = classify_date(row.get("fecha_primer_contacto"))
        reg_value = normalized_date_value(reg_info)
        cont_value = normalized_date_value(cont_info)

        row_anomalies: list[str] = []
        if reg_info["format"] == "DD/MM/YYYY vs MM/DD/YYYY":
            ambiguous_registration += 1
            row_anomalies.append("ambiguous_registration_date")
        if cont_info["format"] == "DD/MM/YYYY vs MM/DD/YYYY":
            ambiguous_first_contact += 1
            row_anomalies.append("ambiguous_first_contact_date")
        if reg_info["ambiguous"] and reg_info["format"] == "DD-MM-YYYY":
            ambiguous_by_convention += 1
        if reg_info["format"] == "desconocido":
            unknown_dates += 1
            row_anomalies.append("unknown_registration_date")
        if cont_info["format"] == "desconocido":
            unknown_dates += 1
            row_anomalies.append("unknown_first_contact_date")
        if (
            reg_value
            and cont_value
            and not reg_info["ambiguous"]
            and not cont_info["ambiguous"]
            and cont_value < reg_value
        ):
            chronology_inconsistencies += 1
            row_anomalies.append("first_contact_before_registration")
        if (
            estado_value
            and estado_value != "Sin gestión"
            and not (row.get("fecha_primer_contacto") or "").strip()
        ):
            managed_without_first_contact += 1
            row_anomalies.append("managed_without_first_contact")
        if not phone_valid:
            row_anomalies.append("invalid_phone")
        if not city_raw:
            row_anomalies.append("missing_city")
        if city_raw and not city_matched:
            row_anomalies.append("unmatched_city")
        if model_match["state"] == "ambiguous":
            row_anomalies.append("ambiguous_model")
        if model_match["state"] == "unmatched":
            row_anomalies.append("unmatched_model")
        if canal_value is None:
            row_anomalies.append("missing_channel")

        meta = _build_meta(
            row,
            reg_info,
            cont_info,
            phone_raw,
            phone_norm,
            phone_valid,
            email_raw,
            email_valid,
            city_raw,
            city_label,
            city_key,
            city_matched,
            canal_raw,
            canal_value,
            estado_raw,
            estado_value,
            model_match,
            row_anomalies,
        )

        if extras:
            duplicate_info = {
                "row_numbers": [row_number] + [number for number, _ in extras],
                "identical": all(extra_row == row for _, extra_row in extras),
            }
            if not duplicate_info["identical"]:
                duplicate_info["extra_payloads"] = [dict(extra_row) for _, extra_row in extras]
            meta["duplicates"] = duplicate_info
            duplicates_detail.append({"lead_id": lead_id, **duplicate_info})
            row_anomalies.append("duplicate_lead_id")

        normalized_fields = {
            "company_id": company_id,
            "point_of_sale_id": point_of_sale_id,
            "channel": canal_value,
            "status": estado_value,
            "customer_name": (row.get("nombre_cliente") or "").strip() or None,
            "phone_raw": phone_raw or None,
            "phone_normalized": phone_norm if phone_valid else None,
            "email_raw": email_raw,
            "email_normalized": normalize_email(email_raw) if email_valid else None,
            "city_raw": city_raw,
            "city_normalized": city_label,
            "model_text_raw": model_raw,
            "sku": model_match["sku"],
            "registration_at": reg_value,
            "first_contact_at": cont_value,
            "campaign": (row.get("campania") or "").strip() or None,
        }
        record_hash = loaders.sha256_of(dict(row))
        content_hash = loaders.sha256_of(normalized_fields)

        existing = session.get(Lead, lead_id)
        if existing is None:
            session.add(
                Lead(
                    lead_id=lead_id,
                    raw_payload=dict(row),
                    normalization_meta=meta,
                    record_hash=record_hash,
                    content_hash=content_hash,
                    first_seen_run=run_id,
                    last_seen_run=run_id,
                    is_current=True,
                    **normalized_fields,
                )
            )
            inserted += 1
        elif existing.record_hash == record_hash:
            existing.last_seen_run = run_id
            unchanged += 1
        else:
            for key, value in normalized_fields.items():
                setattr(existing, key, value)
            existing.raw_payload = dict(row)
            existing.normalization_meta = meta
            existing.record_hash = record_hash
            existing.content_hash = content_hash
            existing.last_seen_run = run_id
            updated += 1

    persisted = inserted + updated + unchanged

    session.flush()

    return {
        "read": len(rows),
        "persisted": persisted,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "duplicate_count": duplicate_count,
        "duplicate_ids": sorted(duplicate_ids),
        "duplicates_detail": duplicates_detail,
        "ambiguous_registration_dates": ambiguous_registration,
        "ambiguous_first_contact_dates": ambiguous_first_contact,
        "ambiguous_by_convention_dates": ambiguous_by_convention,
        "unknown_dates": unknown_dates,
        "chronology_inconsistencies": chronology_inconsistencies,
        "managed_without_first_contact": managed_without_first_contact,
        "invalid_phones": invalid_phones,
        "cities_normalized": cities_normalized,
        "cities_unmatched": cities_unmatched,
        "models_matched": models_matched,
        "models_ambiguous": models_ambiguous,
        "models_unmatched": models_unmatched,
        "models_empty": models_empty,
        "invalid_references": invalid_references,
        "anomalies_total": len(anomalies),
        "anomalies_sample": anomalies[:20],
    }
