from __future__ import annotations

from datetime import date
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_current_auth, get_db_session, require_roles
from app.auth.schemas import RoleEnum
from app.operations.schemas import (
    ActivateReplacementPlanRequest,
    EffectiveOperationalPlanResponse,
    OperationalPlanAssignmentResponse,
)
from app.operations.service import (
    activate_replacement_plan,
    get_effective_operational_plan,
    list_operational_plan_assignments,
)

router = APIRouter(prefix="/operational-plans", tags=["operational-plans"])


@router.get("/effective", response_model=EffectiveOperationalPlanResponse)
def api_get_effective_operational_plan(
    production_date: Optional[date] = None,
    meal_type: Optional[str] = None,
    target_cohort: Optional[str] = None,
    batch_label: Optional[str] = None,
    dataset_version_id: Optional[UUID] = None,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> EffectiveOperationalPlanResponse:
    return get_effective_operational_plan(
        session,
        kitchen_id=auth.kitchen_id,
        production_date=production_date,
        meal_type=meal_type,
        target_cohort=target_cohort,
        batch_label=batch_label,
        dataset_version_id=dataset_version_id,
    )


@router.get("", response_model=List[OperationalPlanAssignmentResponse])
def api_list_operational_plans(
    dataset_version_id: Optional[UUID] = None,
    include_superseded: bool = Query(default=True),
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(get_db_session),
) -> List[OperationalPlanAssignmentResponse]:
    return list_operational_plan_assignments(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=dataset_version_id,
        include_superseded=include_superseded,
    )


@router.post("/activate", response_model=OperationalPlanAssignmentResponse)
def api_activate_operational_plan(
    req: ActivateReplacementPlanRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> OperationalPlanAssignmentResponse:
    return activate_replacement_plan(session, auth, req)
