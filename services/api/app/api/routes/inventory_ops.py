from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    AuthContext,
    record_audit_event,
    require_active_stock_custodian,
    require_roles,
)
from app.auth.schemas import RoleEnum
from app.db.models import DatasetSourceORM, IngredientMappingORM
from app.db.repository import SQLiteVaultRepository
from app.db.session import db_manager
from app.ingestion.csv_parser import MAX_CSV_BYTES
from app.inventory.adjustments import (
    ManualStockAdjustmentRequest,
    ManualStockAdjustmentResponse,
    record_manual_inventory_adjustment,
)
from app.inventory.mapping import (
    ExternalProductCandidate,
    IngredientMappingReport,
    evaluate_external_mappings,
)
from app.inventory.service import (
    ApprovedPlanInventoryAlert,
    InventoryAvailabilitySummary,
    InventoryLotSummary,
    InventoryTransactionImportResponse,
    MarketPriceReferenceItem,
    MarketReferenceImportResponse,
    build_market_reference_template_csv,
    build_pilot_transactions_template_csv,
    compute_usable_inventory,
    evaluate_approved_plans_against_inventory,
    import_inventory_transactions_csv,
    import_market_price_references_csv,
    list_market_price_references,
    seed_dataset_sources_if_empty,
)
from app.inventory.unit_normalizer import PriceProvenanceEnum
from app.scenarios.service import ResourceNotFoundError

router = APIRouter(tags=["inventory-foundation"])


def _get_session():
    yield from db_manager.get_session()


class DatasetSourceItem(BaseModel):
    id: UUID
    source_name: str
    source_url: Optional[str] = None
    license: str
    license_verified: bool
    dataset_type: str
    retrieved_at: datetime
    checksum: Optional[str] = None
    allowed_use: str
    transformation_notes: Optional[str] = None


class InventoryAvailabilityResponse(BaseModel):
    summary: InventoryAvailabilitySummary
    approved_plan_alerts: List[ApprovedPlanInventoryAlert] = Field(default_factory=list)


class InventoryLotCatalogEntry(BaseModel):
    ingredient_id: UUID
    ingredient_code: str
    ingredient_name: str
    recorded_raw_g: Optional[float] = None
    usable_raw_g: Optional[float] = None
    safety_held_raw_g: float = 0.0
    rejected_disposed_raw_g: float = 0.0
    data_quality_status: str
    held_lot_codes: List[str] = Field(default_factory=list)
    lots: List[InventoryLotSummary] = Field(default_factory=list)


class InventoryLotsResponse(BaseModel):
    kitchen_id: UUID
    dataset_version_id: UUID
    production_date: datetime
    items: List[InventoryLotCatalogEntry] = Field(default_factory=list)


