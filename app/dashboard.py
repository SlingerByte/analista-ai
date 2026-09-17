"""Dashboard V1: vista asesor (/) + supervisión (/supervision) + detalle.

Autenticación real por sesión (app/auth.py). La identidad y el rol salen
siempre de ``current_user`` cargado desde la DB; el frontend nunca aporta
identidad. Rutas de negocio requieren login; /login y /health son públicas.
"""

from __future__ import annotations

import math
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlencode

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.browser import BrowserOllamaReplay, parse_browser_result
from app.ai.factory import PRODUCTION_PROVIDERS, build_extractor
from app.ai.prompt import EXTRACTION_PROMPT_VERSION, build_messages
from app.ai.schema import SCHEMA_VERSION, ExtractionResult
from app.ai.service import (
    STATUS_SUCCESS,
    conversation_to_input,
    get_current_extraction,
    process_conversation,
    process_pending,
)
from app.assignment.service import STATUS_ASSIGNED, STATUS_OVERFLOW, retry_assignment
from app.auth import ROLE_ADVISOR, ROLE_ADMIN, ROLE_SUPERVISOR, require_login
from app.config import get_settings, is_production
from app.db import get_session
from app.ingestion.catalog import build_catalog_index, match_model
from app.lead_status import (
    CLOSE_REASONS,
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    LeadTransitionError,
    is_lead_terminal,
    update_lead_status,
)
from app.models import (
    Advisor,
    AIExtraction,
    Assignment,
    CatalogItem,
    Company,
    Conversation,
    Lead,
    LeadScore,
    User,
)
from app.presentation import (
    dimension_label,
    score_reason_label,
    sender_class,
    sender_label,
)
from app.scoring.service import score_and_persist_lead

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

# Análisis IA desde la web: límites permitidos y tope duro server-side.
AI_LIMIT_OPTIONS = (1, 10, 20)
MAX_AI_LIMIT = 20


def _configured_ai_providers(settings) -> list[dict]:
    """Proveedores seleccionables. El remoto solo si está configurado.

    En producción (APP_ENV=production) solo se ofrecen proveedores remotos: el
    proveedor local (Ollama/agente en loopback) no es accesible desde el
    contenedor ni está permitido en producción (ver app/ai/factory.py).
    """
    providers: list[dict] = []
    if not is_production(settings):
        providers.append({"value": "local", "label": "IA local (agente + Ollama)"})
    if settings.groq_api_key and settings.groq_model:
        providers.append({"value": "groq", "label": "Groq (remoto)"})
    if settings.openrouter_api_key and settings.openrouter_model:
        providers.append({"value": "openrouter", "label": "OpenRouter (remoto)"})
    return providers


def _humanize_ai_error(text: str) -> str:
    """Traduce un error técnico a un mensaje de negocio, sin filtrar detalles."""
    token = (text or "").lower()
    if "429" in token or ("rate" in token and "limit" in token) or "too many requests" in token:
        return ("El proveedor de IA está temporalmente limitado. Intenta nuevamente "
                "en unos minutos o selecciona otro proveedor.")
    if ("401" in token or "403" in token or "unauthorized" in token
            or "forbidden" in token):
        return "El proveedor de IA no está correctamente configurado."
    if "timeout" in token or "timed out" in token:
        return "El proveedor de IA tardó demasiado en responder."
    if ("network" in token or "urlerror" in token or "connection" in token
            or "unreachable" in token or "failed to fetch" in token
            or "refused" in token):
        return "No fue posible conectar con el proveedor de IA."
    if ("schema" in token or "invalid json" in token or "no choices" in token
            or "could not parse" in token or "validation" in token):
        return "El proveedor de IA no pudo procesar esta conversación."
    return "No fue posible completar el análisis."


def _safe_error_summary(items) -> str:
    """Motivo humano y seguro para la UI.

    Nunca expone el JSON del proveedor, URLs internas, claves, tokens ni stack
    traces; el detalle técnico completo permanece en BD/logs.
    """
    for item in items or []:
        value = item.get("error") if isinstance(item, dict) else item
        text = str(value or "").strip()
        if text:
            return _humanize_ai_error(text)
    return ""


