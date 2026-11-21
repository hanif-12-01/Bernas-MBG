from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    AuthContext,
    get_db_session,
    require_active_stock_custodian,
    require_roles,
)
from app.auth.schemas import RoleEnum
from app.procurement.file_security import MAX_PROCUREMENT_EVIDENCE_BYTES
from app.procurement.schemas import (
    GoodsReceiptCreateRequest,
    GoodsReceiptResponse,
    PurchaseDocumentCreateRequest,
    PurchaseDocumentResponse,
    PurchaseDocumentReviewRequest,
)
from app.procurement.service import (
    create_goods_receipt,
    create_purchase_document,
    get_purchase_document,
    get_purchase_document_evidence_bytes,
    list_goods_receipts,
    list_purchase_documents,
    review_purchase_document,
    upload_purchase_document_evidence,
)

router = APIRouter(prefix="/procurement", tags=["procurement"])


@router.get("/documents", response_model=List[PurchaseDocumentResponse])
def api_list_purchase_documents(
    limit: int = 50,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> List[PurchaseDocumentResponse]:
    return list_purchase_documents(session, auth, limit=limit)


@router.post("/documents", response_model=PurchaseDocumentResponse, status_code=201)
def api_create_purchase_document(
    req: PurchaseDocumentCreateRequest,
    auth: AuthContext = Depends(require_active_stock_custodian),
    session: Session = Depends(get_db_session),
) -> PurchaseDocumentResponse:
    return create_purchase_document(session, auth, req)


@router.get("/documents/{document_id}", response_model=PurchaseDocumentResponse)
def api_get_purchase_document(
    document_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> PurchaseDocumentResponse:
    return get_purchase_document(session, auth, document_id)


@router.post("/documents/{document_id}/evidence", response_model=PurchaseDocumentResponse)
async def api_upload_purchase_document_evidence(
    document_id: UUID,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_active_stock_custodian),
    session: Session = Depends(get_db_session),
) -> PurchaseDocumentResponse:
    raw = await file.read(MAX_PROCUREMENT_EVIDENCE_BYTES + 1)
    if len(raw) > MAX_PROCUREMENT_EVIDENCE_BYTES:
        raise HTTPException(status_code=422, detail="Ukuran bukti pembelian melebihi 10 MB.")
    return upload_purchase_document_evidence(
        session, auth, document_id, raw, file.filename or "bukti_pembelian"
    )


@router.get("/documents/{document_id}/evidence")
def api_get_purchase_document_evidence(
    document_id: UUID,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> Response:
    raw, mime, _safe_name = get_purchase_document_evidence_bytes(session, auth, document_id)
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if mime == "application/pdf":
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return Response(content=raw, media_type=mime, headers=headers)


@router.patch("/documents/{document_id}/review", response_model=PurchaseDocumentResponse)
def api_review_purchase_document(
    document_id: UUID,
    req: PurchaseDocumentReviewRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> PurchaseDocumentResponse:
    return review_purchase_document(session, auth, document_id, req)


@router.get("/receipts", response_model=List[GoodsReceiptResponse])
def api_list_goods_receipts(
    limit: int = 50,
    auth: AuthContext = Depends(
        require_roles(RoleEnum.KITCHEN_MANAGER, RoleEnum.MENU_PLANNER, RoleEnum.QC_OFFICER)
    ),
    session: Session = Depends(get_db_session),
) -> List[GoodsReceiptResponse]:
    return list_goods_receipts(session, auth, limit=limit)


@router.post("/receipts", response_model=GoodsReceiptResponse, status_code=201)
def api_create_goods_receipt(
    req: GoodsReceiptCreateRequest,
    auth: AuthContext = Depends(require_active_stock_custodian),
    session: Session = Depends(get_db_session),
) -> GoodsReceiptResponse:
    return create_goods_receipt(session, auth, req)
