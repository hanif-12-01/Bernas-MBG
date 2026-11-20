from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_db_session, require_roles
from app.auth.schemas import RoleEnum
from app.incidents.schemas import (
    IncidentActionResponse,
    IncidentCreateRequest,
    IncidentImageInfo,
    IncidentImpactSummaryResponse,
    IncidentReleaseHoldRequest,
    IncidentStartRecoveryRequest,
    IncidentStatusUpdateRequest,
    IngredientIncidentResponse,
)
from app.incidents.service import (
    get_incident,
    get_incident_actions,
    get_incident_image_bytes,
    get_incident_impact,
    list_incidents,
    release_safety_hold_blocked,
    report_ingredient_incident,
    start_recovery_for_incident,
    update_incident_status,
    upload_incident_image,
)
from app.recovery.schemas import RecoveryEventResponse
from app.vision.image_security import MAX_QC_IMAGE_BYTES

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=IngredientIncidentResponse, status_code=201)
def api_create_incident(
    req: IncidentCreateRequest,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
) -> IngredientIncidentResponse:
    return report_ingredient_incident(session, auth, req)


@router.get("", response_model=List[IngredientIncidentResponse])
def api_list_incidents(
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
) -> List[IngredientIncidentResponse]:
    return list_incidents(session, auth)


@router.get("/{incident_id}", response_model=IngredientIncidentResponse)
def api_get_incident(
    incident_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
) -> IngredientIncidentResponse:
    return get_incident(session, auth, incident_id)


@router.get("/{incident_id}/impact", response_model=IncidentImpactSummaryResponse)
def api_get_incident_impact(
    incident_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
) -> IncidentImpactSummaryResponse:
    return get_incident_impact(session, auth, incident_id)


@router.patch("/{incident_id}/status", response_model=IngredientIncidentResponse)
def api_update_incident_status(
    incident_id: UUID,
    req: IncidentStatusUpdateRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.QC_OFFICER)),
    session: Session = Depends(get_db_session),
) -> IngredientIncidentResponse:
    return update_incident_status(session, auth, incident_id, req)


@router.post("/{incident_id}/release-hold", status_code=403)
def api_attempt_release_safety_hold(
    incident_id: UUID,
    req: IncidentReleaseHoldRequest,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
):
    release_safety_hold_blocked(session, auth, incident_id, req)


@router.post("/{incident_id}/start-recovery", response_model=RecoveryEventResponse, status_code=201)
def api_start_incident_recovery(
    incident_id: UUID,
    req: IncidentStartRecoveryRequest = IncidentStartRecoveryRequest(),
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(get_db_session),
) -> RecoveryEventResponse:
    return start_recovery_for_incident(session, auth, incident_id, req)


@router.post("/{incident_id}/images", response_model=IncidentImageInfo, status_code=201)
async def api_upload_incident_image(
    incident_id: UUID,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
) -> IncidentImageInfo:
    raw = await file.read(MAX_QC_IMAGE_BYTES + 1)
    if len(raw) > MAX_QC_IMAGE_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"Ukuran foto melebihi {MAX_QC_IMAGE_BYTES // (1024 * 1024)} MB.",
        )
    return upload_incident_image(
        session, auth, incident_id, raw, file.filename or "bukti_insiden.png"
    )


@router.get("/{incident_id}/images/{image_id}")
def api_get_incident_image(
    incident_id: UUID,
    image_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    raw, mime = get_incident_image_bytes(session, auth, incident_id, image_id)
    return Response(
        content=raw,
        media_type=mime,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{incident_id}/actions", response_model=List[IncidentActionResponse])
def api_get_incident_actions(
    incident_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)
    ),
    session: Session = Depends(get_db_session),
) -> List[IncidentActionResponse]:
    return get_incident_actions(session, auth, incident_id)
