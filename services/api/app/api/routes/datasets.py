from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_current_auth, record_audit_event, require_roles
from app.auth.schemas import RoleEnum
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
from app.inventory.service import (
    ApprovedPlanInventoryAlert,
    InventoryLotSummary,
    compute_usable_inventory,
    evaluate_approved_plans_against_inventory,
    list_market_price_references,
)
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
    price_provenance: PriceProvenanceEnum = PriceProvenanceEnum.SYNTHETIC_EXAMPLE
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


def _get_session():
    yield from db_manager.get_session()


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
    production_date: Optional[datetime] = None,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> InventoryCatalogResponse:
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
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
        production_date=production_date,
    )
    avail_by_code = {a.ingredient_code: a for a in availability.items}
    approved_alerts = evaluate_approved_plans_against_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        production_date=production_date,
    )
    market_refs_all = list_market_price_references(session)
    market_refs_by_code: Dict[str, List[MarketReferenceHint]] = {}
    for mr in market_refs_all:
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

    items: List[InventoryCatalogItem] = []
    for code in sorted(ingredients_by_code.keys()):
        ing = ingredients_by_code[code]
        pr = prices_by_code.get(code)
        st = stock_by_code.get(code)
        av = avail_by_code.get(code)
        usable_val = av.usable_raw_g if av is not None else (st.stock_raw_g if st else None)
        provenance = classify_price_provenance(
            source_type=pr.source_type.value if pr else None,
            is_synthetic=ds_row.is_synthetic,
        )
        items.append(
            InventoryCatalogItem(
                id=ing.id,
                code=ing.code,
                name=ing.name,
                category=ing.category,
                edible_fraction=ing.edible_fraction,
                allergens=list(ing.allergens),
                nutrients=ing.nutrients,
                price_idr_per_g=pr.price_idr_per_g if pr else None,
                original_price_value=pr.original_value if pr else None,
                original_price_unit=pr.original_unit if pr else None,
                price_region=pr.region if pr else None,
                price_observed_at=pr.observed_at if pr else None,
                price_source_type=pr.source_type if pr else None,
                price_provenance=provenance,
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
                data_quality_status=av.data_quality_status if av else "UNKNOWN",
                data_classification=av.data_classification if av else ("synthetic" if ds_row.is_synthetic else "pilot_real"),
                last_verified_at=av.last_verified_at if av else None,
                availability_explanation=av.availability_explanation if av else None,
                availability_warnings=av.warnings if av else [],
                market_references=market_refs_by_code.get(code, [])[:3],
                source_type=ing.source_type,
                source_ref=av.source_name if av else ing.source_ref,
                review_status=ing.review_status,
            )
        )

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
