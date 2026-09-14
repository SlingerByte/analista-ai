from __future__ import annotations

import difflib
from collections import defaultdict
from typing import Iterable

from app.ingestion.normalizers import normalize_model_text

FUZZY_THRESHOLD = 0.90


def build_catalog_index(rows: Iterable[tuple[str, str, str]]) -> dict:
    mapping: dict[str, list[str]] = defaultdict(list)
    brand_skus: dict[str, set[str]] = defaultdict(set)
    brands: set[str] = set()

    for sku, brand, line in rows:
        full = normalize_model_text(f"{brand} {line}")
        line_key = normalize_model_text(line)
        brand_key = normalize_model_text(brand)
        for key in {full, line_key, f"{brand_key} {line_key}"}:
            if key and sku not in mapping[key]:
                mapping[key].append(sku)
        brand_skus[brand_key].add(sku)
        brands.add(brand_key)

    return {
        "mapping": {key: sorted(value) for key, value in mapping.items()},
        "brand_skus": {key: sorted(value) for key, value in brand_skus.items()},
        "brands": brands,
    }


def _result(raw, state, sku, match_type, method, score=None, candidates=None):
    return {
        "raw": raw,
        "state": state,
        "sku": sku,
        "match_type": match_type,
        "method": method,
        "score": score,
        "candidates": candidates or [],
    }


def match_model(raw: str | None, index: dict) -> dict:
    text = (raw or "").strip()
    if not text:
        return _result(raw, "empty", None, "vacio", "none")

    canonical = normalize_model_text(text)
    mapping = index["mapping"]

    skus = sorted(set(mapping.get(canonical, [])))
    if skus:
        if len(skus) == 1:
            return _result(raw, "matched", skus[0], "directo_unico", "catalog_direct")
        return _result(raw, "ambiguous", None, "directo_ambiguo", "catalog_direct", candidates=skus)

    if canonical in index["brands"]:
        return _result(
            raw,
            "ambiguous",
            None,
            "solo_marca",
            "catalog_brand",
            candidates=index["brand_skus"].get(canonical, []),
        )

    prefix_skus = sorted(
        {
            sku
            for key, values in mapping.items()
            if key.startswith(canonical) or canonical.startswith(key)
            for sku in values
        }
    )
    if len(prefix_skus) == 1:
        return _result(raw, "matched", prefix_skus[0], "prefijo_unico", "catalog_prefix")
    if len(prefix_skus) > 1:
        return _result(
            raw, "ambiguous", None, "prefijo_ambiguo", "catalog_prefix", candidates=prefix_skus
        )

    best_score = 0.0
    best_skus: set[str] = set()
    for key, values in mapping.items():
        score = difflib.SequenceMatcher(None, canonical, key).ratio()
        if score > best_score:
            best_score = score
            best_skus = set(values)
        elif score == best_score:
            best_skus.update(values)

    if best_score >= FUZZY_THRESHOLD and len(best_skus) == 1:
        return _result(
            raw,
            "matched",
            next(iter(best_skus)),
            "fuzzy",
            "catalog_fuzzy",
            score=round(best_score, 4),
        )

    return _result(raw, "unmatched", None, "sin_match", "catalog_fuzzy", score=round(best_score, 4))
