from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    IngredientORM,
    InventoryMovementORM,
    MenuReviewRecordORM,
    NutritionTargetORM,
    OperationalPlanAssignmentORM,
    OperationalPlanServiceDateORM,
    OptimizationRunORM,
    QCInspectionORM,
    RecipeVariantORM,
    RunAssignmentORM,
    RunMaterialUsageORM,
    ScenarioORM,
    StockReservationORM,
)
from app.inventory.service import InventoryAvailabilitySummary, compute_usable_inventory
from app.inventory.timezone_utils import jakarta_today, to_jakarta_date


def _service_dt(d: date) -> datetime:
    """Canonical production datetime matching operations/service.py & compute_usable_inventory."""
    return datetime(d.year, d.month, d.day, 8, 0, tzinfo=timezone.utc)


def default_weekdays(start: date, count: int) -> List[date]:
    """Generate `count` consecutive weekdays (Mon-Fri) starting on or after `start`."""
    days_out: List[date] = []
    curr = start
    include_weekends = count > 5
    while len(days_out) < max(1, count):
        if include_weekends or curr.weekday() < 5:
            days_out.append(curr)
        curr += timedelta(days=1)
    return days_out


def normalize_service_dates(
    production_date: Optional[datetime],
    days: int,
    explicit_dates: Optional[Sequence[date]] = None,
) -> List[date]:
    """Resolve ordered, duplicate-free service dates for a scenario or operational plan."""
    if explicit_dates:
        parsed: List[date] = []
        for item in explicit_dates:
            if isinstance(item, date) and not isinstance(item, datetime):
                parsed.append(item)
            elif isinstance(item, datetime):
                parsed.append(item.date())
            else:
                parsed.append(date.fromisoformat(str(item)[:10]))
        if not (1 <= len(parsed) <= 14):
            raise ValueError("service_dates harus berisi antara 1 hingga 14 tanggal pelayanan.")
        if len(set(parsed)) != len(parsed):
            raise ValueError("service_dates tidak boleh mengandung tanggal duplikat.")
        return sorted(parsed)

    if production_date is not None:
        start_d = (
            production_date.date()
            if isinstance(production_date, datetime)
            else production_date
        )
        return default_weekdays(start_d, int(days or 5))

    return []


def extract_scenario_service_dates(sc: ScenarioORM) -> List[date]:
    raw = getattr(sc, "service_dates_json", None)
    if isinstance(raw, list) and raw:
        try:
            return normalize_service_dates(
                sc.production_date,
                sc.days,
                [date.fromisoformat(str(x)[:10]) for x in raw],
            )
        except ValueError:
            pass
    return normalize_service_dates(sc.production_date, sc.days)


def extract_assignment_service_dates(assign: OperationalPlanAssignmentORM) -> List[date]:
    raw = getattr(assign, "service_dates_json", None)
    if isinstance(raw, list) and raw:
        try:
            return normalize_service_dates(
                _service_dt(assign.production_date),
                assign.horizon_days,
                [date.fromisoformat(str(x)[:10]) for x in raw],
            )
        except ValueError:
            pass
    return default_weekdays(assign.production_date, int(assign.horizon_days or 5))


def suggest_next_week_service_dates(
    previous_dates: Sequence[date],
    days: int = 5,
    *,
    reference_today: Optional[date] = None,
) -> List[date]:
    """Suggest next period's service dates starting the next weekday strictly after previous period."""
    if previous_dates:
        curr = max(previous_dates) + timedelta(days=1)
        while curr.weekday() >= 5:
            curr += timedelta(days=1)
        return default_weekdays(curr, days)

    base = reference_today or jakarta_today()
    days_until_mon = (7 - base.weekday()) % 7
    if days_until_mon == 0:
        days_until_mon = 7
    return default_weekdays(base + timedelta(days=days_until_mon), days)


def derive_period_phase(
    service_dates: Sequence[date],
    *,
    today: Optional[date] = None,
) -> Optional[str]:
    """Derive IN_PROGRESS / UPCOMING / COMPLETED purely from service dates (no extra DB status)."""
    if not service_dates:
        return None
    ref = today or jakarta_today()
    start_d = min(service_dates)
    end_d = max(service_dates)
    if end_d < ref:
        return "COMPLETED"
    if start_d <= ref <= end_d:
        return "IN_PROGRESS"
    return "UPCOMING"


