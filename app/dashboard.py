"""Dashboard V1: vista asesor (/) + supervisión (/supervision) + detalle.

Autenticación real por sesión (app/auth.py). La identidad y el rol salen
siempre de ``current_user`` cargado desde la DB; el frontend nunca aporta
identidad. Rutas de negocio requieren login; /login y /health son públicas.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

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
from app.presentation import (
    dimension_label,
    score_reason_label,
    sender_class,
    sender_label,
)

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
    return _build_row(assignment, lead, score, catalog, owner_name)


def _build_row(assignment: Assignment, lead: Lead, score: LeadScore | None,
               catalog: CatalogItem | None,
               owner_name: str | None = None) -> dict:
    """Construye la fila de presentación desde objetos ya cargados."""
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


# --- Supervisión: batch-load + paginación (perf, sin cambio de alcance) --------

PAGE_SIZE = 50


def _parse_page(raw: str | None) -> int:
    """Página segura: inválidos, 0 y negativos → 1."""
    try:
        page = int((raw or "").strip() or "1")
    except (TypeError, ValueError):
        return 1
    return page if page >= 1 else 1


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _model_label_column():
    """Etiqueta de modelo como expresión SQL (misma regla que _model_label)."""
    catalog_label = (
        sa.func.coalesce(CatalogItem.brand, "")
        + " "
        + sa.func.coalesce(CatalogItem.line, "")
    )
    return sa.case(
        (CatalogItem.sku.is_not(None), catalog_label),
        else_=Lead.model_text_raw,
    )


def _supervision_ids_stmt(scope_companies: list[str], resolved: date,
                          pos: str | None, asesor: str | None,
                          banda: str | None, estado: str | None,
                          modelo: str | None):
    """IDs de assignments del conjunto filtrado (sin paginar).

    Los filtros de banda/estado/modelo se aplican en SQL con JOINs para no
    cargar todas las filas en memoria. El orden/paginación se aplica después.
    """
    stmt = (
        sa.select(Assignment.assignment_id)
        .where(
            Assignment.is_current.is_(True),
            Assignment.company_id.in_(scope_companies),
            Assignment.run_date == resolved,
        )
    )
    if pos:
        stmt = stmt.where(Assignment.point_of_sale_id == pos)
    if asesor:
        stmt = stmt.where(Assignment.advisor_id == asesor)
    if estado or banda or modelo:
        stmt = stmt.join(Lead, Lead.lead_id == Assignment.lead_id)
    if banda:
        stmt = stmt.join(
            LeadScore,
            (LeadScore.lead_id == Assignment.lead_id)
            & (LeadScore.is_current.is_(True)),
        ).where(LeadScore.band == banda)
    if estado:
        stmt = stmt.where(Lead.status == estado)
    if modelo:
        needle = (modelo or "").strip().lower()
        if needle:
            stmt = stmt.outerjoin(
                CatalogItem, CatalogItem.sku == Lead.sku
            ).where(
                sa.func.lower(_model_label_column()).like(
                    f"%{_escape_like(needle)}%", escape="\\"
                )
            )
    return stmt


def _supervision_order():
    return (Assignment.company_id, Assignment.point_of_sale_id,
            Assignment.priority_rank.asc())


def _batch_lead_details(session: Session, assignments: list[Assignment]
                        ) -> tuple[dict, dict, dict, dict]:
    """Carga en batch (WHERE IN) los datos de una lista de assignments.

    Retorna (leads, scores, catalogs, advisors): score = vigente de mayor
    score_id por lead (igual que _current_score); advisors por id.
    """
    lead_ids = list({a.lead_id for a in assignments})
    skus: set[str] = set()
    leads: dict[str, Lead] = {}
    if lead_ids:
        for lead in session.scalars(
            sa.select(Lead).where(Lead.lead_id.in_(lead_ids))
        ).all():
            leads[lead.lead_id] = lead
            if lead.sku:
                skus.add(lead.sku)
    scores: dict[str, LeadScore] = {}
    if lead_ids:
        for score in session.scalars(
            sa.select(LeadScore)
            .where(LeadScore.lead_id.in_(lead_ids),
                   LeadScore.is_current.is_(True))
            .order_by(LeadScore.score_id.desc())
        ).all():
            scores.setdefault(score.lead_id, score)
    catalogs: dict[str, CatalogItem] = {}
    if skus:
        for item in session.scalars(
            sa.select(CatalogItem).where(CatalogItem.sku.in_(skus))
        ).all():
            catalogs[item.sku] = item
    advisor_ids = list({a.advisor_id for a in assignments if a.advisor_id})
    advisors: dict[str, Advisor] = {}
    if advisor_ids:
        for advisor in session.scalars(
            sa.select(Advisor).where(Advisor.advisor_id.in_(advisor_ids))
        ).all():
            advisors[advisor.advisor_id] = advisor
    return leads, scores, catalogs, advisors


def _supervision_row(assignment: Assignment, leads: dict, scores: dict,
                     catalogs: dict, advisors: dict) -> dict | None:
    lead = leads.get(assignment.lead_id)
    if lead is None:
        return None
    score = scores.get(lead.lead_id)
    catalog = catalogs.get(lead.sku) if lead.sku else None
    owner = advisors.get(assignment.advisor_id) if assignment.advisor_id else None
    return _build_row(
        assignment, lead, score, catalog,
        owner.name if owner else "Sin asignar (overflow)")


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
    page: str | None = Query(default=None),
    ppage: str | None = Query(default=None),
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
    # Conjunto filtrado (scope + filtros) como subconsulta de IDs: el total,
    # la página y los agregados se calculan sobre el mismo conjunto sin traer
    # todas las filas a memoria.
    if resolved and scope_companies:
        ids_sub = _supervision_ids_stmt(
            scope_companies, resolved, pos, asesor, banda, estado, modelo
        ).subquery()
        ids_select = sa.select(ids_sub.c.assignment_id)
        total = session.scalar(
            sa.select(sa.func.count()).select_from(ids_sub)
        ) or 0
    else:
        ids_sub = None
        ids_select = None
        total = 0

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page_number = min(_parse_page(page), total_pages)
    offset = (page_number - 1) * PAGE_SIZE

    if total:
        page_assignments = session.scalars(
            sa.select(Assignment)
            .where(Assignment.assignment_id.in_(ids_select))
            .order_by(*_supervision_order())
            .limit(PAGE_SIZE)
            .offset(offset)
        ).all()
        status_counts = dict(session.execute(
            sa.select(Assignment.status, sa.func.count())
            .where(Assignment.assignment_id.in_(ids_select))
            .group_by(Assignment.status)
        ).all())
        assigned_total = status_counts.get(STATUS_ASSIGNED, 0)
        overflow_total = status_counts.get(STATUS_OVERFLOW, 0)
        # Pendientes: paginación propia e independiente de la principal. La
        # paginación de gestión (`page`) nunca controla esta sección.
        pending_pages = max(1, math.ceil(overflow_total / PAGE_SIZE))
        ppage_number = min(_parse_page(ppage), pending_pages)
        poffset = (ppage_number - 1) * PAGE_SIZE
        overflow_assignments = session.scalars(
            sa.select(Assignment)
            .where(Assignment.assignment_id.in_(ids_select),
                   Assignment.status == STATUS_OVERFLOW)
            .order_by(*_supervision_order())
            .limit(PAGE_SIZE)
            .offset(poffset)
        ).all()
        leads, scores, catalogs, advisors = _batch_lead_details(
            session, list(page_assignments) + list(overflow_assignments))
        counts_rows = session.execute(
            sa.select(LeadScore.band,
                      sa.func.count(sa.distinct(Assignment.assignment_id)))
            .select_from(Assignment)
            .join(LeadScore,
                  (LeadScore.lead_id == Assignment.lead_id)
                  & (LeadScore.is_current.is_(True)))
            .where(Assignment.assignment_id.in_(ids_select))
            .group_by(LeadScore.band)
        ).all()
        status_rows = session.execute(
            sa.select(Assignment.status, sa.func.count())
            .where(Assignment.assignment_id.in_(ids_select))
            .group_by(Assignment.status)
        ).all()
        status_options = sorted({
            (status or UNKNOWN)
            for (status,) in session.execute(
                sa.select(Lead.status.distinct())
                .select_from(Lead)
                .join(Assignment, Assignment.lead_id == Lead.lead_id)
                .where(Assignment.assignment_id.in_(ids_select))
            ).all()
        })
        option_pairs = session.execute(
            sa.select(Assignment.point_of_sale_id.distinct(),
                      Assignment.advisor_id)
            .where(
                Assignment.is_current.is_(True),
                Assignment.company_id.in_(scope_companies),
                Assignment.run_date == resolved,
            )
        ).all()
        pos_options = sorted({pos_id for pos_id, _ in option_pairs if pos_id})
        advisor_options = sorted({
            advisor_id for pos_id, advisor_id in option_pairs
            if advisor_id and (not pos or pos_id == pos)
        })
    else:
        page_assignments = []
        overflow_assignments = []
        leads = scores = catalogs = advisors = {}
        counts_rows = []
        status_options = []
        pos_options = []
        advisor_options = []
        assigned_total = 0
        overflow_total = 0
        pending_pages = 1
        ppage_number = 1

    rows = []
    for assignment in page_assignments:
        row = _supervision_row(assignment, leads, scores, catalogs, advisors)
        if row is not None:
            rows.append(row)
    counts = {"Alta": 0, "Media": 0, "Baja": 0}
    for band, count in counts_rows:
        if band in counts:
            counts[band] += count
    overflow_rows = []
    for assignment in overflow_assignments:
        row = _supervision_row(assignment, leads, scores, catalogs, advisors)
        if row is not None:
            overflow_rows.append(row)
    supervisor_options = sorted(
        email for (email,) in session.execute(
            sa.select(User.email).where(
                User.role == ROLE_SUPERVISOR,
                User.company_id.in_(scope_companies) if scope_companies else sa.false())
        ).all()
    ) if is_admin else []
    base_params = {}
    if run_date:
        base_params["run_date"] = run_date.isoformat()
    for key, value in (("empresa", empresa), ("supervisor", supervisor),
                       ("pos", pos), ("asesor", asesor), ("banda", banda),
                       ("estado", estado), ("modelo", modelo)):
        if value:
            base_params[key] = value

    def _supervision_url(target_page: int, target_ppage: int) -> str:
        return "/supervision?" + urlencode(
            {**base_params, "page": target_page, "ppage": target_ppage})

    pagination = {
        "page": page_number,
        "total_pages": total_pages,
        "total": total,
        "prev_url": _supervision_url(page_number - 1, ppage_number) if page_number > 1 else None,
        "next_url": _supervision_url(page_number + 1, ppage_number) if page_number < total_pages else None,
    }
    pending_pagination = {
        "page": ppage_number,
        "total_pages": pending_pages,
        "total": overflow_total,
        "prev_url": _supervision_url(page_number, ppage_number - 1) if ppage_number > 1 else None,
        "next_url": _supervision_url(page_number, ppage_number + 1) if ppage_number < pending_pages else None,
    }
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
            "total": total,
            "assigned_total": assigned_total,
            "overflow_total": overflow_total,
            "overflow_rows": overflow_rows,
            "pagination": pagination,
            "pending_pagination": pending_pagination,
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
            "page_size": PAGE_SIZE,
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
        messages = [m for m in (conversation.messages or []) if isinstance(m, dict)]
        ordered = sorted(
            messages,
            key=lambda m: m.get("seq") if isinstance(m.get("seq"), int) else 0,
        )
        extraction = get_current_extraction(session, conversation.conversation_id)
        conv_rows.append(
            {
                "conversation": conversation,
                "message_count": len(messages),
                "fields": dict(extraction.fields) if extraction and extraction.fields else {},
                "messages": [
                    {
                        "sender_label": sender_label(m.get("sender")),
                        "sender_class": sender_class(m.get("sender")),
                        "hour": str(m.get("hour") or ""),
                        "text": str(m.get("text") or ""),
                    }
                    for m in ordered
                ],
            }
        )
    reasons_display = [
        {
            "label": score_reason_label(reason.get("code")),
            "dimension": dimension_label(reason.get("dimension")),
            "text": reason.get("text"),
            "contribution": reason.get("contribution"),
        }
        for reason in _priority_reasons(score.reasons if score else None)
    ]
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
            "reasons": reasons_display,
            "conversations": conv_rows,
            "unknown": UNKNOWN,
            "bool_label": _bool_label,
        },
    )
