"""Autenticación mínima real: sesión firmada en cookie + login/logout.

Sin dependencias nuevas: HMAC-SHA256 (stdlib) para firmar la sesión y
PBKDF2-SHA256 (stdlib) para contraseñas. Apropiado para app server-rendered
local; documentado como no apto para producción sin endurecer (expiración
corta, rotación de SECRET_KEY, HTTPS, rate-limit).

La cookie solo guarda ``user_id`` + expiración firmados. La identidad y el
rol siempre se cargan desde la DB (``current_user``); el frontend nunca
aporta identidad.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import User

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

SESSION_COOKIE = "analista_session"
SESSION_MAX_AGE = 12 * 3600
ROLE_ADVISOR = "asesor"
ROLE_SUPERVISOR = "supervisor"
ROLE_ADMIN = "admin"

_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 con salt aleatorio. Nunca texto plano."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return (
        f"pbkdf2${_PBKDF2_ITERATIONS}"
        f"${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        name, iterations, salt_b64, hash_b64 = stored.split("$")
        if name != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(),
            base64.b64decode(salt_b64), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def _signature(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_value(user_id: int, secret: str) -> str:
    payload = f"{user_id}:{int(time.time()) + SESSION_MAX_AGE}"
    return f"{payload}:{_signature(payload, secret)}"


def parse_session_value(value: str, secret: str) -> int | None:
    try:
        user_id, exp, signature = value.split(":")
        if not hmac.compare_digest(_signature(f"{user_id}:{exp}", secret), signature):
            return None
        if int(exp) < time.time():
            return None
        return int(user_id)
    except (ValueError, TypeError):
        return None


def get_current_user(
    request: Request, session: Session = Depends(get_session)
) -> User | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    user_id = parse_session_value(raw, get_settings().secret_key)
    if user_id is None:
        return None
    return session.get(User, user_id)


def require_login(request: Request, user: User | None = Depends(get_current_user)):
    """Retorna el usuario o una redirección a /login (para vistas HTML)."""
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return user


def _set_session(response: RedirectResponse, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_value(user_id, get_settings().secret_key),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user: User | None = Depends(get_current_user)):
    if user is not None:
        target = "/supervision" if user.role == ROLE_SUPERVISOR else "/"
        return RedirectResponse(url=target, status_code=303)
    return templates.TemplateResponse(
        request=request, name="login.html",
        context={"app_name": get_settings().app_name, "error": None},
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    session: Session = Depends(get_session),
):
    settings = get_settings()
    user = session.scalar(sa.select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"app_name": settings.app_name,
                     "error": "Credenciales inválidas."},
            status_code=401,
        )
    if user.role == ROLE_ADVISOR:
        advisor = user.advisor
        if advisor is None or not advisor.active:
            return templates.TemplateResponse(
                request=request, name="login.html",
                context={"app_name": settings.app_name,
                         "error": "Cuenta de asesor inactiva."},
                status_code=403,
            )
        target = "/"
    else:
        target = "/supervision"
    response = RedirectResponse(url=target, status_code=303)
    _set_session(response, user.user_id)
    return response


@router.get("/logout")
@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


def fresh_secret(nbytes: int = 32) -> str:
    """Genera un SECRET_KEY seguro para .env (utilidad CLI, no ruta web)."""
    return secrets.token_urlsafe(nbytes)