@dataclass
class HistoricalMenuDay:
    service_date: date
    source_type: str  # VERIFIED_EXECUTION | OPERATIONAL_PLAN
    run_id: str
    plan_title: str
    recipes_by_slot: Dict[str, str]  # slot -> recipe_id
    recipe_codes_by_slot: Dict[str, str]  # slot -> recipe_code
    recipe_names_by_slot: Dict[str, str]  # slot -> recipe_name
    families_by_slot: Dict[str, str]  # slot -> recipe family


@dataclass
class MenuHistoryContext:
    window_days: int
    days: List[HistoricalMenuDay] = field(default_factory=list)
    primary_source_type: str = "NONE"  # VERIFIED_EXECUTION | MIXED | OPERATIONAL_PLAN | NONE
    source_notice: str = "Belum ada histori menu periode sebelumnya untuk dibandingkan."
    previous_run_id: Optional[str] = None
    previous_plan_title: Optional[str] = None
    previous_cost_per_serving_idr: Optional[float] = None

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "window_days": self.window_days,
            "history_days_count": len(self.days),
            "primary_source_type": self.primary_source_type,
            "source_notice": self.source_notice,
            "previous_run_id": self.previous_run_id,
            "previous_plan_title": self.previous_plan_title,
            "previous_cost_per_serving_idr": self.previous_cost_per_serving_idr,
            "previous_period_dates": [d.service_date.isoformat() for d in self.days],
            "history_days": [
                {
                    "service_date": d.service_date.isoformat(),
                    "source_type": d.source_type,
                    "plan_title": d.plan_title,
                    "recipe_names_by_slot": d.recipe_names_by_slot,
                    "families_by_slot": d.families_by_slot,
                }
                for d in self.days
            ],
        }


