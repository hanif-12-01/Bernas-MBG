from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_current_auth, get_db_session, require_roles
from app.auth.schemas import RoleEnum
from app.custodian.schemas import (
    AssignCustodianRequest,
    KitchenStockCustodianStatusResponse,
    RevokeCustodianRequest,
)
from app.custodian.service import (
    assign_stock_custodian,
    get_kitchen_custodian_status,
    revoke_stock_custodian,
)

router = APIRouter(prefix="/stock-custodian", tags=["stock-custodian"])


@router.get("", response_model=KitchenStockCustodianStatusResponse)
def api_get_stock_custodian_status(
    auth: AuthContext = Depends(get_current_auth),
    session: Session = Depends(get_db_session),
) -> KitchenStockCustodianStatusResponse:
    """Return active stock custodian (and candidates/history for Kitchen Manager)."""
    return get_kitchen_custodian_status(session, auth)


@router.post("/assign", response_model=KitchenStockCustodianStatusResponse)
def api_assign_stock_custodian(
    req: AssignCustodianRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> KitchenStockCustodianStatusResponse:
    """Delegate active stock-writer authority to exactly one QC_OFFICER in this kitchen."""
    return assign_stock_custodian(session, auth, req)


@router.post("/revoke", response_model=KitchenStockCustodianStatusResponse)
def api_revoke_stock_custodian(
    req: RevokeCustodianRequest,
    auth: AuthContext = Depends(require_roles(RoleEnum.KITCHEN_MANAGER)),
    session: Session = Depends(get_db_session),
) -> KitchenStockCustodianStatusResponse:
    """Revoke active stock custodian delegation so no stock mutation can happen until reassigned."""
    return revoke_stock_custodian(session, auth, req)
