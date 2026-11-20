from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.analytics.comparison import ScenarioComparisonResponse, compare_runs
from app.auth.dependencies import AuthContext, require_roles
from app.auth.schemas import RoleEnum
from app.db.repository import SQLiteVaultRepository
from app.db.session import db_manager
from app.scenarios.service import ResourceNotFoundError

router = APIRouter(tags=["comparisons"])


def _get_session():
    yield from db_manager.get_session()


@router.get("/comparisons", response_model=ScenarioComparisonResponse)
def api_compare_runs(
    base_id: UUID = Query(..., description="UUID of baseline OptimizationRun"),
    candidate_id: UUID = Query(..., description="UUID of candidate OptimizationRun"),
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> ScenarioComparisonResponse:
    repo = SQLiteVaultRepository(session)
    try:
        base_run = repo.get_run(base_id, kitchen_id=auth.kitchen_id)
        candidate_run = repo.get_run(candidate_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return compare_runs(base_run, candidate_run)
