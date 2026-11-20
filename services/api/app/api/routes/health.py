from __future__ import annotations

from fastapi import APIRouter

from app.db.session import db_manager
from app.vision.provider import get_vision_provider_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "gizioptima-api",
        "model_version": "recipe-milp-v0.1",
        "simulation_only": True,
        "persistence": "sqlite" if db_manager.database_url.startswith("sqlite") else "sql",
        "vision_provider": get_vision_provider_status(),
    }