@router.get("/inventory/lots", response_model=InventoryLotsResponse)
def get_inventory_lots_no_pricing(
    dataset_version_id: Optional[UUID] = None,
    production_date: Optional[datetime] = None,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(_get_session),
) -> InventoryLotsResponse:
    """List inventory lots and safety-hold status without exposing supplier pricing (safe for QC_OFFICER)."""
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        summary = compute_usable_inventory(
            session,
            kitchen_id=auth.kitchen_id,
            dataset_version_id=ds_id,
            production_date=production_date,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return InventoryLotsResponse(
        kitchen_id=summary.kitchen_id,
        dataset_version_id=summary.dataset_version_id,
        production_date=summary.production_date,
        items=[
            InventoryLotCatalogEntry(
                ingredient_id=it.ingredient_id,
                ingredient_code=it.ingredient_code,
                ingredient_name=it.ingredient_name,
                recorded_raw_g=it.recorded_raw_g,
                usable_raw_g=it.usable_raw_g,
                safety_held_raw_g=it.safety_held_raw_g,
                rejected_disposed_raw_g=it.rejected_disposed_raw_g,
                data_quality_status=it.data_quality_status,
                held_lot_codes=it.held_lot_codes,
                lots=it.lots,
            )
            for it in summary.items
        ],
    )


class MappingValidateRequest(BaseModel):
    dataset_version_id: Optional[UUID] = None
    persist: bool = True
    candidates: List[ExternalProductCandidate] = Field(min_length=1)


class StoredMappingItem(BaseModel):
    id: UUID
    external_product_code: str
    external_product_name: str
    external_unit: str
    canonical_category: Optional[str] = None
    ingredient_code: Optional[str] = None
    standard_unit: str
    conversion_factor_to_g: Optional[float] = None
    density_g_per_ml: Optional[float] = None
    unit_weight_g: Optional[float] = None
    mapping_status: str
    review_status: str
    notes: Optional[str] = None


@router.get("/inventory/availability", response_model=InventoryAvailabilityResponse)
def get_inventory_availability(
    dataset_version_id: Optional[UUID] = None,
    production_date: Optional[datetime] = None,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> InventoryAvailabilityResponse:
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    summary = compute_usable_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=ds_id,
        production_date=production_date,
    )
    alerts = evaluate_approved_plans_against_inventory(
        session,
        kitchen_id=auth.kitchen_id,
        production_date=production_date,
    )
    return InventoryAvailabilityResponse(summary=summary, approved_plan_alerts=alerts)


@router.get("/inventory/sources", response_model=List[DatasetSourceItem])
def list_dataset_sources(
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> List[DatasetSourceItem]:
    seed_dataset_sources_if_empty(session)
    session.commit()
    rows = list(
        session.execute(
            select(DatasetSourceORM).order_by(DatasetSourceORM.created_at.desc())
        )
        .scalars()
        .all()
    )
    # Filter private kitchen sources cleanly while keeping global conceptual/official manifest visible (dedup by source_name)
    visible_by_name: Dict[str, DatasetSourceORM] = {}
    for r in rows:
        if r.kitchen_id is None or r.kitchen_id == str(auth.kitchen_id):
            if r.source_name not in visible_by_name or r.kitchen_id is not None:
                visible_by_name[r.source_name] = r
    visible = list(visible_by_name.values())
    return [
        DatasetSourceItem(
            id=UUID(r.id),
            source_name=r.source_name,
            source_url=r.source_url,
            license=r.license,
            license_verified=r.license_verified,
            dataset_type=r.dataset_type,
            retrieved_at=r.retrieved_at,
            checksum=r.checksum,
            allowed_use=r.allowed_use,
            transformation_notes=r.transformation_notes,
        )
        for r in visible
    ]


@router.get("/inventory/mappings", response_model=List[StoredMappingItem])
def list_ingredient_mappings(
    dataset_version_id: Optional[UUID] = None,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> List[StoredMappingItem]:
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    rows = list(
        session.execute(
            select(IngredientMappingORM)
            .where(
                IngredientMappingORM.kitchen_id == str(auth.kitchen_id),
                IngredientMappingORM.dataset_version_id == str(ds_id),
            )
            .order_by(IngredientMappingORM.external_product_code)
        )
        .scalars()
        .all()
    )
    return [
        StoredMappingItem(
            id=UUID(r.id),
            external_product_code=r.external_product_code,
            external_product_name=r.external_product_name,
            external_unit=r.external_unit,
            canonical_category=r.canonical_category,
            ingredient_code=r.ingredient_code,
            standard_unit=r.standard_unit,
            conversion_factor_to_g=r.conversion_factor_to_g,
            density_g_per_ml=r.density_g_per_ml,
            unit_weight_g=r.unit_weight_g,
            mapping_status=r.mapping_status,
            review_status=r.review_status,
            notes=r.notes,
        )
        for r in rows
    ]


@router.post("/inventory/mappings/validate", response_model=IngredientMappingReport)
def validate_ingredient_mappings(
    req: MappingValidateRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> IngredientMappingReport:
    repo = SQLiteVaultRepository(session)
    ds_id = req.dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    report = evaluate_external_mappings(
        session,
        kitchen_id=auth.kitchen_id,
        dataset_version_id=ds_id,
        candidates=req.candidates,
        reviewer_user_id=auth.user_id,
        persist=req.persist,
    )
    if req.persist:
        record_audit_event(
            session,
            action="inventory.mappings_validated",
            entity_type="dataset",
            entity_id=str(ds_id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={
                "total": report.total_records,
                "mapped": report.mapped_count,
                "rejected": report.rejected_count,
                "unit_errors": report.unit_conversion_errors,
            },
        )
        session.commit()
    return report


@router.post("/inventory/transactions/import", response_model=InventoryTransactionImportResponse)
async def import_inventory_transactions(
    transactions_file: UploadFile = File(...),
    dataset_version_id: Optional[UUID] = Form(None),
    data_classification: str = Form("synthetic"),
    authorization_confirmed: bool = Form(False),
    dry_run: bool = Form(False),
    source_name: str = Form("Unggahan Transaksi Inventaris Dapur", max_length=255),
    auth: AuthContext = Depends(require_active_stock_custodian),
    session: Session = Depends(_get_session),
) -> InventoryTransactionImportResponse:
    repo = SQLiteVaultRepository(session)
    ds_id = dataset_version_id or repo.get_active_dataset_id(auth.kitchen_id)
    try:
        repo.get_dataset_orm(ds_id, kitchen_id=auth.kitchen_id)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    raw_bytes = await transactions_file.read(MAX_CSV_BYTES + 1)
    if len(raw_bytes) > MAX_CSV_BYTES:
        raise HTTPException(status_code=422, detail="Ukuran file CSV transaksi melebihi batas 2 MB.")
    try:
        csv_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="File CSV wajib berenkode UTF-8.") from exc

    try:
        result = import_inventory_transactions_csv(
            session,
            kitchen_id=auth.kitchen_id,
            dataset_version_id=ds_id,
            csv_text=csv_text,
            data_classification=data_classification,
            authorization_confirmed=authorization_confirmed,
            dry_run=dry_run,
            actor_user_id=auth.user_id,
            source_name=source_name.strip() or "Unggahan Transaksi Inventaris Dapur",
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not dry_run:
        record_audit_event(
            session,
            action="inventory.transactions_imported",
            entity_type="dataset",
            entity_id=str(ds_id),
            kitchen_id=auth.kitchen_id,
            actor_user_id=auth.user_id,
            actor_role=auth.role.value,
            metadata={
                "classification": data_classification,
                "applied": result.applied_count,
                "duplicates_skipped": result.duplicate_skipped_count,
                "quarantined": result.quarantined_count,
            },
        )
        session.commit()
    return result


@router.post("/inventory/adjustments", response_model=ManualStockAdjustmentResponse)
def api_record_manual_inventory_adjustment(
    req: ManualStockAdjustmentRequest,
    auth: AuthContext = Depends(require_active_stock_custodian),
    session: Session = Depends(_get_session),
) -> ManualStockAdjustmentResponse:
    """Single-item ledger update (receipt, consumption, damage, opname, correction) for the active stock custodian only."""
    return record_manual_inventory_adjustment(session, auth, req)


@router.get("/inventory/templates/{template_name}")
def download_inventory_template(
    template_name: str,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
) -> Response:
    _ = auth
    if template_name == "pilot-transactions":
        body = build_pilot_transactions_template_csv()
        filename = "gizioptima_pilot_inventory_transactions_template.csv"
    elif template_name == "market-references":
        body = build_market_reference_template_csv()
        filename = "gizioptima_indonesian_market_reference_template.csv"
    else:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' tidak ditemukan.")

    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/market-references", response_model=List[MarketPriceReferenceItem])
def api_list_market_references(
    canonical_ingredient_code: Optional[str] = None,
    region: Optional[str] = None,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> List[MarketPriceReferenceItem]:
    _ = auth
    return list_market_price_references(
        session,
        canonical_ingredient_code=canonical_ingredient_code,
        region=region,
    )


@router.post("/market-references/import", response_model=MarketReferenceImportResponse, status_code=201)
async def api_import_market_references(
    market_file: UploadFile = File(...),
    source_name: str = Form("Referensi Harga Pangan Resmi (Impor Manual)", max_length=255),
    price_provenance: PriceProvenanceEnum = Form(PriceProvenanceEnum.OFFICIAL_MARKET_REFERENCE),
    source_url: Optional[str] = Form(None, max_length=2048),
    auth: AuthContext = Depends(require_roles(RoleEnum.MENU_PLANNER)),
    session: Session = Depends(_get_session),
) -> MarketReferenceImportResponse:
    raw_bytes = await market_file.read(MAX_CSV_BYTES + 1)
    if len(raw_bytes) > MAX_CSV_BYTES:
        raise HTTPException(status_code=422, detail="Ukuran file CSV referensi pasar melebihi 2 MB.")
    try:
        csv_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="File CSV wajib berenkode UTF-8.") from exc

    try:
        res = import_market_price_references_csv(
            session,
            csv_text=csv_text,
            source_name=source_name.strip() or "Referensi Harga Pangan Resmi",
            price_provenance=price_provenance,
            source_url=source_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record_audit_event(
        session,
        action="market_references.imported",
        entity_type="market_reference",
        entity_id=res.source_name,
        kitchen_id=auth.kitchen_id,
        actor_user_id=auth.user_id,
        actor_role=auth.role.value,
        metadata={
            "imported_count": res.imported_count,
            "provenance": res.price_provenance.value,
        },
    )
    session.commit()
    return res
