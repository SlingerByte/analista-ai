from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai.factory import AIProviderConfigError, validate_ai_configuration
from app.auth import router as auth_router
from app.config import get_settings, validate_startup_configuration
from app.dashboard import router as dashboard_router
from app.db import check_database

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fallar temprano y con mensaje claro si el entorno exige configuración
    # que no está presente (producción sin SECRET_KEY o sin IA remota).
    try:
        validate_startup_configuration(settings)
    except RuntimeError as exc:
        raise RuntimeError(f"Configuración inválida: {exc}") from exc
    try:
        validate_ai_configuration(settings)
    except AIProviderConfigError as exc:
        raise RuntimeError(f"Configuración de IA inválida: {exc}") from exc
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(dashboard_router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "database": check_database(),
        "ai_provider": settings.ai_provider,
    }
