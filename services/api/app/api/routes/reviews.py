from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_current_auth, get_db_session, require_roles
from app.auth.schemas import RoleEnum
from app.reviews.schemas import (
    MenuReviewCreateRequest,
    MenuReviewDecisionRequest,
    MenuReviewResponse,
    MenuReviewStatusEnum,
    MenuReviewSubmitRequest,
)
from app.reviews.service import (
    create_menu_review,
    get_menu_review,
    list_menu_reviews,
    review_menu_plan,
    submit_menu_review,
)

router = APIRouter(prefix="/menu-reviews", tags=["menu-reviews"])


@router.post("", response_model=MenuReviewResponse, status_code=201)
def api_create_menu_review(
    req: MenuReviewCreateRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(get_db_session),
) -> MenuReviewResponse:
    return create_menu_review(session, auth, req)


@router.get("", response_model=List[MenuReviewResponse])
def api_list_menu_reviews(
    status: Optional[MenuReviewStatusEnum] = None,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(get_db_session),
) -> List[MenuReviewResponse]:
    return list_menu_reviews(session, auth, status_filter=status)


@router.get("/{review_id}", response_model=MenuReviewResponse)
def api_get_menu_review(
    review_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(get_db_session),
) -> MenuReviewResponse:
    return get_menu_review(session, auth, review_id)


@router.post("/{review_id}/submit", response_model=MenuReviewResponse)
def api_submit_menu_review(
    review_id: UUID,
    req: Optional[MenuReviewSubmitRequest] = Body(default=None),
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(get_db_session),
) -> MenuReviewResponse:
    return submit_menu_review(session, auth, review_id, req)


@router.post("/{review_id}/review", response_model=MenuReviewResponse)
def api_review_menu_plan(
    review_id: UUID,
    req: MenuReviewDecisionRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> MenuReviewResponse:
    return review_menu_plan(session, auth, review_id, req)
