from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_db_session, require_roles
from app.auth.schemas import RoleEnum
from app.recovery.procurement import export_procurement_delta_to_csv
from app.recovery.schemas import (
    DisruptionConditionRequest,
    DisruptionImpactReport,
    RecoveryEventResponse,
    RecoveryModeEnum,
    RecoverySubmitRequest,
)
from app.recovery.service import (
    analyze_and_create_recovery_event,
    get_recovery_event,
    list_recovery_events,
    preview_disruption_impact,
    submit_recovery_candidate,
)
from app.reviews.schemas import MenuReviewResponse

router = APIRouter(prefix="/recovery", tags=["recovery"])


class RecoverySubmitResponse(BaseModel):
    recovery_event: RecoveryEventResponse
    review: MenuReviewResponse


@router.post("/impact", response_model=DisruptionImpactReport)
def api_preview_disruption_impact(
    req: DisruptionConditionRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(get_db_session),
) -> DisruptionImpactReport:
    return preview_disruption_impact(session, auth, req)


@router.post("/events", response_model=RecoveryEventResponse, status_code=201)
def api_create_recovery_event(
    req: DisruptionConditionRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(get_db_session),
) -> RecoveryEventResponse:
    return analyze_and_create_recovery_event(session, auth, req)


@router.get("/events", response_model=List[RecoveryEventResponse])
def api_list_recovery_events(
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER, RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> List[RecoveryEventResponse]:
    return list_recovery_events(session, auth)


@router.get("/events/{event_id}", response_model=RecoveryEventResponse)
def api_get_recovery_event(
    event_id: UUID,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER, RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> RecoveryEventResponse:
    return get_recovery_event(session, auth, event_id)


@router.post("/events/{event_id}/submit", response_model=RecoverySubmitResponse)
def api_submit_recovery_event(
    event_id: UUID,
    req: RecoverySubmitRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(get_db_session),
) -> RecoverySubmitResponse:
    event_resp, review_resp = submit_recovery_candidate(session, auth, event_id, req)
    return RecoverySubmitResponse(recovery_event=event_resp, review=review_resp)


@router.get("/events/{event_id}/procurement.csv")
def api_export_recovery_procurement_csv(
    event_id: UUID,
    mode: RecoveryModeEnum = Query(default=RecoveryModeEnum.MIN_DISRUPTION),
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER, RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> Response:
    event_resp = get_recovery_event(session, auth, event_id)
    items = event_resp.procurement_delta_by_mode.get(mode.value, [])
    cand = (
        event_resp.min_disruption
        if mode == RecoveryModeEnum.MIN_DISRUPTION
        else event_resp.min_cost
    )
    csv_text = export_procurement_delta_to_csv(
        event_id=str(event_id),
        title=event_resp.title,
        mode=mode.value,
        items=items,
        days_count=event_resp.impact.days,
        servings_per_day=event_resp.impact.servings_per_day,
        total_servings=event_resp.impact.days * event_resp.impact.servings_per_day,
        total_cost_idr=cand.total_cost_idr,
    )
    safe_id = str(event_id).replace('"', "")
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="gizioptima_recovery_{safe_id}_{mode.value.lower()}.csv"'
        },
    )