def collect_previous_menu_history(
    session: Session,
    *,
    kitchen_id: UUID,
    before_date: date,
    meal_type: str,
    target_cohort: str,
    batch_label: str = "DEFAULT",
    window_days: int = 5,
    fallback_source_run_id: Optional[UUID] = None,
) -> MenuHistoryContext:
    """Collect up to `window_days` prior service days using strict trust priority:
    1. Verified execution (submitted/reviewed QC inspection linked to that operational run/day).
    2. Effective operational plan covering that date (including post-Recovery active replacements,
       never superseded old versions or unapproved drafts).
    """
    norm_meal = (meal_type or "lunch").strip().lower() or "lunch"
    norm_cohort = (target_cohort or "DEFAULT").strip() or "DEFAULT"
    norm_batch = (batch_label or "DEFAULT").strip() or "DEFAULT"

    # Find effective (ACTIVE or ON_HOLD) operational plan service dates strictly before `before_date`
    rows = session.execute(
        select(OperationalPlanServiceDateORM, OperationalPlanAssignmentORM)
        .join(
            OperationalPlanAssignmentORM,
            OperationalPlanServiceDateORM.assignment_id == OperationalPlanAssignmentORM.id,
        )
        .where(
            OperationalPlanServiceDateORM.kitchen_id == str(kitchen_id),
            OperationalPlanServiceDateORM.service_date < before_date,
            OperationalPlanServiceDateORM.meal_type == norm_meal,
            OperationalPlanServiceDateORM.target_cohort == norm_cohort,
            OperationalPlanAssignmentORM.operational_status.in_(["ACTIVE", "ON_HOLD"]),
        )
        .order_by(
            OperationalPlanServiceDateORM.service_date.desc(),
            OperationalPlanAssignmentORM.activated_at.desc(),
        )
    ).all()

    # Prefer matching batch_label, fall back to any batch on same meal/cohort if none match
    matched_by_date: Dict[date, Tuple[OperationalPlanServiceDateORM, OperationalPlanAssignmentORM]] = {}
    for sd_row, assign_row in rows:
        if sd_row.batch_label != norm_batch:
            continue
        if sd_row.service_date not in matched_by_date:
            matched_by_date[sd_row.service_date] = (sd_row, assign_row)
    if not matched_by_date:
        for sd_row, assign_row in rows:
            if sd_row.service_date not in matched_by_date:
                matched_by_date[sd_row.service_date] = (sd_row, assign_row)

    selected_dates = sorted(matched_by_date.keys())[-window_days:]

    history_days: List[HistoricalMenuDay] = []
    run_cache: Dict[str, OptimizationRunORM] = {}
    review_cache: Dict[str, Optional[MenuReviewRecordORM]] = {}
    assign_map_cache: Dict[str, Dict[int, List[RunAssignmentORM]]] = {}
    recipe_cache: Dict[str, Optional[RecipeVariantORM]] = {}
    qc_verified_pairs: Set[Tuple[str, int]] = set()

    candidate_run_ids = {matched_by_date[d][1].run_id for d in selected_dates}
    if fallback_source_run_id is not None:
        candidate_run_ids.add(str(fallback_source_run_id))

    if candidate_run_ids:
        insp_rows = session.execute(
            select(QCInspectionORM.run_id, QCInspectionORM.day_index).where(
                QCInspectionORM.kitchen_id == str(kitchen_id),
                QCInspectionORM.run_id.in_(candidate_run_ids),
                QCInspectionORM.status.in_(["SUBMITTED", "REVIEWED"]),
            )
        ).all()
        qc_verified_pairs = {(r[0], int(r[1])) for r in insp_rows}

    def _load_run_assignments(rid: str) -> Dict[int, List[RunAssignmentORM]]:
        if rid not in assign_map_cache:
            items = list(
                session.execute(
                    select(RunAssignmentORM).where(RunAssignmentORM.run_id == rid)
                )
                .scalars()
                .all()
            )
            by_day: Dict[int, List[RunAssignmentORM]] = {}
            for item in items:
                by_day.setdefault(int(item.day_index), []).append(item)
            assign_map_cache[rid] = by_day
        return assign_map_cache[rid]

    def _load_recipe(recipe_id: str) -> Optional[RecipeVariantORM]:
        if recipe_id not in recipe_cache:
            recipe_cache[recipe_id] = session.get(RecipeVariantORM, recipe_id)
        return recipe_cache[recipe_id]

    for svc_d in selected_dates:
        sd_row, assign_row = matched_by_date[svc_d]
        rid = assign_row.run_id
        if rid not in run_cache:
            r_obj = session.get(OptimizationRunORM, rid)
            if r_obj is not None:
                run_cache[rid] = r_obj
        if assign_row.menu_review_id not in review_cache:
            review_cache[assign_row.menu_review_id] = session.get(
                MenuReviewRecordORM, assign_row.menu_review_id
            )
        rev = review_cache[assign_row.menu_review_id]
        plan_title = rev.title if rev else f"Rencana {rid[:8]}"

        day_assigns = _load_run_assignments(rid).get(int(sd_row.day_index), [])
        if not day_assigns:
            continue

        rec_by_slot: Dict[str, str] = {}
        codes_by_slot: Dict[str, str] = {}
        names_by_slot: Dict[str, str] = {}
        fam_by_slot: Dict[str, str] = {}
        for a in day_assigns:
            rec_obj = _load_recipe(a.recipe_id)
            rec_by_slot[a.slot] = a.recipe_id
            codes_by_slot[a.slot] = rec_obj.code if rec_obj else a.recipe_id[:8]
            names_by_slot[a.slot] = a.recipe_name
            fam_by_slot[a.slot] = rec_obj.family if rec_obj else "unknown"

        src_type = (
            "VERIFIED_EXECUTION"
            if (rid, int(sd_row.day_index)) in qc_verified_pairs
            else "OPERATIONAL_PLAN"
        )
        history_days.append(
            HistoricalMenuDay(
                service_date=svc_d,
                source_type=src_type,
                run_id=rid,
                plan_title=plan_title,
                recipes_by_slot=rec_by_slot,
                recipe_codes_by_slot=codes_by_slot,
                recipe_names_by_slot=names_by_slot,
                families_by_slot=fam_by_slot,
            )
        )

    # Fallback: if no operational plan rows exist yet before `before_date` but caller explicitly
    # continued from a specific `fallback_source_run_id`, load its days as OPERATIONAL_PLAN context.
    if not history_days and fallback_source_run_id is not None:
        rid = str(fallback_source_run_id)
        r_obj = session.get(OptimizationRunORM, rid)
        if r_obj is not None:
            run_cache[rid] = r_obj
            sc_obj = session.get(ScenarioORM, r_obj.scenario_id)
            sc_dates = extract_scenario_service_dates(sc_obj) if sc_obj else []
            by_day = _load_run_assignments(rid)
            ordered_day_indices = sorted(by_day.keys())[-window_days:]
            for idx_pos, d_idx in enumerate(ordered_day_indices):
                svc_d = (
                    sc_dates[d_idx - 1]
                    if 0 <= d_idx - 1 < len(sc_dates)
                    else before_date - timedelta(days=len(ordered_day_indices) - idx_pos)
                )
                rec_by_slot = {}
                codes_by_slot = {}
                names_by_slot = {}
                fam_by_slot = {}
                for a in by_day[d_idx]:
                    rec_obj = _load_recipe(a.recipe_id)
                    rec_by_slot[a.slot] = a.recipe_id
                    codes_by_slot[a.slot] = rec_obj.code if rec_obj else a.recipe_id[:8]
                    names_by_slot[a.slot] = a.recipe_name
                    fam_by_slot[a.slot] = rec_obj.family if rec_obj else "unknown"
                src_type = (
                    "VERIFIED_EXECUTION"
                    if (rid, int(d_idx)) in qc_verified_pairs
                    else "OPERATIONAL_PLAN"
                )
                history_days.append(
                    HistoricalMenuDay(
                        service_date=svc_d,
                        source_type=src_type,
                        run_id=rid,
                        plan_title=sc_obj.name if sc_obj else f"Rencana {rid[:8]}",
                        recipes_by_slot=rec_by_slot,
                        recipe_codes_by_slot=codes_by_slot,
                        recipe_names_by_slot=names_by_slot,
                        families_by_slot=fam_by_slot,
                    )
                )

    if not history_days:
        return MenuHistoryContext(window_days=window_days)

    source_types = {d.source_type for d in history_days}
    if source_types == {"VERIFIED_EXECUTION"}:
        primary_source = "VERIFIED_EXECUTION"
        notice = (
            f"Histori {len(history_days)} hari pelayanan sebelumnya bersumber dari catatan pemeriksaan pelaksanaan yang terverifikasi."
        )
    elif source_types == {"OPERATIONAL_PLAN"}:
        primary_source = "OPERATIONAL_PLAN"
        notice = (
            f"Histori {len(history_days)} hari pelayanan sebelumnya bersumber dari rencana operasional yang diberlakukan "
            f"(termasuk hasil pemulihan bila ada), bukan bukti fisik makanan benar-benar tersaji."
        )
    else:
        primary_source = "MIXED"
        notice = (
            f"Histori {len(history_days)} hari pelayanan menggabungkan catatan pelaksanaan terverifikasi dan rencana operasional yang diberlakukan "
            f"(hari tanpa pemeriksaan fisik mencerminkan rencana, bukan bukti sajian)."
        )

    latest_day = history_days[-1]
    prev_run = run_cache.get(latest_day.run_id)
    prev_cost = (
        float(prev_run.cost_per_serving_average_idr)
        if prev_run and prev_run.cost_per_serving_average_idr is not None
        else None
    )

    return MenuHistoryContext(
        window_days=window_days,
        days=history_days,
        primary_source_type=primary_source,
        source_notice=notice,
        previous_run_id=latest_day.run_id,
        previous_plan_title=latest_day.plan_title,
        previous_cost_per_serving_idr=prev_cost,
    )