def _validate_ai_limit(raw: str | None) -> int | None:
    """Límite server-side: entero >= 1, acotado a MAX_AI_LIMIT. None si inválido."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value < 1:
        return None
    return min(value, MAX_AI_LIMIT)


def _parse_ai_ids(raw: str | None) -> list[str]:
    """Ids de conversaciones de la última ejecución (acotado a MAX_AI_LIMIT)."""
    if not raw:
        return []
    seen: list[str] = []
    for token in raw.split(","):
        value = token.strip()
        if value and value not in seen:
            seen.append(value)
    return seen[:MAX_AI_LIMIT]


# --- Conversaciones analizadas (auditoría de extracciones vigentes) ------------

# Una conversación está "analizada" si su AIExtraction es is_current=True y
# status="success". No hay estado/tabla nuevos. Filtros por campos JSON con
# `as_string()` (portable: PostgreSQL JSONB ->> y SQLite json_extract).
AI_INTENT_FILTERS = (
    ("", "Todas"),
    ("alta", "Alta"),
    ("media", "Media"),
    ("baja", "Baja"),
    ("informativa", "Informativa"),
    ("none", "No determinada"),
)
AI_SIGNAL_FILTERS = (
    ("", "Todas"),
    ("cita", "Cita"),
    ("cotizacion", "Cotización"),
    ("presupuesto", "Presupuesto"),
    ("cuota_inicial", "Cuota inicial"),
    ("forma_pago", "Forma de pago"),
    ("objecion", "Objeción"),
)
AI_STATE_FILTERS = (
    ("", "Todas"),
    ("any", "Tiene alguna señal"),
    ("none", "Sin señales determinadas"),
    ("undetermined", "Tiene campos no determinados"),
)
AI_ORDER_OPTIONS = (
    ("analyzed_desc", "Más recientemente analizadas"),
    ("analyzed_asc", "Más antiguamente analizadas"),
    ("conversation_desc", "Conversación más reciente"),
    ("conversation_asc", "Conversación más antigua"),
)
_SIGNAL_FIELDS = ("solicitud_cita", "solicitud_cotizacion", "presupuesto",
                  "cuota_inicial", "forma_pago", "objecion")


def _ai_field_text(name: str):
    return AIExtraction.fields[name].as_string()


def _ai_bool_true(name: str):
    # Cast a texto: `as_string()` da texto en PostgreSQL (->> ) y nativo en
    # SQLite (json_extract); el cast unifica "true"/"1" en ambos dialectos.
    return sa.cast(_ai_field_text(name), sa.String).in_(("true", "1"))


def _ai_not_null(name: str):
    return _ai_field_text(name).is_not(None)


def _ai_is_null(name: str):
    return _ai_field_text(name).is_(None)


def _ai_signal_condition(signal: str):
    if signal == "cita":
        return _ai_bool_true("solicitud_cita")
    if signal == "cotizacion":
        return _ai_bool_true("solicitud_cotizacion")
    if signal in ("presupuesto", "cuota_inicial", "forma_pago", "objecion"):
        return _ai_not_null(signal)
    return None


def _ai_bool_not_true(name: str):
    # "No verdadero" con lógica de 3 valores: null o false (nunca NULL).
    return sa.or_(
        _ai_is_null(name),
        sa.cast(_ai_field_text(name), sa.String).in_(("false", "0")),
    )


def _ai_state_condition(state: str):
    if state == "any":
        return sa.or_(
            _ai_bool_true("solicitud_cita"),
            _ai_bool_true("solicitud_cotizacion"),
            _ai_not_null("presupuesto"),
            _ai_not_null("cuota_inicial"),
            _ai_not_null("forma_pago"),
            _ai_not_null("objecion"),
        )
    if state == "none":
        # Expresado en positivo para que los JSON null/missing no propaguen NULL.
        return sa.and_(
            _ai_bool_not_true("solicitud_cita"),
            _ai_bool_not_true("solicitud_cotizacion"),
            _ai_is_null("presupuesto"),
            _ai_is_null("cuota_inicial"),
            _ai_is_null("forma_pago"),
            _ai_is_null("objecion"),
        )
    if state == "undetermined":
        return sa.or_(*[_ai_is_null(field) for field in _SIGNAL_FIELDS])
    return None


def _analyzed_order(order: str):
    """Orden determinista; por defecto, análisis más reciente primero."""
    if order == "analyzed_asc":
        return (AIExtraction.created_at.asc(), Conversation.conversation_id.asc())
    if order == "conversation_desc":
        return (Conversation.started_at.desc(), Conversation.conversation_id.asc())
    if order == "conversation_asc":
        return (Conversation.started_at.asc(), Conversation.conversation_id.asc())
    return (AIExtraction.created_at.desc(), Conversation.conversation_id.asc())


def _analyzed_conversations_stmt(user: User, search: str | None,
                                 intent: str | None, signal: str | None,
                                 state: str | None):
    """Consulta base de conversaciones analizadas, acotada al scope del rol."""
    # Banda del lead (score vigente) y si tiene asignación vigente, en subconsultas
    # escalares para no multiplicar filas por joins.
    band_sq = (
        sa.select(LeadScore.band)
        .where(LeadScore.lead_id == Conversation.lead_id,
               LeadScore.is_current.is_(True))
        .order_by(LeadScore.score_id.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    assign_sq = (
        sa.select(sa.func.count(Assignment.assignment_id))
        .where(Assignment.lead_id == Conversation.lead_id,
               Assignment.is_current.is_(True))
        .correlate(Conversation)
        .scalar_subquery()
    )
    stmt = (
        sa.select(Conversation, AIExtraction, Lead,
                  band_sq.label("lead_band"), assign_sq.label("assign_count"))
        .join(
            AIExtraction,
            (AIExtraction.conversation_id == Conversation.conversation_id)
            & (AIExtraction.is_current.is_(True))
            & (AIExtraction.status == "success"),
        )
        .outerjoin(Lead, Lead.lead_id == Conversation.lead_id)
    )
    if user.role == ROLE_ADVISOR:
        # Solo leads con asignación vigente del propio asesor.
        assigned = sa.select(Assignment.lead_id).where(
            Assignment.advisor_id == user.advisor_id,
            Assignment.company_id == user.company_id,
            Assignment.is_current.is_(True),
        )
        stmt = stmt.where(Conversation.lead_id.in_(assigned))
    elif user.role != ROLE_ADMIN:
        stmt = stmt.where(Conversation.company_id == user.company_id)
    if search and search.strip():
        needle = f"%{search.strip()}%"
        stmt = stmt.where(sa.or_(
            Conversation.conversation_id.ilike(needle),
            Conversation.lead_id.ilike(needle),
            Lead.customer_name.ilike(needle),
        ))
    if intent == "none":
        stmt = stmt.where(_ai_is_null("intencion_compra"))
    elif intent in ("alta", "media", "baja", "informativa"):
        stmt = stmt.where(_ai_field_text("intencion_compra") == intent)
    if signal:
        condition = _ai_signal_condition(signal)
        if condition is not None:
            stmt = stmt.where(condition)
    if state:
        condition = _ai_state_condition(state)
        if condition is not None:
            stmt = stmt.where(condition)
    return stmt


def _conversation_in_scope(session: Session, user: User,
                           conversation: Conversation) -> bool:
    if user.role == ROLE_ADMIN:
        return True
    if user.role == ROLE_SUPERVISOR:
        return conversation.company_id == user.company_id
    if user.role == ROLE_ADVISOR:
        if not conversation.lead_id:
            return False
        return session.scalar(
            sa.select(Assignment.assignment_id).where(
                Assignment.advisor_id == user.advisor_id,
                Assignment.company_id == user.company_id,
                Assignment.lead_id == conversation.lead_id,
                Assignment.is_current.is_(True),
            ).limit(1)
        ) is not None
    return False


def _ai_conversation_row(conversation: Conversation, lead: Lead | None,
                         extraction: AIExtraction, lead_band: str | None = None,
                         assign_count: int = 0) -> dict:
    fields = extraction.fields if isinstance(extraction.fields, dict) else {}
    return {
        "conversation_id": conversation.conversation_id,
        "customer_name": lead.customer_name if lead else None,
        "lead_id": conversation.lead_id,
        "company_id": conversation.company_id,
        "analyzed_at": extraction.created_at,
        "prompt_version": extraction.prompt_version,
        "schema_version": extraction.schema_version,
        "lead_band": lead_band,
        "assigned": bool(assign_count),
        "model": fields.get("model_interes"),
        "intent": fields.get("intencion_compra"),
        "cita": fields.get("solicitud_cita"),
        "cotizacion": fields.get("solicitud_cotizacion"),
        "presupuesto": fields.get("presupuesto"),
        "cuota_inicial": fields.get("cuota_inicial"),
        "forma_pago": fields.get("forma_pago"),
        "objecion": fields.get("objecion"),
    }


def _ai_pending_conversation_ids(session: Session,
                                 scope_companies: list[str]) -> list[str]:
    """Conversaciones del alcance SIN extracción IA vigente (cualquier estado).

    Se excluyen también las filas `error` vigentes: volver a extraer el mismo
    input sin `force` choca con la constraint única (conversation_id,
    input_hash), así que no cuentan como "pendientes de analizar".
    """
    if not scope_companies:
        return []
    stmt = (
        sa.select(Conversation.conversation_id)
        .outerjoin(
            AIExtraction,
            (AIExtraction.conversation_id == Conversation.conversation_id)
            & (AIExtraction.is_current.is_(True)),
        )
        .where(
            Conversation.company_id.in_(scope_companies),
            AIExtraction.extraction_id.is_(None),
        )
        .order_by(Conversation.conversation_id)
    )
    return list(session.scalars(stmt).all())


class SupervisionScope:
    """Ámbito de supervisión ya resuelto (misma regla en ambas bandejas)."""

    def __init__(self, companies: list[str], company_ids: list[str]) -> None:
        self.companies = companies
        self.company_ids = company_ids


def _supervision_scope(session: Session, user: User, is_admin: bool,
                       empresa: str | None, supervisor: str | None
                       ) -> SupervisionScope:
    """Resuelve el alcance por rol. Sin fallback amplio ante valores inválidos."""
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
    return SupervisionScope(companies, scope_companies)


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
                          modelo: str | None, status: str | None = None):
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
    if status:
        stmt = stmt.where(Assignment.status == status)
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
    ai: str | None = Query(default=None),
    ai_provider: str | None = Query(default=None),
    ai_model: str | None = Query(default=None),
    ai_limit: int | None = Query(default=None),
    ai_candidates: int | None = Query(default=None),
    ai_processed: int | None = Query(default=None),
    ai_reused: int | None = Query(default=None),
    ai_errors: int | None = Query(default=None),
    ai_success: int | None = Query(default=None),
    ai_failed: int | None = Query(default=None),
    ai_failure_reason: str | None = Query(default=None),
    ai_seconds: float | None = Query(default=None),
    ai_empty: int | None = Query(default=None),
    ai_unavailable: int | None = Query(default=None),
    ai_reason: str | None = Query(default=None),
    ai_rescored: int | None = Query(default=None),
    ai_rescore_errors: int | None = Query(default=None),
    ai_ids: str | None = Query(default=None),
):
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    if user.role not in (ROLE_SUPERVISOR, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="La supervisión requiere rol supervisor")
    is_admin = user.role == ROLE_ADMIN

    scope = _supervision_scope(session, user, is_admin, empresa, supervisor)
    companies = scope.companies
    scope_companies = scope.company_ids

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
        leads, scores, catalogs, advisors = _batch_lead_details(
            session, list(page_assignments))
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
        leads = scores = catalogs = advisors = {}
        counts_rows = []
        status_options = []
        pos_options = []
        advisor_options = []
        assigned_total = 0
        overflow_total = 0

    rows = []
    for assignment in page_assignments:
        row = _supervision_row(assignment, leads, scores, catalogs, advisors)
        if row is not None:
            rows.append(row)
    counts = {"Alta": 0, "Media": 0, "Baja": 0}
    for band, count in counts_rows:
        if band in counts:
            counts[band] += count
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

    def _supervision_url(target_page: int) -> str:
        return "/supervision?" + urlencode({**base_params, "page": target_page})

    pagination = {
        "page": page_number,
        "total_pages": total_pages,
        "total": total,
        "prev_url": _supervision_url(page_number - 1) if page_number > 1 else None,
        "next_url": _supervision_url(page_number + 1) if page_number < total_pages else None,
    }
    tabs = {
        "active": "gestion",
        "pending_count": overflow_total,
        "base_query": ("?" + urlencode(base_params)) if base_params else "",
    }
    # Conversaciones de ESTA ejecución (ids en la query), resueltas en batch y
    # re-filtradas por el scope de la sesión (nunca fuera de la empresa).
    ai_conversations: list[dict] = []
    requested_ids = _parse_ai_ids(ai_ids)
    if requested_ids:
        ai_conversations = [
            {"conversation_id": conv_id, "lead_id": lead_id,
             "customer_name": customer_name, "status": status}
            for conv_id, lead_id, customer_name, status in session.execute(
                sa.select(Conversation.conversation_id, Conversation.lead_id,
                          Lead.customer_name, AIExtraction.status)
                .select_from(Conversation)
                .outerjoin(Lead, Lead.lead_id == Conversation.lead_id)
                .outerjoin(
                    AIExtraction,
                    (AIExtraction.conversation_id == Conversation.conversation_id)
                    & (AIExtraction.is_current.is_(True)),
                )
                .where(Conversation.conversation_id.in_(requested_ids),
                       Conversation.company_id.in_(scope_companies))
                .order_by(Conversation.conversation_id)
            ).all()
        ]
    lifecycle_rows = (
        dict(session.execute(
            sa.select(Lead.status, sa.func.count())
            .where(Lead.company_id.in_(scope_companies))
            .group_by(Lead.status)
        ).all())
        if scope_companies else {}
    )
    lifecycle = {
        "open": sum(count for status, count in lifecycle_rows.items()
                    if not is_lead_terminal(status)),
        "closed": lifecycle_rows.get("Cerrado", 0),
        "lost": lifecycle_rows.get("Perdido", 0),
        "discarded": lifecycle_rows.get("Descartado", 0),
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
            "lifecycle": lifecycle,
            "pagination": pagination,
            "tabs": tabs,
            "filter_action": "/supervision",
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
            "ai": {
                "providers": _configured_ai_providers(settings),
                "pending": len(_ai_pending_conversation_ids(session, scope_companies)),
                "limit_options": list(AI_LIMIT_OPTIONS),
                "limit_default": 10,
                "max_limit": MAX_AI_LIMIT,
            },
            "ai_result": ({
                "provider": ai_provider or "",
                "model": ai_model or "",
                "limit": ai_limit,
                "candidates": ai_candidates,
                "processed": ai_processed,
                "success": ai_success or 0,
                "reused": ai_reused,
                "errors": ai_errors,
                "failed": ai_failed,
                "failure_reason": ai_failure_reason or "",
                "seconds": ai_seconds,
                "rescored": ai_rescored,
                "rescore_errors": ai_rescore_errors,
                "conversations": ai_conversations,
                "empty": bool(ai_empty),
                "unavailable": bool(ai_unavailable),
                "reason": ai_reason or "",
            } if ai is not None else None),
        },
    )


@router.get("/supervision/pending", response_class=HTMLResponse)
def supervision_pending(
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
):
    """Bandeja de pendientes de asignación. Mismo scope y filtros que gestión."""
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    if user.role not in (ROLE_SUPERVISOR, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="La supervisión requiere rol supervisor")
    is_admin = user.role == ROLE_ADMIN

    scope = _supervision_scope(session, user, is_admin, empresa, supervisor)
    scope_companies = scope.company_ids

    resolved = run_date or session.scalar(
        sa.select(sa.func.max(Assignment.run_date)).where(
            Assignment.is_current.is_(True),
            Assignment.company_id.in_(scope_companies) if scope_companies else sa.false())
    )
    if resolved and scope_companies:
        ids_sub = _supervision_ids_stmt(
            scope_companies, resolved, pos, asesor, banda, estado, modelo,
            status=STATUS_OVERFLOW,
        ).subquery()
        pending_select = sa.select(ids_sub.c.assignment_id)
        total = session.scalar(
            sa.select(sa.func.count()).select_from(ids_sub)
        ) or 0
    else:
        ids_sub = None
        pending_select = None
        total = 0

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page_number = min(_parse_page(page), total_pages)
    offset = (page_number - 1) * PAGE_SIZE

    if total:
        pending_assignments = session.scalars(
            sa.select(Assignment)
            .where(Assignment.assignment_id.in_(pending_select))
            .order_by(*_supervision_order())
            .limit(PAGE_SIZE)
            .offset(offset)
        ).all()
        leads, scores, catalogs, advisors = _batch_lead_details(
            session, list(pending_assignments))
        status_options = sorted({
            (status or UNKNOWN)
            for (status,) in session.execute(
                sa.select(Lead.status.distinct())
                .select_from(Lead)
                .join(Assignment, Assignment.lead_id == Lead.lead_id)
                .where(Assignment.assignment_id.in_(pending_select))
            ).all()
        })
        option_pairs = session.execute(
            sa.select(Assignment.point_of_sale_id.distinct(),
                      Assignment.advisor_id)
            .where(
                Assignment.is_current.is_(True),
                Assignment.company_id.in_(scope_companies),
                Assignment.run_date == resolved,
                Assignment.status == STATUS_OVERFLOW,
            )
        ).all()
        pos_options = sorted({pos_id for pos_id, _ in option_pairs if pos_id})
        advisor_options = sorted({
            advisor_id for pos_id, advisor_id in option_pairs
            if advisor_id and (not pos or pos_id == pos)
        })
    else:
        pending_assignments = []
        leads = scores = catalogs = advisors = {}
        status_options = []
        pos_options = []
        advisor_options = []

    rows = []
    for assignment in pending_assignments:
        row = _supervision_row(assignment, leads, scores, catalogs, advisors)
        if row is not None:
            rows.append(row)
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

    def _pending_url(target_page: int) -> str:
        return "/supervision/pending?" + urlencode({**base_params, "page": target_page})

    pagination = {
        "page": page_number,
        "total_pages": total_pages,
        "total": total,
        "prev_url": _pending_url(page_number - 1) if page_number > 1 else None,
        "next_url": _pending_url(page_number + 1) if page_number < total_pages else None,
    }
    tabs = {
        "active": "pendientes",
        "pending_count": total,
        "base_query": ("?" + urlencode(base_params)) if base_params else "",
    }
    return templates.TemplateResponse(
        request=request,
        name="supervision_pending.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "is_admin": is_admin,
            "title": "Supervisión global" if is_admin else "Supervisión",
            "company_label": None if is_admin else (scope_companies[0] if scope_companies else None),
            "run_date": resolved.isoformat() if resolved else None,
            "rows": rows,
            "total": total,
            "pagination": pagination,
            "tabs": tabs,
            "filter_action": "/supervision/pending",
            "retry": {
                "ran": retry is not None,
                "assigned": retry_assigned,
                "overflow": retry_overflow,
                "reused": bool(retry_reused),
            },
            "counts": {"Alta": 0, "Media": 0, "Baja": 0},
            "filters": {"empresa": empresa or "", "supervisor": supervisor or "",
                        "pos": pos or "", "asesor": asesor or "",
                        "banda": banda or "", "estado": estado or "",
                        "modelo": modelo or ""},
            "company_options": scope.companies if is_admin else [],
            "supervisor_options": supervisor_options,
            "pos_options": pos_options,
            "advisor_options": advisor_options,
            "band_options": ["Alta", "Media", "Baja"],
            "status_options": status_options,
            "page_size": PAGE_SIZE,
        },
    )


@router.post("/supervision/run-ai")
def run_ai_analysis(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    provider: str = Form(default=""),
    limit: str = Form(default=""),
    empresa: str = Form(default=None),
    return_to: str = Form(default=None),
):
    """Ejecuta el análisis IA (máx. `limit`) sobre pendientes del alcance.

    Reutiliza el pipeline existente: `process_pending` (extracción + validación
    + persistencia). Solo permitido a supervisor/admin y acotado a su empresa.
    """
    if isinstance(user, RedirectResponse):
        return user
    if user.role not in (ROLE_SUPERVISOR, ROLE_ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Solo supervisor o admin pueden ejecutar el análisis IA",
        )
    settings = get_settings()
    is_admin = user.role == ROLE_ADMIN
    base = ("/supervision/pending" if return_to == "/supervision/pending"
            else "/supervision")

    # Validación server-side: el navegador no decide proveedor ni límite.
    allowed = {p["value"] for p in _configured_ai_providers(settings)}
    if provider not in allowed:
        raise HTTPException(status_code=400, detail="Proveedor de IA no permitido")
    if is_production(settings) and provider not in PRODUCTION_PROVIDERS:
        # Defensa adicional: aunque llegue el valor por HTTP, en producción
        # solo se admiten proveedores remotos (ver app/ai/factory.py).
        raise HTTPException(
            status_code=400, detail="Proveedor de IA no permitido en producción")
    selected_limit = _validate_ai_limit(limit)
    if selected_limit is None:
        raise HTTPException(status_code=400, detail="Límite de IA inválido")

    scope = _supervision_scope(session, user, is_admin, empresa, None)
    conversation_ids = _ai_pending_conversation_ids(session, scope.company_ids)
    if not conversation_ids:
        return RedirectResponse(
            url=f"{base}?ai=1&ai_empty=1&ai_provider={quote(provider)}",
            status_code=303,
        )

    extractor = build_extractor(provider, settings)
    available, reason = extractor.availability()
    if not available:
        return RedirectResponse(
            url=(f"{base}?ai=1&ai_unavailable=1&ai_provider={quote(provider)}"
                 f"&ai_reason={quote(str(reason))}"),
            status_code=303,
        )

    started = time.perf_counter()
    report = process_pending(
        session, extractor, limit=selected_limit,
        conversation_ids=conversation_ids,
    )
    elapsed = round(time.perf_counter() - started, 1)

    # Recálculo inmediato del score de los leads afectados (reutiliza
    # score_and_persist_lead; consolida internamente). Nunca ejecuta
    # ingesta, dedup, asignación ni un nuevo pipeline.
    rescored = 0
    rescore_errors: list[dict] = []
    processed_ids = report.get("processed_ids") or []
    lead_ids: list[str] = []
    if processed_ids:
        seen: set[str] = set()
        rows = session.execute(
            sa.select(Conversation.lead_id).where(
                Conversation.conversation_id.in_(processed_ids),
                Conversation.company_id.in_(scope.company_ids),
                Conversation.lead_id.is_not(None),
            )
        ).all()
        for (lead_id,) in rows:
            if lead_id and lead_id not in seen:
                seen.add(lead_id)
                lead_ids.append(lead_id)
    for lead_id in lead_ids:
        try:
            score_and_persist_lead(session, lead_id)
        except Exception as exc:  # noqa: BLE001 - un lead no rompe el resto
            session.rollback()
            rescore_errors.append(
                {"lead_id": lead_id, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        rescored += 1

    params = {
        "ai": "1",
        "ai_provider": provider,
        "ai_model": str(report.get("model") or ""),
        "ai_limit": selected_limit,
        "ai_candidates": report["candidates"],
        "ai_processed": report["processed"],
        "ai_success": report.get("success", 0),
        "ai_reused": report["reused"],
        "ai_errors": report["errors"],
        "ai_failed": report["failed"],
        "ai_failure_reason": _safe_error_summary(
            (report.get("failures") or []) + (report.get("error_reasons") or [])),
        "ai_seconds": elapsed,
        "ai_rescored": rescored,
        "ai_rescore_errors": len(rescore_errors),
        "ai_ids": ",".join(processed_ids),
    }
    return RedirectResponse(url=f"{base}?{urlencode(params)}", status_code=303)


@router.post("/supervision/ai-local-context")
def ai_local_context(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    limit: int = Form(default=10),
    empresa: str = Form(default=None),
):
    """Contexto para ejecutar Ollama en el navegador del usuario.

    Devuelve, para conversaciones pendientes del alcance, los mensajes exactos
    (prompt V8 + schema v1) que el navegador debe enviar a ``127.0.0.1:11434``.
    El backend no contacta a Ollama ni expone credenciales.
    """
    if isinstance(user, RedirectResponse):
        return JSONResponse({"error": "no autenticado"}, status_code=401)
    if user.role not in (ROLE_SUPERVISOR, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Rol no autorizado")
    scope = _supervision_scope(session, user, user.role == ROLE_ADMIN, empresa, None)
    pending = _ai_pending_conversation_ids(session, scope.company_ids)
    selected = pending[: max(1, min(int(limit or 1), MAX_AI_LIMIT))]
    conversations = []
    for conversation_id in selected:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None:
            continue
        conversations.append({
            "conversation_id": conversation_id,
            "messages": build_messages(conversation_to_input(conversation)),
        })
    return JSONResponse({
        "provider": "ollama",
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "schema": ExtractionResult.model_json_schema(),
        "conversations": conversations,
    })


@router.post("/supervision/ai-local-result")
def ai_local_result(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    payload: dict = Body(...),
):
    """Persiste el resultado estructurado que produjo Ollama en el navegador.

    Reutiliza ``process_conversation`` (validación de evidencia, idempotencia
    por ``input_hash``, ``is_current``) y el rescoring existente. El resultado
    se valida con el schema v1; el backend no contacta a ningún proveedor.
    """
    if isinstance(user, RedirectResponse):
        return JSONResponse({"ok": False, "message": "No autenticado"}, status_code=401)
    if user.role not in (ROLE_SUPERVISOR, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Rol no autorizado")

    conversation_id = str(payload.get("conversation_id") or "").strip()
    model = payload.get("model")
    raw_result = payload.get("result")
    conversation = session.get(Conversation, conversation_id) if conversation_id else None
    if conversation is None or not _conversation_in_scope(session, user, conversation):
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    try:
        parsed = parse_browser_result(raw_result)
    except ValidationError:
        return JSONResponse({
            "ok": False, "conversation_id": conversation_id, "status": "error",
            "message": "El proveedor de IA no pudo procesar esta conversación.",
        })

    replay = BrowserOllamaReplay(model, parsed)
    try:
        result = process_conversation(session, conversation_id, replay)
    except Exception:  # noqa: BLE001 - nunca exponer el detalle técnico
        session.rollback()
        return JSONResponse({
            "ok": False, "conversation_id": conversation_id, "status": "error",
            "message": "No fue posible completar el análisis.",
        })

    status = result.extraction.status
    rescored = False
    if status == STATUS_SUCCESS and conversation.lead_id:
        try:
            score_and_persist_lead(session, conversation.lead_id)
            rescored = True
        except Exception:  # noqa: BLE001
            session.rollback()
    return JSONResponse({
        "ok": status == STATUS_SUCCESS,
        "conversation_id": conversation_id,
        "status": status,
        "message": ("Análisis completado." if status == STATUS_SUCCESS
                    else "El proveedor de IA no pudo procesar esta conversación."),
        "model": model,
        "rescored": rescored,
    })


@router.get("/ai/conversations", response_class=HTMLResponse)
def ai_conversations(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    search: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    signal: str | None = Query(default=None),
    state: str | None = Query(default=None),
    order: str | None = Query(default=None),
    page: str | None = Query(default=None),
):
    """Conversaciones con extracción IA vigente y exitosa dentro del scope."""
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    order_value = order if order in {value for value, _ in AI_ORDER_OPTIONS} else "analyzed_desc"
    stmt = _analyzed_conversations_stmt(user, search, intent, signal, state)
    total = session.scalar(
        sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())
    ) or 0
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page_number = min(_parse_page(page), total_pages)
    offset = (page_number - 1) * PAGE_SIZE
    rows = [
        _ai_conversation_row(conversation, lead, extraction, lead_band, assign_count)
        for conversation, extraction, lead, lead_band, assign_count in session.execute(
            stmt.order_by(*_analyzed_order(order_value))
            .limit(PAGE_SIZE).offset(offset)
        ).all()
    ]
    base_params: dict = {}
    for key, value in (("search", search), ("intent", intent),
                       ("signal", signal), ("state", state), ("order", order_value)):
        if value:
            base_params[key] = value

    def _url(target_page: int) -> str:
        return "/ai/conversations?" + urlencode({**base_params, "page": target_page})

    pagination = {
        "page": page_number,
        "total_pages": total_pages,
        "total": total,
        "prev_url": _url(page_number - 1) if page_number > 1 else None,
        "next_url": _url(page_number + 1) if page_number < total_pages else None,
    }
    # Enlace al detalle conservando filtros/orden/página (vuelta a la lista).
    detail_query = urlencode(base_params)
    return templates.TemplateResponse(
        request=request,
        name="ai_conversations.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "is_admin": user.role == ROLE_ADMIN,
            "rows": rows,
            "pagination": pagination,
            "filters": {"search": search or "", "intent": intent or "",
                        "signal": signal or "", "state": state or "",
                        "order": order_value},
            "intent_filters": AI_INTENT_FILTERS,
            "signal_filters": AI_SIGNAL_FILTERS,
            "state_filters": AI_STATE_FILTERS,
            "order_options": AI_ORDER_OPTIONS,
            "detail_query": ("?" + detail_query) if detail_query else "",
        },
    )


@router.get("/ai/conversations/{conversation_id}", response_class=HTMLResponse)
def ai_conversation_detail(
    conversation_id: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    search: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    signal: str | None = Query(default=None),
    state: str | None = Query(default=None),
    order: str | None = Query(default=None),
    page: str | None = Query(default=None),
):
    """Detalle de una conversación analizada (mensajes + extracción IA)."""
    if isinstance(user, RedirectResponse):
        return user
    settings = get_settings()
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or not _conversation_in_scope(session, user, conversation):
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    extraction = get_current_extraction(session, conversation_id)
    fields = (extraction.fields if extraction and isinstance(extraction.fields, dict)
              else {})
    lead = session.get(Lead, conversation.lead_id) if conversation.lead_id else None
    ordered = sorted(
        (m for m in (conversation.messages or []) if isinstance(m, dict)),
        key=lambda m: m.get("seq") if isinstance(m.get("seq"), int) else 0,
    )
    messages = [
        {
            "sender_label": sender_label(m.get("sender")),
            "sender_class": sender_class(m.get("sender")),
            "hour": str(m.get("hour") or ""),
            "text": str(m.get("text") or ""),
        }
        for m in ordered
    ]
    back_params: dict = {}
    for key, value in (("search", search), ("intent", intent),
                       ("signal", signal), ("state", state), ("order", order),
                       ("page", page)):
        if value:
            back_params[key] = value
    back_url = "/ai/conversations" + (f"?{urlencode(back_params)}" if back_params else "")
    return templates.TemplateResponse(
        request=request,
        name="ai_conversation_detail.html",
        context={
            "app_name": settings.app_name,
            "user": user,
            "is_admin": user.role == ROLE_ADMIN,
            "conversation": conversation,
            "lead": lead,
            "extraction": extraction,
            "fields": fields,
            "messages": messages,
            "back_url": back_url,
        },
    )


@router.post("/supervision/retry-assignment")
def retry_assignment_action(
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    empresa: str | None = Form(default=None),
    return_to: str | None = Form(default=None),
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
    # Destino de vuelta restringido a las dos bandejas (sin open redirect).
    base = "/supervision/pending" if return_to == "/supervision/pending" else "/supervision"
    return RedirectResponse(
        url=(
            f"{base}?retry=1"
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
    lead: Lead | None = None
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
        # El lead puede no tener asignación vigente: el scope se valida por la
        # empresa del lead (supervisor) o global (admin), no por la asignación.
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        if user.role != ROLE_ADMIN and lead.company_id != user.company_id:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
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
        owner = (session.get(Advisor, assignment.advisor_id)
                 if assignment and assignment.advisor_id else None)
        advisor, owner_name = owner, (
            owner.name if owner else "Sin asignación vigente")
        back_url, back_label = "/supervision", "Volver a Supervisión comercial"
    if lead is None:
        lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    score = _current_score(session, lead_id)
    catalog = session.get(CatalogItem, lead.sku) if lead.sku else None
    conversations = session.scalars(
        sa.select(Conversation)
        .where(Conversation.lead_id == lead_id)
        .order_by(Conversation.conversation_id)
    ).all()
    # Catálogo canónico (mismo matching que la ingesta) para comparar modelos.
    catalog_rows = session.execute(
        sa.select(CatalogItem.sku, CatalogItem.brand, CatalogItem.line)
    ).all()
    catalog_index = build_catalog_index(catalog_rows)
    brand_by_sku = {sku: brand for sku, brand, _line in catalog_rows}
    crm_text = (lead.model_text_raw or "").strip()
    crm_match = match_model(crm_text, catalog_index) if crm_text else {"sku": None}
    crm_sku = lead.sku or crm_match["sku"]
    ia_entries: list[dict] = []
    conv_rows = []
    for conversation in conversations:
        messages = [m for m in (conversation.messages or []) if isinstance(m, dict)]
        ordered = sorted(
            messages,
            key=lambda m: m.get("seq") if isinstance(m.get("seq"), int) else 0,
        )
        extraction = get_current_extraction(session, conversation.conversation_id)
        fields = dict(extraction.fields) if extraction and extraction.fields else {}
        ia_model = (fields.get("model_interes") or "").strip()
        if ia_model:
            ia_entries.append({
                "conversation_id": conversation.conversation_id,
                "ia_model": ia_model,
                "ia_sku": match_model(ia_model, catalog_index)["sku"],
                "evidence": fields.get("model_interes_evidence"),
            })
        conv_rows.append(
            {
                "conversation": conversation,
                "message_count": len(messages),
                "fields": fields,
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
    # Inconsistencia SOLO con modelos comparables (SKU canónico) y distintos.
    model_inconsistencies: list[dict] = []
    if crm_sku:
        crm_brand = brand_by_sku.get(crm_sku)
        seen_ia_skus: set[str] = set()
        for entry in ia_entries:
            ia_sku = entry["ia_sku"]
            if not ia_sku or ia_sku == crm_sku or ia_sku in seen_ia_skus:
                continue
            seen_ia_skus.add(ia_sku)
            model_inconsistencies.append({
                "conversation_id": entry["conversation_id"],
                "crm_model": crm_text or (_model_label(lead, catalog)),
                "crm_sku": crm_sku,
                "ia_model": entry["ia_model"],
                "ia_sku": ia_sku,
                "kind": ("Mismo fabricante, modelo diferente"
                         if brand_by_sku.get(ia_sku) == crm_brand
                         else "Marca distinta"),
                "evidence": entry["evidence"],
            })
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
            "model_inconsistencies": model_inconsistencies,
            "unknown": UNKNOWN,
            "bool_label": _bool_label,
            "open_statuses": OPEN_STATUSES,
            "terminal_statuses": TERMINAL_STATUSES,
            "close_reasons": CLOSE_REASONS,
            "is_terminal": is_lead_terminal(lead.status),
        },
    )


@router.post("/leads/{lead_id}/status")
def update_lead_status_action(
    lead_id: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User | RedirectResponse = Depends(require_login),
    status: str = Form(...),
    close_reason: str = Form(default=""),
):
    """Cambia el estado de gestión del lead; si es terminal, lo cierra con motivo.

    Permisos: asesor solo sobre leads con asignación vigente suya; supervisor
    solo sobre su empresa; admin global.
    """
    if isinstance(user, RedirectResponse):
        return user

    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    if user.role == ROLE_ADVISOR:
        advisor = session.get(Advisor, user.advisor_id) if user.advisor_id else None
        if advisor is None or advisor.company_id != user.company_id:
            raise HTTPException(status_code=403, detail="Cuenta de asesor no válida")
        assignment = session.scalar(
            sa.select(Assignment).where(
                Assignment.advisor_id == advisor.advisor_id,
                Assignment.company_id == user.company_id,
                Assignment.lead_id == lead_id,
                Assignment.is_current.is_(True),
            )
        )
        if assignment is None:
            raise HTTPException(status_code=403, detail="Lead fuera de su ámbito")
    elif user.role == ROLE_SUPERVISOR:
        if lead.company_id != user.company_id:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
    elif user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Rol no autorizado")

    try:
        update_lead_status(session, lead, status, close_reason=close_reason or None)
    except LeadTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=f"/leads/{lead_id}", status_code=303)
