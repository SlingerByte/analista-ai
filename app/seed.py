from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import get_settings
from app.db import SessionLocal
from app.models import Advisor, CatalogItem, Company, PointOfSale, User

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

ASESORES_CSV = "asesores.csv"
CATALOGO_CSV = "catalogo_motos.csv"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _upsert_company(session: Session, company_id: str) -> None:
    company = session.get(Company, company_id)
    if company is None:
        session.add(Company(company_id=company_id, name=company_id))
    else:
        company.name = company_id


def _upsert_point_of_sale(
    session: Session, point_of_sale_id: str, company_id: str
) -> None:
    existing = session.get(PointOfSale, point_of_sale_id)
    if existing is None:
        session.add(
            PointOfSale(
                point_of_sale_id=point_of_sale_id,
                company_id=company_id,
                name=point_of_sale_id,
            )
        )
    else:
        existing.company_id = company_id
        existing.name = point_of_sale_id


def _upsert_advisor(session: Session, row: dict[str, str]) -> None:
    advisor_id = row["asesor_id"]
    existing = session.get(Advisor, advisor_id)
    fields = {
        "company_id": row["empresa_id"],
        "point_of_sale_id": row["punto_venta_id"],
        "name": row["nombre"].strip(),
        "daily_capacity": int(row["capacidad_diaria_leads"]),
        "active": row["activo"].strip().upper() == "SI",
        "start_date": _parse_date(row["fecha_ingreso"]),
        "raw_fields": dict(row),
    }
    if existing is None:
        session.add(Advisor(advisor_id=advisor_id, **fields))
    else:
        for key, value in fields.items():
            setattr(existing, key, value)


def _upsert_catalog_item(session: Session, row: dict[str, str]) -> None:
    sku = row["sku"]
    points_of_sale = [pv for pv in row["puntos_venta_disponibles"].split("|") if pv]
    availability = {
        "points_of_sale": points_of_sale,
        "units_total": int(row["unidades_disponibles"]),
    }
    fields = {
        "brand": row["marca"].strip(),
        "line": row["linea"].strip(),
        "engine_cc": int(row["cilindraje"]),
        "segment": row["segmento"].strip(),
        "list_price": Decimal(row["precio_lista"]),
        "availability": availability,
    }
    existing = session.get(CatalogItem, sku)
    if existing is None:
        session.add(CatalogItem(sku=sku, **fields))
    else:
        for key, value in fields.items():
            setattr(existing, key, value)


def seed(session: Session, data_dir: Path = DATA_DIR) -> dict[str, int]:
    asesores = _read_csv(data_dir / ASESORES_CSV)
    catalogo = _read_csv(data_dir / CATALOGO_CSV)

    company_ids = sorted({row["empresa_id"] for row in asesores})
    for company_id in company_ids:
        _upsert_company(session, company_id)
    session.flush()

    point_of_sale_company = {
        row["punto_venta_id"]: row["empresa_id"] for row in asesores
    }
    for point_of_sale_id in sorted(point_of_sale_company):
        _upsert_point_of_sale(
            session, point_of_sale_id, point_of_sale_company[point_of_sale_id]
        )
    session.flush()

    for row in asesores:
        _upsert_advisor(session, row)

    for row in catalogo:
        _upsert_catalog_item(session, row)

    _seed_demo_users(session)

    session.commit()

    return {
        "companies": session.scalar(sa.select(sa.func.count()).select_from(Company)),
        "points_of_sale": session.scalar(
            sa.select(sa.func.count()).select_from(PointOfSale)
        ),
        "advisors": session.scalar(sa.select(sa.func.count()).select_from(Advisor)),
        "catalog_items": session.scalar(
            sa.select(sa.func.count()).select_from(CatalogItem)
        ),
        "users": session.scalar(sa.select(sa.func.count()).select_from(User)),
    }


def _upsert_demo_user(
    session: Session,
    email: str,
    password: str,
    role: str,
    company_id: str | None,
    advisor_id: str | None,
) -> None:
    existing = session.scalar(sa.select(User).where(User.email == email))
    password_hash = hash_password(password)
    if existing is None:
        session.add(
            User(
                company_id=company_id,
                advisor_id=advisor_id,
                email=email,
                password_hash=password_hash,
                role=role,
            )
        )
    else:
        existing.company_id = company_id
        existing.advisor_id = advisor_id
        existing.password_hash = password_hash
        existing.role = role


def _seed_demo_users(session: Session) -> None:
    """Usuarios demo idempotentes (solo desarrollo; credenciales por entorno)."""
    settings = get_settings()
    advisor = session.get(Advisor, settings.advisor_demo_advisor_id)
    if advisor is not None:
        _upsert_demo_user(
            session,
            settings.advisor_demo_email.strip().lower(),
            settings.advisor_demo_password,
            "asesor",
            advisor.company_id,
            advisor.advisor_id,
        )
    supervisor_company = session.scalar(
        sa.select(Company.company_id).order_by(Company.company_id).limit(1)
    )
    if supervisor_company is not None:
        _upsert_demo_user(
            session,
            settings.supervisor_demo_email.strip().lower(),
            settings.supervisor_demo_password,
            "supervisor",
            supervisor_company,
            None,
        )
    _upsert_demo_user(
        session,
        settings.admin_demo_email.strip().lower(),
        settings.admin_demo_password,
        "admin",
        None,
        None,
    )


def main() -> None:
    with SessionLocal() as session:
        counts = seed(session)
    for name, count in counts.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
