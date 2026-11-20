from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, comparisons, dashboards, datasets, health, incidents, inventory_ops, operations, qc, recovery, reviews, scenarios
from app.api.upload_limit import UploadBodyLimitMiddleware
from app.db.session import db_manager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db_manager.ensure_initialized()
    yield


app = FastAPI(
    title="GiziOptima — Kitchen Operations & Procurement Intelligence API",
    version="0.3.0",
    lifespan=lifespan,
    description=(
        "Sprint 3A Backend: Multi-actor RBAC (KITCHEN_MANAGER, MENU_PLANNER, QC_OFFICER) "
        "with HttpOnly cookie sessions + CSRF protection, kitchen-level data isolation, "
        "menu operational review workflow, AI-assisted visual menu verification with human-in-the-loop "
        "review and private EXIF-stripped image storage, plus deterministic MILP optimization "
        "and independent raw verification."
    ),
)

_cors_raw = os.getenv(
    "GIZIOPTIMA_CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
)
_cors_origins = [origin.strip() for origin in _cors_raw.split(",") if origin.strip()]

app.add_middleware(UploadBodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(datasets.router, prefix="/api/v1")
app.include_router(inventory_ops.router, prefix="/api/v1")
app.include_router(scenarios.router, prefix="/api/v1")
app.include_router(comparisons.router, prefix="/api/v1")
app.include_router(reviews.router, prefix="/api/v1")
app.include_router(operations.router, prefix="/api/v1")
app.include_router(recovery.router, prefix="/api/v1")
app.include_router(incidents.router, prefix="/api/v1")
app.include_router(qc.router, prefix="/api/v1")
app.include_router(dashboards.router, prefix="/api/v1")
