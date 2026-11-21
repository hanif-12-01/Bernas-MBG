from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_current_auth, record_audit_event, require_roles
from app.auth.schemas import RoleEnum
from app.db.models import (
    IncidentAffectedLotORM,
    IngredientIncidentORM,
    InventoryMovementORM,
    UserORM,
)
from app.db.repository import SQLiteVaultRepository
from app.db.session import db_manager
from app.domain.models.schemas import (
    DatasetVersion,
    Ingredient,
    IngredientNutrients,
    RecipeVariant,
    ReviewStatusEnum,
    SourceTypeEnum,
)
from app.ingestion.csv_parser import (
    MAX_CSV_BYTES,
    CSVImportValidationError,
    DatasetImportResponse,
    UploadedCSVPayload,
    import_dataset_from_csv,
)
from app.inventory.coverage import IngredientCoverageForecast
from app.inventory.service import (
    ApprovedPlanInventoryAlert,
    InventoryLotSummary,
    compute_usable_inventory,
    evaluate_approved_plans_against_inventory,
    list_market_price_references,
)
from app.inventory.timezone_utils import parse_production_date_jakarta
from app.inventory.unit_normalizer import PriceProvenanceEnum, classify_price_provenance
from app.scenarios.service import ResourceNotFoundError

router = APIRouter(tags=["datasets"])


class DatasetVersionListItem(BaseModel):
    id: UUID
    name: str
    source_type: SourceTypeEnum
    source_url: Optional[str] = None
    is_synthetic: bool
    is_active: bool
    review_status: ReviewStatusEnum
    ingestion_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MarketReferenceHint(BaseModel):
    commodity_name: str
    region: str
    observed_date: date
    price_value: float
    unit: str
    source_name: str
    price_provenance: PriceProvenanceEnum


class InventoryCatalogItem(BaseModel):
    id: UUID
    code: str
    name: str
    category: str
    edible_fraction: float
    allergens: List[str] = Field(default_factory=list)
    nutrients: IngredientNutrients
    price_idr_per_g: Optional[float] = None
    original_price_value: Optional[float] = None
    original_price_unit: Optional[str] = None
    price_region: Optional[str] = None
    price_observed_at: Optional[date] = None
    price_source_type: Optional[SourceTypeEnum] = None
    price_provenance: Optional[PriceProvenanceEnum] = PriceProvenanceEnum.SYNTHETIC_EXAMPLE
    stock_raw_g: Optional[float] = None
    recorded_raw_g: Optional[float] = None
    usable_raw_g: Optional[float] = None
    physical_raw_g: Optional[float] = None
    reserved_raw_g: float = 0.0
    unavailable_raw_g: float = 0.0
    expired_raw_g: float = 0.0
    damaged_raw_g: float = 0.0
    unverified_raw_g: float = 0.0
    safety_held_raw_g: float = 0.0
    rejected_disposed_raw_g: float = 0.0
    held_lot_codes: List[str] = Field(default_factory=list)
    lots: List[InventoryLotSummary] = Field(default_factory=list)
    incoming_raw_g: float = 0.0
    delivery_status: str = "NONE"
    quarantined_events_count: int = 0
    latest_supplier_name: Optional[str] = None
    latest_received_at: Optional[datetime] = None
    nearest_expiry_at: Optional[datetime] = None
    days_until_nearest_expiry: Optional[int] = None
    coverage: Optional[IngredientCoverageForecast] = None
    data_quality_status: str = "SYNTHETIC_BASELINE"
    data_classification: str = "synthetic"
    last_verified_at: Optional[datetime] = None
    availability_explanation: Optional[str] = None
    availability_warnings: List[str] = Field(default_factory=list)
    market_references: List[MarketReferenceHint] = Field(default_factory=list)
    source_type: SourceTypeEnum
    source_ref: str
    review_status: ReviewStatusEnum


class InventoryCatalogResponse(BaseModel):
    dataset: DatasetVersionListItem
    uses_batch_ledger: bool = False
    production_date: Optional[datetime] = None
    verified_count: int = 0
    warning_count: int = 0
    unknown_count: int = 0
    quarantined_events_count: int = 0
    approved_plan_alerts: List[ApprovedPlanInventoryAlert] = Field(default_factory=list)
    items: List[InventoryCatalogItem]


