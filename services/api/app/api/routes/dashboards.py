from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_db_session, require_roles
from app.auth.schemas import AuditEventResponse, RoleEnum
from app.db.models import AuditEventORM, IngredientIncidentORM, UserORM
from app.db.repository import SQLiteVaultRepository
from app.inventory.service import (
    ApprovedPlanInventoryAlert,
    compute_usable_inventory,
    evaluate_approved_plans_against_inventory,
)
from app.operations.schemas import OperationalPlanAssignmentResponse
from app.operations.service import list_operational_plan_assignments
from app.reviews.schemas import MenuReviewResponse, MenuReviewStatusEnum
from app.reviews.service import list_menu_reviews
from app.vision.provider import get_vision_provider_status
from app.vision.schemas import (
    ComparisonStatusEnum,
    QCInspectionResponse,
    QCInspectionStatusEnum,
)
from app.vision.service import list_inspections

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class LowStockAlert(BaseModel):
    ingredient_code: str
    ingredient_name: str
    stock_raw_g: float


class ManagerDashboardSummary(BaseModel):
    kitchen_id: UUID
    kitchen_name: str
    simulation_only: bool = True
    total_validated_runs: int
    latest_run_id: Optional[UUID] = None
    latest_cost_per_serving_idr: Optional[float] = None
    latest_total_cost_idr: Optional[float] = None
    pending_menu_reviews: List[MenuReviewResponse] = Field(default_factory=list)
    approved_menu_reviews_count: int
    pending_qc_inspections: List[QCInspectionResponse] = Field(default_factory=list)
    qc_discrepancies_count: int
    low_stock_alerts: List[LowStockAlert] = Field(default_factory=list)
    approved_plan_inventory_alerts: List[ApprovedPlanInventoryAlert] = Field(default_factory=list)
    effective_operational_plans: List[OperationalPlanAssignmentResponse] = Field(default_factory=list)
    approved_awaiting_activation: List[MenuReviewResponse] = Field(default_factory=list)
    active_incidents_count: int = 0
    inventory_dataset_name: Optional[str] = None
    inventory_dataset_is_synthetic: Optional[bool] = None
    recent_audit_events: List[AuditEventResponse] = Field(default_factory=list)
    vision_provider_status: Dict[str, Any] = Field(default_factory=dict)


class QCDashboardSummary(BaseModel):
    kitchen_id: UUID
    kitchen_name: str
    simulation_only: bool = True
    available_menu_plans: List[MenuReviewResponse] = Field(default_factory=list)
    effective_operational_plans: List[OperationalPlanAssignmentResponse] = Field(default_factory=list)
    held_operational_plans: List[OperationalPlanAssignmentResponse] = Field(default_factory=list)
    active_incidents_count: int = 0
    action_required_inspections: List[QCInspectionResponse] = Field(default_factory=list)
    submitted_or_reviewed_inspections: List[QCInspectionResponse] = Field(default_factory=list)
    total_inspections_count: int
    vision_provider_status: Dict[str, Any] = Field(default_factory=dict)


