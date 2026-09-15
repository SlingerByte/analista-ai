"""Tooling de evaluaciÃ³n (NO producciÃ³n): construye el gold set estratificado.

Uso:
    uv run python scripts/build_gold_set.py --target 110

Lee `data/conversaciones.json` en modo lectura, selecciona una muestra
estratificada, anota un candidato de ground truth con `scripts/ai_gold_rules.py`
y aplica overrides humanos de `scripts/gold_overrides.json` si existen.
Escribe `reports/gold_set.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.text import normalize_key  # noqa: E402
from scripts.ai_gold_rules import CATALOG_LINES, annotate  # noqa: E402

DATA = ROOT / "data" / "conversaciones.json"
REPORTS = ROOT / "reports"
OVERRIDES = ROOT / "scripts" / "gold_overrides.json"

CONTROL_CASES = ["CONV-00058"]


def _normalize_record(raw: dict) -> dict:
    return {
        "conversation_id": raw.get("conversacion_id") or raw.get("conversation_id"),
        "lead_id": raw.get("lead_id"),
        "channel": raw.get("canal") or raw.get("channel"),
        "mensajes": raw.get("mensajes") or raw.get("messages") or [],
    }


def _client_text(conversation: dict) -> str:
    return " || ".join(
        normalize_key(m.get("texto")) for m in conversation["mensajes"] if m.get("emisor") == "cliente"
    )


def _tags(conversation: dict) -> dict:
    text = _client_text(conversation)
    models = sorted({canonical for key, canonical in CATALOG_LINES.items() if key in text})
    n = len(conversation["mensajes"])
    return {
        "initial": ("inicial" in text or "entrada" in text or "enganche" in text),
        "no_initial": ("no tengo inicial" in text or "sin inicial" in text),
        "payment_form": ("financiad" in text or "credito" in text or "contado" in text),
        "objection": any(c in text for c in
                         ["muy caro", "muy cara", "otra marca", "mas economico", "solo mirando",
                          "no me alcanza", "tasa", "descuento"]),
        "appointment": any(c in text for c in ["visit", "pasar", "cita", "agendar", "manana voy", "voy manana"]),
        "quote": ("cotiz" in text or "mandela" in text or "enviela" in text or "mandemela" in text),
        "high_intent": any(c in text for c in ["me sirve", "la quiero", "ya voy", "hagale", "la separo"]),
        "multi_model": len(models) >= 2,
        "short": n <= 4,
        "long": n >= 8,
        "informative": ("informacion" in text or "cuanto vale" in text or "precio" in text),
    }


def select(conversations: list[dict], target: int) -> list[dict]:
    by_id = {c["conversation_id"]: c for c in conversations}
    ordered = sorted(conversations, key=lambda c: c["conversation_id"])
    selected: list[dict] = []
    picked: set[str] = set()

    def take(predicate, quota: int) -> None:
        added = 0
        for conversation in ordered:
            if added >= quota:
                break
            cid = conversation["conversation_id"]
            if cid in picked:
                continue
            if predicate(conversation):
                picked.add(cid)
                selected.append(conversation)
                added += 1

    for cid in CONTROL_CASES:
        if cid in by_id and cid not in picked:
            picked.add(cid)
            selected.append(by_id[cid])

    quotas = [
        (lambda c: _tags(c)["initial"], 18),
        (lambda c: _tags(c)["no_initial"], 4),
        (lambda c: _tags(c)["payment_form"], 18),
        (lambda c: _tags(c)["objection"], 15),
        (lambda c: _tags(c)["appointment"], 15),
        (lambda c: _tags(c)["quote"], 15),
        (lambda c: _tags(c)["multi_model"], 15),
        (lambda c: _tags(c)["high_intent"], 10),
        (lambda c: _tags(c)["short"], 10),
        (lambda c: _tags(c)["long"], 10),
        (lambda c: _tags(c)["informative"], 10),
    ]
    for predicate, quota in quotas:
        take(predicate, quota)

    # Relleno determinista y uniforme hasta el objetivo.
    if len(selected) < target:
        step = max(1, len(ordered) // max(1, target - len(selected)))
        for conversation in ordered[::step]:
            if len(selected) >= target:
                break
            cid = conversation["conversation_id"]
            if cid not in picked:
                picked.add(cid)
                selected.append(conversation)

    selected.sort(key=lambda c: c["conversation_id"])
    return selected[:target] if target else selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stratified gold set")
    parser.add_argument("--target", type=int, default=110)
    args = parser.parse_args()

    conversations = json.loads(DATA.read_text(encoding="utf-8"))
    conversations = [_normalize_record(c) for c in conversations]
    selected = select(conversations, args.target)

    overrides = {}
    if OVERRIDES.exists():
        overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))

    records = []
    for conversation in selected:
        gold = annotate(conversation)
        gold["transcript"] = [
            {"emisor": m.get("emisor"), "hora": m.get("hora"), "texto": m.get("texto")}
            for m in conversation["mensajes"]
        ]
        override = overrides.get(gold["conversation_id"])
        if override:
            gold.update(override)
            gold["gold_source"] = "human"
        records.append(gold)

    reports = {
        "target": args.target,
        "selected": len(records),
        "control_cases": CONTROL_CASES,
        "records": records,
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "gold_set.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"gold set: {len(records)} conversations -> reports/gold_set.json")
    if overrides:
        print(f"human overrides applied: {len(overrides)}")


if __name__ == "__main__":
    main()

