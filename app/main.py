from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ai.factory import AIProviderConfigError, validate_ai_configuration
from app.auth import router as auth_router
from app.config import get_settings
from app.dashboard import router as dashboard_router
from app.db import check_database

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fallar temprano y con mensaje claro si el entorno exige una
    # configuración de IA que no está presente (p. ej. producción sin clave).
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