@dataclass
class CrossPeriodStockContext:
    base_availability: InventoryAvailabilitySummary
    effective_stock: Dict[str, float]
    usable_stock_by_day: Dict[int, Dict[str, float]]  # day_index (1..T) -> code -> usable g
    committed_other_plans_raw_g: Dict[str, float]
    stock_confirmation_required: bool = False
    stock_confirmation_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


def compute_cross_period_stock_context(
    session: Session,
    *,
    kitchen_id: UUID,
    dataset_version_id: UUID,
    service_dates: Sequence[date],
    exclude_assignment_ids: Optional[Set[str]] = None,
    reference_today: Optional[date] = None,
) -> CrossPeriodStockContext:
    """Compute exact per-date usable stock (respecting expiry, safety hold, and uncommitted demand
    of other ACTIVE/ON_HOLD plans without double-subtracting reservations or recorded consumption).
    """
    today_d = reference_today or jakarta_today()
    excl = exclude_assignment_ids or set()
    dates_list = list(service_dates) if service_dates else [today_d]

    first_avail = compute_usable_inventory(
        session,
        kitchen_id=kitchen_id,
        dataset_version_id=dataset_version_id,
        production_date=_service_dt(dates_list[0]),
    )

    # Compute per-service-date usable stock (exact expiry evaluation on each service date)
    per_day_raw: Dict[int, Dict[str, float]] = {}
    warnings: List[str] = []
    has_unverified_or_unknown = False

    for idx, svc_d in enumerate(dates_list, start=1):
        avail = (
            first_avail
            if idx == 1
            else compute_usable_inventory(
                session,
                kitchen_id=kitchen_id,
                dataset_version_id=dataset_version_id,
                production_date=_service_dt(svc_d),
            )
        )
        day_map: Dict[str, float] = {}
        for item in avail.items:
            if item.usable_raw_g is not None:
                day_map[item.ingredient_code] = max(0.0, float(item.usable_raw_g))
            else:
                has_unverified_or_unknown = True
        per_day_raw[idx] = day_map

    # Identify OTHER effective (ACTIVE) operational plans on the same kitchen & dataset
    # whose service period has not finished yet. ON_HOLD plans are halted pending replacement
    # (their physical StockReservationORM rows, if any, are already deducted by compute_usable_inventory).
    other_plans = list(
        session.execute(
            select(OperationalPlanAssignmentORM).where(
                OperationalPlanAssignmentORM.kitchen_id == str(kitchen_id),
                OperationalPlanAssignmentORM.dataset_version_id == str(dataset_version_id),
                OperationalPlanAssignmentORM.operational_status == "ACTIVE",
            )
        )
        .scalars()
        .all()
    )

    ing_rows = list(
        session.execute(
            select(IngredientORM).where(
                IngredientORM.dataset_version_id == str(dataset_version_id)
            )
        )
        .scalars()
        .all()
    )
    code_by_ing_id = {i.id: i.code for i in ing_rows}

    # Fetch recorded PRODUCTION_CONSUMPTION movements (already deducted in lot recorded_raw_g)
    # and active StockReservationORM (already deducted in compute_usable_inventory)
    all_consumptions = list(
        session.execute(
            select(InventoryMovementORM).where(
                InventoryMovementORM.kitchen_id == str(kitchen_id),
                InventoryMovementORM.dataset_version_id == str(dataset_version_id),
                InventoryMovementORM.movement_type == "PRODUCTION_CONSUMPTION",
                InventoryMovementORM.quarantined.is_(False),
            )
        )
        .scalars()
        .all()
    )

    committed_extra: Dict[str, float] = {}
    unfinished_plan_titles: List[str] = []

    for plan in other_plans:
        if plan.id in excl:
            continue
        p_dates = extract_assignment_service_dates(plan)
        p_start = min(p_dates)
        p_end = max(p_dates)
        # Skip plans that have completely finished before BOTH today and target period start
        # (unless they overlap/precede an unfinished window).
        if p_end < today_d and p_end < dates_list[0]:
            continue

        usages = list(
            session.execute(
                select(RunMaterialUsageORM).where(RunMaterialUsageORM.run_id == plan.run_id)
            )
            .scalars()
            .all()
        )
        if not usages:
            continue

        # Active reservations linked to this plan's menu_review_id (already deducted by compute_usable_inventory)
        plan_res_rows = list(
            session.execute(
                select(StockReservationORM).where(
                    StockReservationORM.kitchen_id == str(kitchen_id),
                    StockReservationORM.dataset_version_id == str(dataset_version_id),
                    StockReservationORM.menu_review_id == plan.menu_review_id,
                    StockReservationORM.status == "ACTIVE",
                )
            )
            .scalars()
            .all()
        )
        reserved_by_code: Dict[str, float] = {}
        for r in plan_res_rows:
            code = code_by_ing_id.get(r.ingredient_id)
            if code:
                reserved_by_code[code] = reserved_by_code.get(code, 0.0) + max(0.0, float(r.reserved_raw_g))

        # Recorded actual consumption during this plan's service window (already deducted from lot recorded_raw_g)
        consumed_by_code: Dict[str, float] = {}
        for mv in all_consumptions:
            mv_date = to_jakarta_date(mv.event_at)
            if p_start <= mv_date <= p_end:
                code = code_by_ing_id.get(mv.ingredient_id)
                if code:
                    consumed_by_code[code] = consumed_by_code.get(code, 0.0) + abs(float(mv.quantity_delta_raw_g))

        plan_has_unconfirmed_commitment = False
        for u in usages:
            planned_g = max(0.0, float(u.used_raw_g))
            already_accounted_g = reserved_by_code.get(u.ingredient_code, 0.0) + consumed_by_code.get(
                u.ingredient_code, 0.0
            )
            extra_g = max(0.0, planned_g - already_accounted_g)
            if extra_g > 1e-6:
                committed_extra[u.ingredient_code] = committed_extra.get(u.ingredient_code, 0.0) + extra_g
                plan_has_unconfirmed_commitment = True

        # If this other active/held plan covers dates on/after today and hasn't recorded full consumption
        if plan_has_unconfirmed_commitment and p_end >= today_d:
            rev = session.get(MenuReviewRecordORM, plan.menu_review_id)
            title = rev.title if rev else f"Rencana {plan.run_id[:8]}"
            unfinished_plan_titles.append(
                f"'{title}' ({p_start.isoformat()} s.d. {p_end.isoformat()})"
            )

    # Apply extra cross-plan commitments cleanly & enforce monotonic non-increasing suffix bounds
    usable_by_day: Dict[int, Dict[str, float]] = {}
    for idx in range(1, len(dates_list) + 1):
        adjusted: Dict[str, float] = {}
        for code, val in per_day_raw[idx].items():
            net_val = max(0.0, val - committed_extra.get(code, 0.0))
            if idx > 1 and code in usable_by_day[idx - 1]:
                net_val = min(net_val, usable_by_day[idx - 1][code])
            adjusted[code] = round(net_val, 4)
        usable_by_day[idx] = adjusted

    effective_stock = dict(usable_by_day[1]) if usable_by_day else {}

    stock_confirmation_required = False
    reasons: List[str] = []
    if unfinished_plan_titles:
        stock_confirmation_required = True
        reasons.append(
            "Rencana periode berjalan/aktif lain belum selesai dan konsumsi aktualnya belum tercatat penuh ("
            + ", ".join(unfinished_plan_titles)
            + "); sisa stok minggu berikutnya diperhitungkan secara konservatif namun tetap perlu dikonfirmasi sebelum aktivasi."
        )
    if has_unverified_or_unknown:
        stock_confirmation_required = True
        reasons.append(
            "Sebagian bahan memiliki status stok belum terverifikasi/UNKNOWN sehingga ketersediaan stok perlu dikonfirmasi sebelum aktivasi."
        )

    confirmation_reason = " ".join(reasons) if reasons else None
    if confirmation_reason:
        warnings.append(f"PERLU_KONFIRMASI_STOK: {confirmation_reason}")

    return CrossPeriodStockContext(
        base_availability=first_avail,
        effective_stock=effective_stock,
        usable_stock_by_day=usable_by_day,
        committed_other_plans_raw_g=committed_extra,
        stock_confirmation_required=stock_confirmation_required,
        stock_confirmation_reason=confirmation_reason,
        warnings=warnings,
    )


