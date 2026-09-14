from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_csv_fieldnames(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_all() -> dict[str, Any]:
    return {
        "leads": read_csv(config_path("leads")),
        "catalogo": read_csv(config_path("catalogo")),
        "asesores": read_csv(config_path("asesores")),
        "historico": read_csv(config_path("historico")),
        "conversaciones": read_json(config_path("conversaciones")),
    }


def config_path(name: str) -> Path:
    from . import config

    mapping = {
        "leads": config.LEADS,
        "catalogo": config.CATALOGO,
        "asesores": config.ASESORES,
        "historico": config.HISTORICO,
        "conversaciones": config.CONVERSACIONES,
    }
    return mapping[name]