@router.get("/manager-summary", response_model=ManagerDashboardSummary)
def api_manager_summary(
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> ManagerDashboardSummary:
    repo = SQLiteVaultRepository(session)
    runs = repo.list_runs(validated_only=True, kitchen_id=auth.kitchen_id)
    latest_run = runs[0] if runs else None

    all_reviews = list_menu_reviews(session, auth)
    pending_reviews = [r for r in all_reviews if r.status == MenuReviewStatusEnum.SUBMITTED]
    approved_count = sum(1 for r in all_reviews if r.status == MenuReviewStatusEnum.APPROVED)

    all_inspections = list_inspections(session, auth)
    pending_qc = [i for i in all_inspections if i.status == QCInspectionStatusEnum.SUBMITTED]

    discrepancies = 0
    for insp in all_inspections:
        if insp.ai_observations:
            latest_ai = insp.ai_observations[-1]
            if any(
                f.status
                in {
                    ComparisonStatusEnum.MISSING_EXPECTED,
                    ComparisonStatusEnum.UNCERTAIN,
                    ComparisonStatusEnum.NEEDS_MANUAL_CHECK,
                }
                for f in latest_ai.comparison_findings
            ):
                discrepancies += 1

    # Use usable stock availability from the latest validated run's dataset version.
    low_stock: List[LowStockAlert] = []
    inventory_dataset = None
    if latest_run:
        dataset_id = UUID(latest_run.dataset_version_id)
        inventory_dataset = repo.get_dataset_orm(dataset_id, kitchen_id=auth.kitchen_id)
        avail_summary = compute_usable_inventory(
            session,
            kitchen_id=auth.kitchen_id,
            dataset_version_id=dataset_id,
        )
        for av in avail_summary.items:
            if av.usable_raw_g is None or av.usable_raw_g < 10000:
                low_stock.append(
                    LowStockAlert(
                        ingredient_code=av.ingredient_code,
                        ingredient_name=av.ingredient_name,
                        stock_raw_g=av.usable_raw_g if av.usable_raw_g is not None else 0.0,
                    )
                )

    approved_inv_alerts = evaluate_approved_plans_against_inventory(
        session, kitchen_id=auth.kitchen_id
    )
    effective_ops = list_operational_plan_assignments(
        session, auth.kitchen_id, include_superseded=False
    )
    awaiting_activation = [
        r
        for r in all_reviews
        if r.status == MenuReviewStatusEnum.APPROVED
        and r.operational_status == "APPROVED_NOT_ACTIVE"
    ]
    active_inc_count = len(
        session.execute(
            select(IngredientIncidentORM.id).where(
                IngredientIncidentORM.kitchen_id == str(auth.kitchen_id),
                IngredientIncidentORM.status.in_(["REPORTED", "ON_HOLD", "UNDER_REVIEW"]),
            )
        ).all()
    )

    audit_rows = list(
        session.execute(
            select(AuditEventORM)
            .where(AuditEventORM.kitchen_id == str(auth.kitchen_id))
            .order_by(AuditEventORM.created_at.desc())
            .limit(12)
        )
        .scalars()
        .all()
    )
    user_ids = {a.actor_user_id for a in audit_rows if a.actor_user_id}
    users = (
        {
            u.id: u
            for u in session.execute(select(UserORM).where(UserORM.id.in_(user_ids))).scalars().all()
        }
        if user_ids
        else {}
    )
    recent_audits = [
        AuditEventResponse(
            id=UUID(a.id),
            kitchen_id=UUID(a.kitchen_id) if a.kitchen_id else None,
            actor_user_id=UUID(a.actor_user_id) if a.actor_user_id else None,
            actor_username=users[a.actor_user_id].username if a.actor_user_id in users else None,
            actor_full_name=users[a.actor_user_id].full_name if a.actor_user_id in users else None,
            actor_role=a.actor_role,
            action=a.action,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            metadata=dict(a.metadata_json or {}),
            created_at=a.created_at,
        )
        for a in audit_rows
    ]

    return ManagerDashboardSummary(
        kitchen_id=auth.kitchen_id,
        kitchen_name=auth.kitchen_name,
        simulation_only=True,
        total_validated_runs=len(runs),
        latest_run_id=UUID(latest_run.id) if latest_run else None,
        latest_cost_per_serving_idr=latest_run.cost_per_serving_average_idr if latest_run else None,
        latest_total_cost_idr=latest_run.objective_total_idr if latest_run else None,
        pending_menu_reviews=pending_reviews,
        approved_menu_reviews_count=approved_count,
        pending_qc_inspections=pending_qc,
        qc_discrepancies_count=discrepancies,
        low_stock_alerts=low_stock[:6],
        approved_plan_inventory_alerts=approved_inv_alerts,
        effective_operational_plans=effective_ops,
        approved_awaiting_activation=awaiting_activation,
        active_incidents_count=active_inc_count,
        inventory_dataset_name=inventory_dataset.name if inventory_dataset else None,
        inventory_dataset_is_synthetic=inventory_dataset.is_synthetic if inventory_dataset else None,
        recent_audit_events=recent_audits,
        vision_provider_status=get_vision_provider_status(),
    )


@router.get("/qc-summary", response_model=QCDashboardSummary)
def api_qc_summary(
    auth: AuthContext = Depends(require_roles(RoleEnum.QC_OFFICER, RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> QCDashboardSummary:
    approved_reviews = list_menu_reviews(session, auth, MenuReviewStatusEnum.APPROVED)
    # Exclude superseded historical approvals from active QC selection, prioritizing ACTIVE plans first
    relevant_plans = [
        r for r in approved_reviews if r.operational_status != "SUPERSEDED"
    ]
    relevant_plans.sort(
        key=lambda r: (0 if r.operational_status == "ACTIVE" else 1 if r.operational_status == "ON_HOLD" else 2)
    )
    effective_ops = list_operational_plan_assignments(
        session, auth.kitchen_id, include_superseded=False
    )
    active_ops = [p for p in effective_ops if p.operational_status.value == "ACTIVE"]
    held_ops = [p for p in effective_ops if p.operational_status.value == "ON_HOLD"]
    active_inc_count = len(
        session.execute(
            select(IngredientIncidentORM.id).where(
                IngredientIncidentORM.kitchen_id == str(auth.kitchen_id),
                IngredientIncidentORM.status.in_(["REPORTED", "ON_HOLD", "UNDER_REVIEW"]),
            )
        ).all()
    )
    all_inspections = list_inspections(session, auth)
    action_required = [
        i
        for i in all_inspections
        if i.status
        in {
            QCInspectionStatusEnum.CREATED,
            QCInspectionStatusEnum.AI_ANALYZED,
            QCInspectionStatusEnum.HUMAN_REVIEWED,
        }
    ]
    submitted_or_reviewed = [
        i
        for i in all_inspections
        if i.status in {QCInspectionStatusEnum.SUBMITTED, QCInspectionStatusEnum.REVIEWED}
    ]
    return QCDashboardSummary(
        kitchen_id=auth.kitchen_id,
        kitchen_name=auth.kitchen_name,
        simulation_only=True,
        available_menu_plans=relevant_plans,
        effective_operational_plans=active_ops,
        held_operational_plans=held_ops,
        active_incidents_count=active_inc_count,
        action_required_inspections=action_required,
        submitted_or_reviewed_inspections=submitted_or_reviewed,
        total_inspections_count=len(all_inspections),
        vision_provider_status=get_vision_provider_status(),
    )