def build_cross_week_comparison(
    history: MenuHistoryContext,
    new_days: List[Any],  # List[DayPlan]
    recipes_by_id: Dict[UUID, Any],
    new_cost_per_serving_idr: Optional[float],
) -> Dict[str, Any]:
    """Build deterministic boundary comparison between previous week history and new week draft."""
    summary = history.to_summary_dict()
    if not history.days or not new_days:
        summary["comparison"] = None
        return summary

    prev_recipe_ids: Set[str] = set()
    prev_last_day_recipe_ids: Set[str] = set()
    prev_family_counts: Dict[str, int] = {}
    for idx, hd in enumerate(history.days):
        for _slot, rid in hd.recipes_by_slot.items():
            prev_recipe_ids.add(rid)
            if idx == len(history.days) - 1:
                prev_last_day_recipe_ids.add(rid)
        for _slot, fam in hd.families_by_slot.items():
            prev_family_counts[fam] = prev_family_counts.get(fam, 0) + 1

    new_day1_recipes = {str(rid) for rid in new_days[0].recipes_by_slot.values()}
    boundary_immediate_repeats = sorted(prev_last_day_recipe_ids & new_day1_recipes)

    new_all_recipes = {
        str(rid) for dp in new_days for rid in dp.recipes_by_slot.values()
    }
    repeated_from_prev_week = sorted(prev_recipe_ids & new_all_recipes)
    fresh_recipes_count = len(new_all_recipes - prev_recipe_ids)

    cost_delta = (
        round(new_cost_per_serving_idr - history.previous_cost_per_serving_idr, 2)
        if (
            new_cost_per_serving_idr is not None
            and history.previous_cost_per_serving_idr is not None
        )
        else None
    )

    # Check sliding 5-day boundary windows for family repeat transparency
    combined_families: List[List[str]] = [
        list(hd.families_by_slot.values()) for hd in history.days
    ]
    for dp in new_days:
        fams: List[str] = []
        for rid in dp.recipes_by_slot.values():
            rec = recipes_by_id.get(rid)
            if rec is not None:
                fams.append(rec.family)
        combined_families.append(fams)

    hist_len = len(history.days)
    window_size = max(1, history.window_days)
    max_boundary_family_repeat = 0
    for end_idx in range(hist_len, min(len(combined_families), hist_len + window_size - 1)):
        start_idx = max(0, end_idx - window_size + 1)
        counts: Dict[str, int] = {}
        for day_fams in combined_families[start_idx : end_idx + 1]:
            for f in day_fams:
                counts[f] = counts.get(f, 0) + 1
                if counts[f] > max_boundary_family_repeat:
                    max_boundary_family_repeat = counts[f]

    summary["comparison"] = {
        "previous_unique_recipes_count": len(prev_recipe_ids),
        "new_unique_recipes_count": len(new_all_recipes),
        "fresh_recipes_count": fresh_recipes_count,
        "repeated_recipes_from_previous_week_count": len(repeated_from_prev_week),
        "boundary_day5_to_day1_repeat_count": len(boundary_immediate_repeats),
        "max_boundary_5day_family_repeat": max_boundary_family_repeat,
        "previous_cost_per_serving_idr": history.previous_cost_per_serving_idr,
        "new_cost_per_serving_idr": new_cost_per_serving_idr,
        "cost_delta_per_serving_idr": cost_delta,
    }
    return summary


