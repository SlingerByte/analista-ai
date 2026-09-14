from fastapi import FastAPI

from app.config import get_settings
from app.dashboard import router as dashboard_router
from app.db import check_database

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(dashboard_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "database": check_database()}
