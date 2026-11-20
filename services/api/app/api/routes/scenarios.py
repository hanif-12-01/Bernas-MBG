from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_current_auth, record_audit_event, require_roles
from app.auth.schemas import RoleEnum
from app.db.repository import SQLiteVaultRepository
from app.db.session import db_manager
from app.domain.models.schemas import (
    MaterialUsage,
    OptimizationRunResponse,
    OptimizeRequest,
    PriceOverridesRequest,
    Scenario,
    ScenarioCloneRequest,
    ScenarioCreateRequest,
    SolverStatusEnum,
    StockOverridesRequest,
)
from app.export.csv_exporter import ExportConflictError, export_run_to_csv
from app.ingestion.unit_converter import DataValidationError, UnitConversionError
from app.scenarios.service import ResourceNotFoundError, ScenarioConflictError

router = APIRouter(tags=["scenarios"])


class RunListItem(BaseModel):
    run_id: UUID
    scenario_id: UUID
    dataset_version_id: UUID
    solver_status: SolverStatusEnum
    validation_passed: bool
    simulation_only: bool
    objective_total_idr: Optional[float] = None
    cost_per_serving_average_idr: Optional[float] = None
    solver_seconds: float
    model_version: str
    input_sha256: str
    created_at: datetime


def _get_session():
    yield from db_manager.get_session()


@router.get("/scenarios", response_model=List[Scenario])
def api_list_scenarios(
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> List[Scenario]:
    repo = SQLiteVaultRepository(session)
    return repo.list_scenarios(
        kitchen_id=auth.kitchen_id, approved_only=auth.role == RoleEnum.QC_OFFICER
    )


@router.get("/runs", response_model=List[RunListItem])
def api_list_runs(
    scenario_id: Optional[UUID] = None,
    validated_only: bool = False,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> List[RunListItem]:
    repo = SQLiteVaultRepository(session)
    # QC starts from operationally approved, validator-passed plans.
    effective_validated_only = validated_only or (auth.role == RoleEnum.QC_OFFICER)
    rows = repo.list_runs(
        scenario_id=scenario_id,
        validated_only=effective_validated_only,
        kitchen_id=auth.kitchen_id,
        approved_only=auth.role == RoleEnum.QC_OFFICER,
    )
    return [
        RunListItem(
            run_id=UUID(r.id),
            scenario_id=UUID(r.scenario_id),
            dataset_version_id=UUID(r.dataset_version_id),
            solver_status=SolverStatusEnum(r.solver_status),
            validation_passed=r.validation_passed,
            simulation_only=r.simulation_only,
            objective_total_idr=r.objective_total_idr,
            cost_per_serving_average_idr=r.cost_per_serving_average_idr,
            solver_seconds=r.solver_seconds,
            model_version=r.model_version,
            input_sha256=r.input_sha256,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/scenarios", response_model=Scenario, status_code=201)
def api_create_scenario(
    req: ScenarioCreateRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> Scenario:
    repo = SQLiteVaultRepository(session)
    try:
        sc = repo.create_scenario(req, kitchen_id=auth.kitchen_id)
        record_audit_event(
            session,
            action="scenario.created",
            entity_type="scenario",
            entity_id=str(sc.id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={"name": sc.name},
        )
        session.commit()
        return sc
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DataValidationError, UnitConversionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scenarios/{scenario_id}", response_model=Scenario)
def api_get_scenario(
    scenario_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> Scenario:
    repo = SQLiteVaultRepository(session)
    try:
        return repo.get_scenario(
            scenario_id, kitchen_id=auth.kitchen_id, approved_only=auth.role == RoleEnum.QC_OFFICER
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/scenarios/{scenario_id}/clone", response_model=Scenario, status_code=201)
def api_clone_scenario(
    scenario_id: UUID,
    req: Optional[ScenarioCloneRequest] = Body(default=None),
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> Scenario:
    repo = SQLiteVaultRepository(session)
    try:
        sc = repo.clone_scenario(scenario_id, req, kitchen_id=auth.kitchen_id)
        record_audit_event(
            session,
            action="scenario.cloned",
            entity_type="scenario",
            entity_id=str(sc.id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={"parent_scenario_id": str(scenario_id), "name": sc.name},
        )
        session.commit()
        return sc
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/scenarios/{scenario_id}/price-overrides", response_model=Scenario)
def api_patch_price_overrides(
    scenario_id: UUID,
    req: PriceOverridesRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> Scenario:
    repo = SQLiteVaultRepository(session)
    try:
        sc = repo.apply_price_overrides(scenario_id, req, kitchen_id=auth.kitchen_id)
        record_audit_event(
            session,
            action="scenario.price_overrides_updated",
            entity_type="scenario",
            entity_id=str(scenario_id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={"override_count": len(req.overrides)},
        )
        session.commit()
        return sc
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DataValidationError, UnitConversionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/scenarios/{scenario_id}/stock-overrides", response_model=Scenario)
def api_patch_stock_overrides(
    scenario_id: UUID,
    req: StockOverridesRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> Scenario:
    repo = SQLiteVaultRepository(session)
    try:
        sc = repo.apply_stock_overrides(scenario_id, req, kitchen_id=auth.kitchen_id)
        record_audit_event(
            session,
            action="scenario.stock_overrides_updated",
            entity_type="scenario",
            entity_id=str(scenario_id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={"override_count": len(req.overrides)},
        )
        session.commit()
        return sc
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DataValidationError, UnitConversionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/scenarios/{scenario_id}/optimize", response_model=OptimizationRunResponse)
def api_optimize_scenario(
    scenario_id: UUID,
    req: Optional[OptimizeRequest] = Body(default=None),
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> OptimizationRunResponse:
    repo = SQLiteVaultRepository(session)
    time_limit = req.time_limit_seconds if req else 10.0
    try:
        run = repo.run_optimization(
            scenario_id, time_limit_seconds=time_limit, kitchen_id=auth.kitchen_id
        )
        record_audit_event(
            session,
            action="optimization_run.executed",
            entity_type="optimization_run",
            entity_id=str(run.run_id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={
                "scenario_id": str(scenario_id),
                "solver_status": run.solver_status.value,
                "validation_passed": run.validation_passed,
            },
        )
        session.commit()
        return run
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScenarioConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DataValidationError, UnitConversionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=OptimizationRunResponse)
def api_get_run(
    run_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> OptimizationRunResponse:
    repo = SQLiteVaultRepository(session)
    try:
        return repo.get_run(
            run_id, kitchen_id=auth.kitchen_id, approved_only=auth.role == RoleEnum.QC_OFFICER
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/shopping-list", response_model=List[MaterialUsage])
def api_get_shopping_list(
    run_id: UUID,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> List[MaterialUsage]:
    repo = SQLiteVaultRepository(session)
    try:
        run = repo.get_run(run_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if (
        not run.validation_passed
        or run.solver_status in {SolverStatusEnum.INFEASIBLE, SolverStatusEnum.ERROR}
        or not run.days
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run_id}' is not feasible/validated; shopping list cannot be generated.",
        )
    return run.material_usage


@router.get("/runs/{run_id}/export.csv")
def api_export_run_csv(
    run_id: UUID,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> Response:
    repo = SQLiteVaultRepository(session)
    try:
        run = repo.get_run(run_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        csv_text = export_run_to_csv(run)
    except ExportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="gizioptima_run_{run_id}.csv"'
        },
    )
