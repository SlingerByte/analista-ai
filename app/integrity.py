"""Integridad de la jerarquía empresa → punto de venta → asesor → asignación.

Es la defensa de aplicación (los constraints compuestos en la BD son la
defensa adicional). Los validadores son deterministas y no dependen de que
SQLite aplique FKs, de modo que el punto de escritura falla de forma
controlada incluso en desarrollo/pruebas.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import Advisor, PointOfSale


class OrgIntegrityError(ValueError):
    """Relación empresa/POS/asesor inválida."""


def point_of_sale_owners(session: Session) -> dict[str, str]:
    """Mapa ``point_of_sale_id -> company_id`` (una sola consulta)."""
    return dict(
        session.execute(
            sa.select(PointOfSale.point_of_sale_id, PointOfSale.company_id)
        ).all()
    )


def advisor_organizations(session: Session) -> dict[str, tuple[str, str]]:
    """Mapa ``advisor_id -> (company_id, point_of_sale_id)``."""
    return {
        advisor.advisor_id: (advisor.company_id, advisor.point_of_sale_id)
        for advisor in session.scalars(sa.select(Advisor)).all()
    }


def check_lead_organization(
    pos_owner: dict[str, str], *, company_id: str, point_of_sale_id: str
) -> None:
    owner = pos_owner.get(point_of_sale_id)
    if owner is None:
        raise OrgIntegrityError(
            f"punto de venta desconocido: {point_of_sale_id!r}"
        )
    if owner != company_id:
        raise OrgIntegrityError(
            f"el punto de venta {point_of_sale_id!r} pertenece a {owner!r}, "
            f"no a {company_id!r}"
        )


def check_assignment_organization(
    pos_owner: dict[str, str],
    advisor_org: dict[str, tuple[str, str]],
    *,
    company_id: str,
    point_of_sale_id: str | None,
    advisor_id: str | None,
) -> None:
    if point_of_sale_id is not None:
        check_lead_organization(
            pos_owner, company_id=company_id, point_of_sale_id=point_of_sale_id
        )
    if advisor_id is None:
        return
    org = advisor_org.get(advisor_id)
    if org is None:
        raise OrgIntegrityError(f"asesor desconocido: {advisor_id!r}")
    advisor_company, advisor_pos = org
    if advisor_company != company_id:
        raise OrgIntegrityError(
            f"el asesor {advisor_id!r} pertenece a {advisor_company!r}, "
            f"no a {company_id!r}"
        )
    if point_of_sale_id is not None and advisor_pos != point_of_sale_id:
        raise OrgIntegrityError(
            f"el asesor {advisor_id!r} pertenece al punto de venta "
            f"{advisor_pos!r}, no a {point_of_sale_id!r}"
        )


def validate_lead_organization(
    session: Session, *, company_id: str, point_of_sale_id: str
) -> None:
    check_lead_organization(
        point_of_sale_owners(session),
        company_id=company_id,
        point_of_sale_id=point_of_sale_id,
    )


def validate_assignment_organization(
    session: Session,
    *,
    company_id: str,
    point_of_sale_id: str | None,
    advisor_id: str | None,
) -> None:
    check_assignment_organization(
        point_of_sale_owners(session),
        advisor_organizations(session),
        company_id=company_id,
        point_of_sale_id=point_of_sale_id,
        advisor_id=advisor_id,
    )
