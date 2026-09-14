"""Dashboard V1 «Mis leads de hoy» (HTML server-side con Jinja2).

Lee el pipeline existente (Assignment → Lead → LeadScore → AIExtraction) y lo
presenta como herramienta comercial. Sin React, sin APIs públicas nuevas.

Aislamiento: todo parte de asignaciones del asesor en contexto. Nunca se
consulta un lead sin antes verificar su assignment vigente. El contexto actual
es un asesor demo controlado (``DEMO_ADVISOR_ID``); la autenticación real lo
reemplazará sin cambiar las consultas (ver ``resolve_context``).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.ai.service import get_current_extraction
from app.config import get_settings
from app.db import SessionLocal
from app.models import Advisor, Assignment, CatalogItem, Conversation, Lead, LeadScore

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

UNKNOWN = "Desconocido"


def get_session():
    with SessionLocal() as session:
        yield session


def resolve_context(session: Session) -> Advisor:
    """Contexto demo: asesor controlado por configuración.

    Separado de la futura autenticación real: cuando exista login, esta
    función se reemplaza por la resolución desde la sesión/JWT y el resto
    del módulo no cambia (todas las consultas ya parten del asesor).
    """
    advisor_id = get_settings().demo_advisor_id
    advisor = session.get(Advisor, advisor_id)
    if advisor is None or not advisor.active:
        raise HTTPException(status_code=404, detail="Asesor demo no disponible")
    return advisor


def _latest_run_date(session: Session, advisor_id: str) -> date | None:
    return session.scalar(
        sa.select(sa.func.max(Assignment.run_date)).where(
            Assignment.advisor_id == advisor_id,
            Assignment.is_current.is_(True),
        )
    )


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


def _bool_label(value: bool | None) -> str:
    if value is True:
        return "Sí"
    if value is False:
        return "No"
    return UNKNOWN


def _load_rows(session: Session, advisor: Advisor, run_date: date) -> list[dict]:
    assignments = session.scalars(
        sa.select(Assignment)
        .where(
            Assignment.advisor_id == advisor.advisor_id,
            Assignment.run_date == run_date,
            Assignment.is_current.is_(True),
        )
        .order_by(Assignment.priority_rank.asc())
    ).all()
    rows = []
    for assignment in assignments:
        lead = session.get(Lead, assignment.lead_id)
        if lead is None:
            continue
        score = _current_score(session, lead.lead_id)
        catalog = session.get(CatalogItem, lead.sku) if lead.sku else None
        rows.append(
            {
                "assignment": assignment,
                "lead": lead,
                "score": score,
                "model": _model_label(lead, catalog),
                "band": (score.band if score and score.band else UNKNOWN),
                "queue": (float(score.queue_score) if score and score.queue_score is not None else None),
                "status": (lead.status or UNKNOWN),
            }
        )
    return rows


@router.get("/", response_class=HTMLResponse)
def today(
    request: Request,
    session: Session = Depends(get_session),
    run_date: date | None = Query(default=None),
    banda: str | None = Query(default=None),
    estado: str | None = Query(default=None),
    pos: str | None = Query(default=None),
    modelo: str | None = Query(default=None),
):
    settings = get_settings()
    advisor = resolve_context(session)
    resolved = run_date or _latest_run_date(session, advisor.advisor_id)
    rows = _load_rows(session, advisor, resolved) if resolved else []

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

    # Los filtros solo recortan dentro de los leads del asesor en contexto.
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


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(
    lead_id: str,
    request: Request,
    session: Session = Depends(get_session),
    run_date: date | None = Query(default=None),
):
    settings = get_settings()
    advisor = resolve_context(session)
    resolved = run_date or _latest_run_date(session, advisor.advisor_id)
    assignment = None
    if resolved:
        # El lead solo existe para este asesor si hay assignment vigente suyo.
        assignment = session.scalar(
            sa.select(Assignment).where(
                Assignment.advisor_id == advisor.advisor_id,
                Assignment.lead_id == lead_id,
                Assignment.run_date == resolved,
                Assignment.is_current.is_(True),
            )
        )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Lead no asignado a este asesor")
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
            "advisor": advisor,
            "assignment": assignment,
            "lead": lead,
            "score": score,
            "model": _model_label(lead, catalog),
            "reasons": list(score.reasons) if score and score.reasons else [],
            "conversations": conv_rows,
            "unknown": UNKNOWN,
            "bool_label": _bool_label,
        },
    )