class InventoryMovementSummaryItem(BaseModel):
    id: UUID
    movement_type: str
    quantity_delta_raw_g: float
    original_value: float
    original_unit: str
    lot_code: Optional[str] = None
    source_document_ref: Optional[str] = None
    event_at: datetime
    quarantined: bool = False
    quarantine_reason: Optional[str] = None
    actor_name: Optional[str] = None


class InventoryActiveIncidentHint(BaseModel):
    id: UUID
    title: str
    category: str
    severity: str
    status: str
    observed_at: datetime
    total_held_kg: float = 0.0


class InventoryIngredientDetailResponse(BaseModel):
    ingredient: InventoryCatalogItem
    recent_movements: List[InventoryMovementSummaryItem] = Field(default_factory=list)
    active_incidents: List[InventoryActiveIncidentHint] = Field(default_factory=list)


def _get_session():
    yield from db_manager.get_session()


def _parse_prod_date_param(raw: Optional[str]) -> Optional[datetime]:
    if raw is None or not raw.strip():
        return None
    try:
        return parse_production_date_jakarta(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Format tanggal produksi tidak valid: '{raw}'."
        ) from exc


def _build_inventory_catalog_item(
    *,
    ing: Ingredient,
    pr: Any,
    st: Any,
    av: Any,
    ds_row: Any,
    market_refs: List[MarketReferenceHint],
    hide_pricing: bool,
) -> InventoryCatalogItem:
    usable_val = av.usable_raw_g if av is not None else (st.stock_raw_g if st else None)
    provenance = classify_price_provenance(
        source_type=pr.source_type.value if pr else None,
        is_synthetic=ds_row.is_synthetic,
    )
    return InventoryCatalogItem(
        id=ing.id,
        code=ing.code,
        name=ing.name,
        category=ing.category,
        edible_fraction=ing.edible_fraction,
        allergens=list(ing.allergens),
        nutrients=ing.nutrients,
        price_idr_per_g=None if hide_pricing else (pr.price_idr_per_g if pr else None),
        original_price_value=None if hide_pricing else (pr.original_value if pr else None),
        original_price_unit=None if hide_pricing else (pr.original_unit if pr else None),
        price_region=None if hide_pricing else (pr.region if pr else None),
        price_observed_at=None if hide_pricing else (pr.observed_at if pr else None),
        price_source_type=None if hide_pricing else (pr.source_type if pr else None),
        price_provenance=None if hide_pricing else provenance,
        stock_raw_g=usable_val,
        recorded_raw_g=av.recorded_raw_g if av else (st.stock_raw_g if st else None),
        usable_raw_g=usable_val,
        physical_raw_g=av.physical_raw_g if av else None,
        reserved_raw_g=av.reserved_raw_g if av else 0.0,
        unavailable_raw_g=av.unavailable_raw_g if av else 0.0,
        expired_raw_g=av.expired_raw_g if av else 0.0,
        damaged_raw_g=av.damaged_raw_g if av else 0.0,
        unverified_raw_g=av.unverified_raw_g if av else 0.0,
        safety_held_raw_g=av.safety_held_raw_g if av else 0.0,
        rejected_disposed_raw_g=av.rejected_disposed_raw_g if av else 0.0,
        held_lot_codes=av.held_lot_codes if av else [],
        lots=av.lots if av else [],
        incoming_raw_g=av.incoming_raw_g if av else 0.0,
        delivery_status=av.delivery_status if av else "NONE",
        quarantined_events_count=av.quarantined_events_count if av else 0,
        latest_supplier_name=av.latest_supplier_name if av else None,
        latest_received_at=av.latest_received_at if av else None,
        nearest_expiry_at=av.nearest_expiry_at if av else None,
        days_until_nearest_expiry=av.days_until_nearest_expiry if av else None,
        coverage=av.coverage if av else None,
        data_quality_status=av.data_quality_status if av else "UNKNOWN",
        data_classification=av.data_classification if av else ("synthetic" if ds_row.is_synthetic else "pilot_real"),
        last_verified_at=av.last_verified_at if av else None,
        availability_explanation=av.availability_explanation if av else None,
        availability_warnings=av.warnings if av else [],
        market_references=[] if hide_pricing else market_refs[:3],
        source_type=ing.source_type,
        source_ref=av.source_name if av else ing.source_ref,
        review_status=ing.review_status,
    )


