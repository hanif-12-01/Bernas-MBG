from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_current_auth, get_db_session, require_roles
from app.auth.schemas import RoleEnum
from app.vision.image_security import MAX_QC_IMAGE_BYTES
from app.vision.schemas import (
    QCImageInfo,
    QCInspectionCreateRequest,
    QCInspectionResponse,
    QCInspectionStatusEnum,
    QCManagerReviewRequest,
    QCObservationsPatchRequest,
    QCSubmitRequest,
)
from app.vision.service import (
    analyze_inspection_with_ai,
    create_inspection,
    get_authorized_image_bytes,
    get_inspection,
    list_inspections,
    manager_review_inspection,
    save_human_observations_review,
    submit_inspection,
    upload_inspection_image,
)

router = APIRouter(prefix="/qc/inspections", tags=["qc"])


@router.post("", response_model=QCInspectionResponse, status_code=201)
def api_create_qc_inspection(
    req: QCInspectionCreateRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.QC_OFFICER)),
    session: Session = Depends(get_db_session),
) -> QCInspectionResponse:
    return create_inspection(session, auth, req)


@router.get("", response_model=List[QCInspectionResponse])
def api_list_qc_inspections(
    status: Optional[QCInspectionStatusEnum] = None,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> List[QCInspectionResponse]:
    return list_inspections(session, auth, status_filter=status)


@router.get("/{inspection_id}", response_model=QCInspectionResponse)
def api_get_qc_inspection(
    inspection_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> QCInspectionResponse:
    return get_inspection(session, auth, inspection_id)


@router.post("/{inspection_id}/images", response_model=QCImageInfo, status_code=201)
def api_upload_qc_image(
    inspection_id: UUID,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_roles(RoleEnum.QC_OFFICER)),
    session: Session = Depends(get_db_session),
) -> QCImageInfo:
    raw_bytes = file.file.read(MAX_QC_IMAGE_BYTES + 1)
    return upload_inspection_image(
        session, auth, inspection_id, raw_bytes, file.filename or "sample.jpg"
    )


@router.get("/{inspection_id}/images/{image_id}")
def api_get_qc_image(
    inspection_id: UUID,
    image_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    data, mime_type = get_authorized_image_bytes(session, auth, inspection_id, image_id)
    return Response(
        content=data,
        media_type=mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{inspection_id}/analyze", response_model=QCInspectionResponse)
def api_analyze_qc_inspection(
    inspection_id: UUID,
    image_id: Optional[UUID] = None,
    auth: AuthContext = Depends(require_roles(RoleEnum.QC_OFFICER)),
    session: Session = Depends(get_db_session),
) -> QCInspectionResponse:
    return analyze_inspection_with_ai(session, auth, inspection_id, image_id=image_id)


@router.patch("/{inspection_id}/observations", response_model=QCInspectionResponse)
def api_patch_qc_observations(
    inspection_id: UUID,
    req: QCObservationsPatchRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.QC_OFFICER)),
    session: Session = Depends(get_db_session),
) -> QCInspectionResponse:
    return save_human_observations_review(session, auth, inspection_id, req)


@router.post("/{inspection_id}/submit", response_model=QCInspectionResponse)
def api_submit_qc_inspection(
    inspection_id: UUID,
    req: Optional[QCSubmitRequest] = Body(default=None),
    auth: AuthContext = Depends(require_roles(RoleEnum.QC_OFFICER)),
    session: Session = Depends(get_db_session),
) -> QCInspectionResponse:
    return submit_inspection(session, auth, inspection_id, req)


@router.post("/{inspection_id}/review", response_model=QCInspectionResponse)
def api_review_qc_inspection(
    inspection_id: UUID,
    req: QCManagerReviewRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> QCInspectionResponse:
    return manager_review_inspection(session, auth, inspection_id, req)