# =====================================================================
# API Schemas for "Siapkan Menu Minggu Berikutnya"
# =====================================================================


class NextWeekDefaultsResponse(BaseModel):
    source_run_id: Optional[UUID] = None
    source_assignment_id: Optional[UUID] = None
    source_plan_title: Optional[str] = None
    source_service_dates: List[date] = Field(default_factory=list)
    suggested_name: str
    suggested_service_dates: List[date] = Field(default_factory=list)
    dataset_version_id: UUID
    nutrition_target_id: UUID
    meal_type: str = "lunch"
    servings_per_day: int = 100
    days: int = 5
    budget_idr_per_serving: float = 12000.0
    max_repeat_per_family: int = 2
    excluded_allergens: List[str] = Field(default_factory=list)
    history_source_type: str = "NONE"
    history_source_notice: str = ""
    stock_confirmation_required: bool = False
    stock_confirmation_reason: Optional[str] = None


class PrepareNextWeekRequest(BaseModel):
    source_run_id: Optional[UUID] = None
    source_assignment_id: Optional[UUID] = None
    name: Optional[str] = Field(default=None, max_length=255)
    dataset_version_id: Optional[UUID] = None
    service_dates: Optional[List[date]] = None
    servings_per_day: Optional[int] = Field(default=None, ge=1, le=10000)
    budget_idr_per_serving: Optional[float] = Field(default=None, gt=0.0)
    max_repeat_per_family: Optional[int] = Field(default=None, ge=1, le=14)
    excluded_allergens: Optional[List[str]] = None
    planner_notes: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_dates(self) -> "PrepareNextWeekRequest":
        if self.service_dates is not None:
            if not (1 <= len(self.service_dates) <= 14):
                raise ValueError("service_dates harus berisi antara 1 hingga 14 tanggal pelayanan.")
            if len(set(self.service_dates)) != len(self.service_dates):
                raise ValueError("service_dates tidak boleh mengandung tanggal duplikat.")
            self.service_dates = sorted(self.service_dates)
        return self


class PrepareNextWeekResponse(BaseModel):
    scenario_id: UUID
    run_id: UUID
    menu_review_id: Optional[UUID] = None
    menu_review_status: Optional[str] = None
    service_dates: List[date] = Field(default_factory=list)
    solver_status: str
    validation_passed: bool
    stock_confirmation_required: bool = False
    stock_confirmation_reason: Optional[str] = None
    history_context: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