@router.get("/datasets", response_model=List[DatasetVersionListItem])
def list_datasets(
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> List[DatasetVersionListItem]:
    repo = SQLiteVaultRepository(session)
    rows = repo.list_datasets(kitchen_id=auth.kitchen_id)
    return [
        DatasetVersionListItem(
            id=UUID(r.id),
            name=r.name,
            source_type=SourceTypeEnum(r.source_type),
            source_url=r.source_url,
            is_synthetic=r.is_synthetic,
            is_active=r.is_active,
            review_status=ReviewStatusEnum(r.review_status),
            ingestion_metadata=dict(r.ingestion_metadata_json or {}),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/inventory", response_model=InventoryCatalogResponse)
def get_inventory_catalog(
    dataset_version_id: Optional[UUID] = None,
    production_date: Optional[str] = None,
    auth: AuthContext = Depends(
        require_roles(
            RoleEnum.KITCHEN_MANAGER,
            RoleEnum.MENU_PLANNER,
            RoleEnum.QC_OFFICER,
            RoleEnum.NUTRITIONIST,
        )
    ),
    session: Session = Depends(_get_session),
) -> InventoryCatalogResponse:
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    parsed_prod_dt = _parse_prod_date_param(production_date)
    try:
        ds_row = repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
        ingredients_by_code, _, prices_by_code, stock_by_code, _ = repo.load_dataset_bundle(
            ds_id, kitchen_id=auth.kitchen_id
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    availability = compute_usable_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=ds_id,
        production_date=parsed_prod_dt,
    )
    avail_by_code = {a.ingredient_code: a for a in availability.items}
    approved_alerts = evaluate_approved_plans_against_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        production_date=parsed_prod_dt,
    )
    hide_pricing = auth.role == RoleEnum.QC_OFFICER
    market_refs_by_code: Dict[str, List[MarketReferenceHint]] = {}
    if not hide_pricing:
        for mr in list_market_price_references(session):
            if mr.canonical_ingredient_code:
                market_refs_by_code.setdefault(mr.canonical_ingredient_code, []).append(
                    MarketReferenceHint(
                        commodity_name=mr.commodity_name,
                        region=mr.region,
                        observed_date=mr.observed_date,
                        price_value=mr.price_value,
                        unit=mr.unit,
                        source_name=mr.source_name,
                        price_provenance=mr.price_provenance,
                    )
                )

    items = [
        _build_inventory_catalog_item(
            ing=ingredients_by_code[code],
            pr=prices_by_code.get(code),
            st=stock_by_code.get(code),
            av=avail_by_code.get(code),
            ds_row=ds_row,
            market_refs=market_refs_by_code.get(code, []),
            hide_pricing=hide_pricing,
        )
        for code in sorted(ingredients_by_code.keys())
    ]

    return InventoryCatalogResponse(
        dataset=DatasetVersionListItem(
            id=UUID(ds_row.id),
            name=ds_row.name,
            source_type=SourceTypeEnum(ds_row.source_type),
            source_url=ds_row.source_url,
            is_synthetic=ds_row.is_synthetic,
            is_active=ds_row.is_active,
            review_status=ReviewStatusEnum(ds_row.review_status),
            ingestion_metadata=dict(ds_row.ingestion_metadata_json or {}),
            created_at=ds_row.created_at,
        ),
        uses_batch_ledger=availability.uses_batch_ledger,
        production_date=availability.production_date,
        verified_count=availability.verified_count,
        warning_count=availability.warning_count,
        unknown_count=availability.unknown_count,
        quarantined_events_count=availability.quarantined_events_count,
        approved_plan_alerts=approved_alerts,
        items=items,
    )


@router.get("/inventory/{ingredient_code}/detail", response_model=InventoryIngredientDetailResponse)
def get_inventory_ingredient_detail(
    ingredient_code: str,
    dataset_version_id: Optional[UUID] = None,
    production_date: Optional[str] = None,
    auth: AuthContext = Depends(
        require_roles(
            RoleEnum.KITCHEN_MANAGER,
            RoleEnum.MENU_PLANNER,
            RoleEnum.QC_OFFICER,
            RoleEnum.NUTRITIONIST,
        )
    ),
    session: Session = Depends(_get_session),
) -> InventoryIngredientDetailResponse:
    """Lot breakdown, movement history, active incidents & FEFO forecast for one ingredient (pricing stripped for QC)."""
    from sqlalchemy import select as sa_select

    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    parsed_prod_dt = _parse_prod_date_param(production_date)
    try:
        ds_row = repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
        ingredients_by_code, _, prices_by_code, stock_by_code, _ = repo.load_dataset_bundle(
            ds_id, kitchen_id=auth.kitchen_id
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    code_clean = ingredient_code.strip()
    ing = ingredients_by_code.get(code_clean)
    if ing is None:
        raise HTTPException(status_code=404, detail=f"Bahan '{code_clean}' tidak ditemukan.")

    availability = compute_usable_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=ds_id,
        production_date=parsed_prod_dt,
    )
    avail_by_code = {a.ingredient_code: a for a in availability.items}
    av = avail_by_code.get(code_clean)
    hide_pricing = auth.role == RoleEnum.QC_OFFICER

    market_refs: List[MarketReferenceHint] = []
    if not hide_pricing:
        for mr in list_market_price_references(session, canonical_ingredient_code=code_clean):
            market_refs.append(
                MarketReferenceHint(
                    commodity_name=mr.commodity_name,
                    region=mr.region,
                    observed_date=mr.observed_date,
                    price_value=mr.price_value,
                    unit=mr.unit,
                    source_name=mr.source_name,
                    price_provenance=mr.price_provenance,
                )
            )

    catalog_item = _build_inventory_catalog_item(
        ing=ing,
        pr=prices_by_code.get(code_clean),
        st=stock_by_code.get(code_clean),
        av=av,
        ds_row=ds_row,
        market_refs=market_refs,
        hide_pricing=hide_pricing,
    )

    lot_code_by_id = {str(l.id): l.lot_code for l in (av.lots if av else [])}
    mov_rows = list(
        session.execute(
            sa_select(InventoryMovementORM)
            .where(
                InventoryMovementORM.kitchen_id == str(auth.kitchen_id),
                InventoryMovementORM.dataset_version_id == str(ds_id),
                InventoryMovementORM.ingredient_id == str(ing.id),
            )
            .order_by(InventoryMovementORM.event_at.desc(), InventoryMovementORM.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    actor_ids = {m.actor_user_id for m in mov_rows if m.actor_user_id}
    actor_names: Dict[str, str] = {}
    if actor_ids:
        for u in session.execute(sa_select(UserORM).where(UserORM.id.in_(actor_ids))).scalars().all():
            actor_names[u.id] = u.full_name

    recent_movements = [
        InventoryMovementSummaryItem(
            id=UUID(m.id),
            movement_type=m.movement_type,
            quantity_delta_raw_g=float(m.quantity_delta_raw_g),
            original_value=float(m.original_value),
            original_unit=m.original_unit,
            lot_code=lot_code_by_id.get(m.lot_id) if m.lot_id else None,
            source_document_ref=m.source_document_ref,
            event_at=m.event_at,
            quarantined=bool(m.quarantined),
            quarantine_reason=m.quarantine_reason,
            actor_name=actor_names.get(m.actor_user_id) if m.actor_user_id else None,
        )
        for m in mov_rows
    ]

    aff_rows = list(
        session.execute(
            sa_select(IncidentAffectedLotORM).where(
                IncidentAffectedLotORM.kitchen_id == str(auth.kitchen_id),
                IncidentAffectedLotORM.dataset_version_id == str(ds_id),
                IncidentAffectedLotORM.ingredient_id == str(ing.id),
            )
        )
        .scalars()
        .all()
    )
    inc_ids = {a.incident_id for a in aff_rows}
    active_incidents: List[InventoryActiveIncidentHint] = []
    if inc_ids:
        inc_rows = list(
            session.execute(
                sa_select(IngredientIncidentORM)
                .where(IngredientIncidentORM.id.in_(inc_ids))
                .order_by(IngredientIncidentORM.created_at.desc())
            )
            .scalars()
            .all()
        )
        for inc in inc_rows:
            held_kg = sum(
                float(a.recorded_raw_g_snapshot)
                for a in aff_rows
                if a.incident_id == inc.id and a.lot_safety_status == "ON_HOLD"
            ) / 1000.0
            active_incidents.append(
                InventoryActiveIncidentHint(
                    id=UUID(inc.id),
                    title=inc.title,
                    category=inc.category,
                    severity=inc.severity,
                    status=inc.status,
                    observed_at=inc.observed_at,
                    total_held_kg=round(held_kg, 2),
                )
            )

    return InventoryIngredientDetailResponse(
        ingredient=catalog_item,
        recent_movements=recent_movements,
        active_incidents=active_incidents,
    )


@router.post("/datasets/import", response_model=DatasetImportResponse, status_code=201)
async def api_import_dataset(
    ingredients_file: UploadFile = File(...),
    prices_file: UploadFile = File(...),
    stock_file: UploadFile = File(...),
    recipes_file: UploadFile = File(...),
    name: str = Form("Imported Dataset (SIMULASI)", min_length=1, max_length=255),
    source_type: SourceTypeEnum = Form(SourceTypeEnum.SYNTHETIC),
    source_url: Optional[str] = Form(None, max_length=2048),
    is_synthetic: bool = Form(True),
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> DatasetImportResponse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Nama dataset wajib diisi.")
    if source_type == SourceTypeEnum.SYNTHETIC and not is_synthetic:
        raise HTTPException(status_code=422, detail="Sumber sintetis harus ditandai sebagai data simulasi.")
    ing_payload = UploadedCSVPayload(
        file_key="ingredients_file",
        filename=ingredients_file.filename or "",
        content_type=ingredients_file.content_type or "",
        raw_bytes=await ingredients_file.read(MAX_CSV_BYTES + 1),
    )
    price_payload = UploadedCSVPayload(
        file_key="prices_file",
        filename=prices_file.filename or "",
        content_type=prices_file.content_type or "",
        raw_bytes=await prices_file.read(MAX_CSV_BYTES + 1),
    )
    stock_payload = UploadedCSVPayload(
        file_key="stock_file",
        filename=stock_file.filename or "",
        content_type=stock_file.content_type or "",
        raw_bytes=await stock_file.read(MAX_CSV_BYTES + 1),
    )
    rec_payload = UploadedCSVPayload(
        file_key="recipes_file",
        filename=recipes_file.filename or "",
        content_type=recipes_file.content_type or "",
        raw_bytes=await recipes_file.read(MAX_CSV_BYTES + 1),
    )

    try:
        result = import_dataset_from_csv(
            session,
            name=name,
            source_type=source_type,
            source_url=source_url,
            is_synthetic=is_synthetic,
            kitchen_id=auth.kitchen_id,
            ingredients_csv=ing_payload,
            prices_csv=price_payload,
            stock_csv=stock_payload,
            recipes_csv=rec_payload,
        )
        record_audit_event(
            session,
            action="dataset.imported",
            entity_type="dataset",
            entity_id=str(result.dataset_version_id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={"name": name, "ingredients": result.ingredients_imported},
        )
        session.commit()
        return result
    except CSVImportValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "errors": [e.model_dump() for e in exc.errors],
            },
        ) from exc


@router.get("/datasets/{dataset_id}", response_model=DatasetVersion)
def get_dataset(
    dataset_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> DatasetVersion:
    repo = SQLiteVaultRepository(session)
    try:
        return repo.get_dataset(dataset_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ingredients", response_model=List[Ingredient])
def list_ingredients(
    dataset_version_id: Optional[UUID] = None,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> List[Ingredient]:
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        ingredients_by_code, _, _, _, _ = repo.load_dataset_bundle(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sorted(ingredients_by_code.values(), key=lambda x: x.code)


@router.get("/recipes", response_model=List[RecipeVariant])
def list_reviewed_recipes(
    include_unreviewed: bool = False,
    dataset_version_id: Optional[UUID] = None,
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(_get_session),
) -> List[RecipeVariant]:
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        _, _, _, _, recipes = repo.load_dataset_bundle(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if include_unreviewed:
        return recipes
    return [r for r in recipes if r.review_status == ReviewStatusEnum.REVIEWED and r.active]
