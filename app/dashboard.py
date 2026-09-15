"""Dashboard V1: vista asesor (/) + supervisión (/supervision) + detalle.

Autenticación real por sesión (app/auth.py). La identidad y el rol salen
siempre de ``current_user`` cargado desde la DB; el frontend nunca aporta
identidad. Rutas de negocio requieren login; /login y /health son públicas.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.ai.service import get_current_extraction
from app.assignment.service import STATUS_ASSIGNED, STATUS_OVERFLOW, retry_assignment
from app.auth import ROLE_ADVISOR, ROLE_ADMIN, ROLE_SUPERVISOR, require_login
from app.config import get_settings
from app.db import get_session
from app.models import Advisor, Assignment, CatalogItem, Company, Conversation, Lead, LeadScore, User

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

UNKNOWN = "Desconocido"

# Dimensiones que sí explican la prioridad (comercial + urgencia). `quality`
# es una dimensión separada que no entra a `queue` y no debe mostrarse como
# si sumara a la prioridad.
PRIORITY_DIMENSIONS = ("commercial", "urgency")


def _priority_reasons(reasons) -> list:
    return [r for r in (reasons or []) if r.get("dimension") in PRIORITY_DIMENSIONS]


def _latest_run_date(session: Session, advisor_id: str) -> date | None:
    return session.scalar(
        sa.select(sa.func.max(Assignment.run_date)).where(
            Assignment.advisor_id == advisor_id,
            Assignment.is_current.is_(True),
        )
    )


def _load_rows(session: Session, advisor: Advisor, run_date: date) -> list[dict]:
    """Filas del asesor para una fecha (ordenadas por priority_rank)."""
    assignments = session.scalars(
        sa.select(Assignment)
        .where(
            Assignment.advisor_id == advisor.advisor_id,
            Assignment.run_date == run_date,
            Assignment.is_current.is_(True),
        )
        .order_by(Assignment.priority_rank.asc())
    ).all()
    return [row for row in (_row_for_assignment(session, a) for a in assignments)
            if row is not None]


def _current_score(session: Session, lead_id: str) -> LeadScore | None:
    return session.scalar(
        sa.select(LeadScore)
        .where(LeadScore.lead_id == lead_id, LeadScore.is_current.is_(True))
        .order_by(LeadScore.score_id.desc())
    )


def _model_label(lead: Lead, catalog: CatalogItem | None) -> str:
    if catalog is not None:
        return f"{catalog.brand} {catalog.line}".strip()
    return (lead.model_text_raw or "").strip() or UNKNOWN


def _city_label(lead: Lead) -> str:
    """Ciudad canónica cuando hay resolución confiable; si no, el original."""
    return lead.city_normalized or lead.city_raw or UNKNOWN


def _bool_label(value: bool | None) -> str:
    if value is True:
        return "Sí"
    if value is False:
        return "No"
    return UNKNOWN


def _row_for_assignment(session: Session, assignment: Assignment,
                        owner_name: str | None = None) -> dict | None:
    lead = session.get(Lead, assignment.lead_id)
    if lead is None:
        return None
    score = _current_score(session, lead.lead_id)
    catalog = session.get(CatalogItem, lead.sku) if lead.sku else None
    return {
        "assignment": assignment,
        "lead": lead,
        "score": score,
        "model": _model_label(lead, catalog),
        "city": _city_label(lead),
        "band": (score.band if score and score.band else UNKNOWN),
        "queue": (float(score.queue_score)
                  if score and score.queue_score is not None else None),
        "status": (lead.status or UNKNOWN),
        "owner_name": owner_name,
    }


@router.get("/", response_class=HTMLResponse)
def today(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    run_date: date | None = Query(default=None),
    banda: str | None = Query(default=None),
    estado: str | None = Query(default=None),
    pos: str | None = Query(default=None),
    modelo: str | None = Query(default=None),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    if user.role != ROLE_ADVISOR:
        return RedirectResponse(url="/supervision", status_code=303)
    advisor = session.get(Advisor, user.advisor_id) if user.advisor_id else None
    if advisor is None or not advisor.active or advisor.company_id != user.company_id:
        raise HTTPException(status_code=403, detail="Cuenta de asesor no válida")
    resolved = run_date or _latest_run_date(session, advisor.advisor_id)
    assignments = session.scalars(
        sa.select(Assignment)
        .where(
            Assignment.advisor_id == advisor.advisor_id,
            Assignment.company_id == user.company_id,
            Assignment.run_date == resolved if resolved else sa.true(),
            Assignment.is_current.is_(True),
        )
        .order_by(Assignment.priority_rank.asc())
    ).all() if resolved else []
    rows = [row for row in (_row_for_assignment(session, a) for a in assignments)
            if row is not None]

    def _match(row: dict) -> bool:
        if banda and row["band"] != banda:
            return False
        if estado and row["status"] != estado:
            return False
        if pos and row["lead"].point_of_sale_id != pos:
            return False
        if modelo and modelo.strip().lower() not in row["model"].lower():
            return False
        return True

    # Los filtros solo recortan dentro de los leads del asesor autenticado.
    filtered = [row for row in rows if _match(row)]
    counts = {"Alta": 0, "Media": 0, "Baja": 0}
    for row in rows:
        if row["band"] in counts:
            counts[row["band"]] += 1
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "advisor": advisor,
            "run_date": resolved.isoformat() if resolved else None,
            "rows": filtered,
            "total": len(rows),
            "counts": counts,
            "filters": {
                "banda": banda or "",
                "estado": estado or "",
                "pos": pos or "",
                "modelo": modelo or "",
            },
            "band_options": ["Alta", "Media", "Baja"],
            "status_options": sorted({row["status"] for row in rows}),
            "pos_options": sorted({row["lead"].point_of_sale_id for row in rows}),
        },
    )


@router.get("/supervision", response_class=HTMLResponse)
def supervision(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    run_date: date | None = Query(default=None),
    empresa: str | None = Query(default=None),
    supervisor: str | None = Query(default=None),
    pos: str | None = Query(default=None),
    asesor: str | None = Query(default=None),
    banda: str | None = Query(default=None),
    estado: str | None = Query(default=None),
    modelo: str | None = Query(default=None),
    retry: str | None = Query(default=None),
    retry_assigned: int | None = Query(default=None),
    retry_overflow: int | None = Query(default=None),
    retry_reused: int | None = Query(default=None),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    if user.role not in (ROLE_SUPERVISOR, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="La supervisión requiere rol supervisor")
    is_admin = user.role == ROLE_ADMIN

    companies = sorted(
        session.scalars(sa.select(Company.company_id).order_by(Company.company_id)).all()
    )
    if is_admin:
        # Ámbito global; la empresa se valida contra compañías reales.
        # Valor desconocido → vacío (whitelist, nunca fallback amplio).
        if not empresa:
            scope_companies = list(companies)
        elif empresa in companies:
            scope_companies = [empresa]
        else:
            scope_companies = []
        if supervisor:
            sup = session.scalar(
                sa.select(User).where(User.email == supervisor,
                                      User.role == ROLE_SUPERVISOR))
            if sup is None or sup.company_id is None:
                scope_companies = []
            else:
                scope_companies = [sup.company_id]
    else:
        # Supervisor: su empresa, sin filtro de empresa.
        scope_companies = [user.company_id]

    resolved = run_date or session.scalar(
        sa.select(sa.func.max(Assignment.run_date)).where(
            Assignment.is_current.is_(True),
            Assignment.company_id.in_(scope_companies) if scope_companies else sa.false())
    )
    assignments = session.scalars(
        sa.select(Assignment)
        .where(
            Assignment.is_current.is_(True),
            Assignment.company_id.in_(scope_companies) if scope_companies else sa.false(),
            Assignment.run_date == resolved if resolved else sa.true(),
        )
        .order_by(Assignment.company_id, Assignment.point_of_sale_id,
                  Assignment.priority_rank.asc())
    ).all() if resolved and scope_companies else []

    advisors = {a.advisor_id: a for a in session.scalars(sa.select(Advisor)).all()}
    rows = []
    for assignment in assignments:
        if pos and assignment.point_of_sale_id != pos:
            continue
        if asesor and assignment.advisor_id != asesor:
            continue
        owner = advisors.get(assignment.advisor_id) if assignment.advisor_id else None
        row = _row_for_assignment(
            session, assignment, owner.name if owner else "Sin asignar (overflow)")
        if row is None:
            continue
        if banda and row["band"] != banda:
            continue
        if estado and row["status"] != estado:
            continue
        if modelo and modelo.strip().lower() not in row["model"].lower():
            continue
        rows.append(row)
    counts = {"Alta": 0, "Media": 0, "Baja": 0}
    for row in rows:
        if row["band"] in counts:
            counts[row["band"]] += 1
    assigned_total = sum(
        1 for row in rows if row["assignment"].status == STATUS_ASSIGNED
    )
    overflow_rows = [
        row for row in rows if row["assignment"].status == STATUS_OVERFLOW
    ]
    pos_options = sorted({a.point_of_sale_id for a in assignments})
    advisor_options = sorted({a.advisor_id for a in assignments if a.advisor_id
                              and (not pos or a.point_of_sale_id == pos)})
    supervisor_options = sorted(
        email for (email,) in session.execute(
            sa.select(User.email).where(
                User.role == ROLE_SUPERVISOR,
                User.company_id.in_(scope_companies) if scope_companies else sa.false())
        ).all()
    ) if is_admin else []
    status_options = sorted({row["status"] for row in rows})
    return templates.TemplateResponse(
        request=request,
        name="supervision.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "is_admin": is_admin,
            "title": "Supervisión global" if is_admin else "Supervisión",
            "company_label": None if is_admin else (scope_companies[0] if scope_companies else None),
            "run_date": resolved.isoformat() if resolved else None,
            "rows": rows,
            "total": len(rows),
            "assigned_total": assigned_total,
            "overflow_total": len(overflow_rows),
            "overflow_rows": overflow_rows,
            "retry": {
                "ran": retry is not None,
                "assigned": retry_assigned,
                "overflow": retry_overflow,
                "reused": bool(retry_reused),
            },
            "counts": counts,
            "filters": {"empresa": empresa or "", "supervisor": supervisor or "",
                        "pos": pos or "", "asesor": asesor or "",
                        "banda": banda or "", "estado": estado or "",
                        "modelo": modelo or ""},
            "company_options": companies if is_admin else [],
            "supervisor_options": supervisor_options,
            "pos_options": pos_options,
            "advisor_options": advisor_options,
            "band_options": ["Alta", "Media", "Baja"],
            "status_options": status_options,
        },
    )


@router.post("/supervision/retry-assignment")
def retry_assignment_action(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    empresa: str | None = Form(default=None),
):
    """Reintenta la asignación determinista sobre los pendientes (scoped)."""
    if isinstance(user, RedirectResponse):
        return user
    if user.role not in (ROLE_SUPERVISOR, ROLE_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Solo supervisor o admin pueden reintentar la asignación",
        )

    is_admin = user.role == ROLE_ADMIN
    if is_admin:
        if empresa:
            exists = session.scalar(
                sa.select(Company.company_id).where(Company.company_id == empresa)
            )
            scope: set[str] | None = {empresa} if exists else set()
        else:
            scope = None
    else:
        scope = {user.company_id} if user.company_id else set()

    if scope is not None and not scope:
        # Empresa filtrada inexistente: nada que reintentar.
        return RedirectResponse(url="/supervision", status_code=303)

    resolved = session.scalar(
        sa.select(sa.func.max(Assignment.run_date)).where(
            Assignment.is_current.is_(True),
            Assignment.company_id.in_(scope) if scope else sa.true(),
        )
    ) or date.today()

    report = retry_assignment(session, resolved, company_ids=scope)
    return RedirectResponse(
        url=(
            "/supervision?retry=1"
            f"&retry_assigned={report['assigned']}"
            f"&retry_overflow={report['overflow']}"
            f"&retry_reused={1 if report['reused'] else 0}"
        ),
        status_code=303,
    )


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(
    lead_id: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    run_date: date | None = Query(default=None),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    if user.role == ROLE_ADVISOR:
        advisor = session.get(Advisor, user.advisor_id) if user.advisor_id else None
        if advisor is None or advisor.company_id != user.company_id:
            raise HTTPException(status_code=403, detail="Cuenta de asesor no válida")
        resolved = run_date or _latest_run_date(session, advisor.advisor_id)
        assignment = None
        if resolved:
            # El lead solo existe para este asesor si hay assignment vigente suyo.
            assignment = session.scalar(
                sa.select(Assignment).where(
                    Assignment.advisor_id == advisor.advisor_id,
                    Assignment.company_id == user.company_id,
                    Assignment.lead_id == lead_id,
                    Assignment.run_date == resolved,
                    Assignment.is_current.is_(True),
                )
            )
        if assignment is None:
            raise HTTPException(status_code=404, detail="Lead no asignado a este asesor")
        owner_name, back_url, back_label = (
            advisor.name, "/", "Volver a Mis leads de hoy")
    else:
        # Supervisor: su empresa. Admin: global. Nunca por parámetro.
        company_filter = (
            sa.true() if user.role == ROLE_ADMIN
            else Assignment.company_id == user.company_id
        )
        assignment = session.scalar(
            sa.select(Assignment)
            .where(Assignment.lead_id == lead_id,
                   company_filter,
                   Assignment.is_current.is_(True))
            .order_by(Assignment.run_date.desc(), Assignment.assignment_id.desc())
        )
        if assignment is None:
            raise HTTPException(status_code=404, detail="Lead sin asignación vigente")
        owner = session.get(Advisor, assignment.advisor_id) if assignment.advisor_id else None
        advisor, owner_name = owner, (owner.name if owner else "Sin asignar (overflow)")
        back_url, back_label = "/supervision", "Volver a Supervisión comercial"
    lead = session.get(Lead, lead_id)
    score = _current_score(session, lead_id)
    catalog = session.get(CatalogItem, lead.sku) if lead.sku else None
    conversations = session.scalars(
        sa.select(Conversation)
        .where(Conversation.lead_id == lead_id)
        .order_by(Conversation.conversation_id)
    ).all()
    conv_rows = []
    for conversation in conversations:
        messages = conversation.messages or []
        extraction = get_current_extraction(session, conversation.conversation_id)
        conv_rows.append(
            {
                "conversation": conversation,
                "message_count": len(messages),
                "fields": dict(extraction.fields) if extraction and extraction.fields else {},
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="lead_detail.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "advisor": advisor,
            "advisor_name": owner_name,
            "back_url": back_url,
            "back_label": back_label,
            "assignment": assignment,
            "lead": lead,
            "score": score,
            "model": _model_label(lead, catalog),
            "city": _city_label(lead),
            "reasons": _priority_reasons(score.reasons if score else None),
            "conversations": conv_rows,
            "unknown": UNKNOWN,
            "bool_label": _bool_label,
        },
    )
