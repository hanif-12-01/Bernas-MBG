from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from uuid import UUID

from app.domain.models.schemas import OptimizationRunResponse, SlotEnum, SolverStatusEnum
from app.recovery.schemas import (
    CandidatePlanSummary,
    CounterfactualBaselineSnapshot,
    DisruptionImpactReport,
    FairComparisonBundle,
    RecoveryModeEnum,
    SlotSwapDetail,
)


def _diff_slots(
    *,
    baseline_run: OptimizationRunResponse,
    candidate_run: OptimizationRunResponse,
    slot_reasons: Dict[Tuple[int, SlotEnum], List[str]],
) -> Tuple[List[SlotSwapDetail], int, int]:
    """Build explicit day/slot swap list between baseline menu and candidate menu."""
    base_map: Dict[int, Dict[SlotEnum, Tuple[UUID, str]]] = {
        d.day_index: {
            slot: (rid, d.recipe_names_by_slot.get(slot, str(rid)))
            for slot, rid in d.recipes_by_slot.items()
        }
        for d in baseline_run.days
    }
    changed: List[SlotSwapDetail] = []
    total_slots = 0
    for day in sorted(candidate_run.days, key=lambda x: x.day_index):
        orig_day = base_map.get(day.day_index, {})
        for slot in sorted(day.recipes_by_slot.keys(), key=lambda s: s.value):
            total_slots += 1
            new_rid = day.recipes_by_slot[slot]
            new_name = day.recipe_names_by_slot.get(slot, str(new_rid))
            orig_pair = orig_day.get(slot)
            if orig_pair is None or orig_pair[0] != new_rid:
                orig_rid, orig_name = orig_pair if orig_pair else (new_rid, "-")
                reasons = slot_reasons.get((day.day_index, slot), [])
                reason_text = (
                    "; ".join(reasons)
                    if reasons
                    else "Penyesuaian ulang untuk menjaga keseimbangan gizi, stok, dan anggaran."
                )
                changed.append(
                    SlotSwapDetail(
                        day_index=day.day_index,
                        slot=slot,
                        original_recipe_id=orig_rid,
                        original_recipe_name=orig_name,
                        new_recipe_id=new_rid,
                        new_recipe_name=new_name,
                        reason=reason_text,
                    )
                )
    unchanged = max(0, total_slots - len(changed))
    return changed, unchanged, total_slots


def build_candidate_summary(
    *,
    mode: RecoveryModeEnum,
    baseline_run: OptimizationRunResponse,
    candidate_run: OptimizationRunResponse,
    counterfactual: CounterfactualBaselineSnapshot,
    slot_reasons: Dict[Tuple[int, SlotEnum], List[str]],
    min_disruption_total_cost_idr: Optional[float] = None,
) -> CandidatePlanSummary:
    """Summarize candidate recovery run with fair delta comparisons."""
    feasible = (
        candidate_run.validation_passed
        and candidate_run.solver_status in {SolverStatusEnum.OPTIMAL, SolverStatusEnum.FEASIBLE}
        and candidate_run.objective_total_idr is not None
    )

    if not feasible:
        return CandidatePlanSummary(
            mode=mode,
            scenario_id=candidate_run.scenario_id,
            run_id=candidate_run.run_id,
            solver_status=candidate_run.solver_status,
            validation_passed=False,
            changed_slots_count=0,
            unchanged_slots_count=0,
            total_slots_count=sum(len(d.recipes_by_slot) for d in baseline_run.days),
            changed_slots=[],
            total_cost_idr=None,
            cost_per_serving_idr=None,
            days_count=candidate_run.days_count,
            servings_per_day=candidate_run.servings_per_day,
            total_servings=candidate_run.total_servings,
            total_menu_slots=candidate_run.total_menu_slots,
            cost_per_day_average_idr=None,
            delta_vs_original_historical_idr=None,
            delta_vs_original_at_new_conditions_idr=None,
            delta_vs_min_disruption_idr=None,
            constraint_diagnostics=list(candidate_run.constraint_diagnostics),
            warnings=list(candidate_run.warnings),
            run_detail=candidate_run,
        )

    changed_slots, unchanged_count, total_slots = _diff_slots(
        baseline_run=baseline_run,
        candidate_run=candidate_run,
        slot_reasons=slot_reasons,
    )
    cand_total = round(float(candidate_run.objective_total_idr), 2)
    cand_per_serving = (
        round(float(candidate_run.cost_per_serving_average_idr), 2)
        if candidate_run.cost_per_serving_average_idr is not None
        else None
    )
    cand_per_day = (
        round(float(candidate_run.cost_per_day_average_idr), 2)
        if candidate_run.cost_per_day_average_idr is not None
        else (
            round(cand_total / max(1, len(candidate_run.days)), 2)
            if candidate_run.days
            else None
        )
    )

    delta_historical = (
        round(cand_total - float(baseline_run.objective_total_idr), 2)
        if baseline_run.objective_total_idr is not None
        else None
    )
    delta_at_new = (
        round(cand_total - float(counterfactual.total_cost_idr), 2)
        if counterfactual.feasible and counterfactual.total_cost_idr is not None
        else None
    )
    delta_vs_min_disruption = (
        round(cand_total - float(min_disruption_total_cost_idr), 2)
        if mode == RecoveryModeEnum.MIN_COST and min_disruption_total_cost_idr is not None
        else None
    )

    return CandidatePlanSummary(
        mode=mode,
        scenario_id=candidate_run.scenario_id,
        run_id=candidate_run.run_id,
        solver_status=candidate_run.solver_status,
        validation_passed=True,
        changed_slots_count=len(changed_slots),
        unchanged_slots_count=unchanged_count,
        total_slots_count=total_slots,
        changed_slots=changed_slots,
        total_cost_idr=cand_total,
        cost_per_serving_idr=cand_per_serving,
        days_count=candidate_run.days_count,
        servings_per_day=candidate_run.servings_per_day,
        total_servings=candidate_run.total_servings,
        total_menu_slots=candidate_run.total_menu_slots or total_slots,
        cost_per_day_average_idr=cand_per_day,
        delta_vs_original_historical_idr=delta_historical,
        delta_vs_original_at_new_conditions_idr=delta_at_new,
        delta_vs_min_disruption_idr=delta_vs_min_disruption,
        constraint_diagnostics=list(candidate_run.constraint_diagnostics),
        warnings=list(candidate_run.warnings),
        run_detail=candidate_run,
    )


def _menus_identical(a: Optional[OptimizationRunResponse], b: Optional[OptimizationRunResponse]) -> bool:
    if a is None or b is None or not a.validation_passed or not b.validation_passed:
        return False
    if len(a.days) != len(b.days):
        return False
    a_sig = [
        (d.day_index, sorted((s.value, str(rid)) for s, rid in d.recipes_by_slot.items()))
        for d in sorted(a.days, key=lambda x: x.day_index)
    ]
    b_sig = [
        (d.day_index, sorted((s.value, str(rid)) for s, rid in d.recipes_by_slot.items()))
        for d in sorted(b.days, key=lambda x: x.day_index)
    ]
    return a_sig == b_sig


def build_fair_comparison_bundle(
    *,
    baseline_run: OptimizationRunResponse,
    impact: DisruptionImpactReport,
    counterfactual: CounterfactualBaselineSnapshot,
    min_disruption: CandidatePlanSummary,
    min_cost: CandidatePlanSummary,
    prices_or_servings_changed: bool,
) -> FairComparisonBundle:
    """Build 4-way fair comparison never claiming fake savings across infeasible plans or old prices."""
    hist_days = baseline_run.days_count or len(baseline_run.days) or impact.days
    hist_total = baseline_run.objective_total_idr
    hist_daily = (
        baseline_run.cost_per_day_average_idr
        if baseline_run.cost_per_day_average_idr is not None
        else (round(float(hist_total) / max(1, hist_days), 2) if hist_total is not None and hist_days else None)
    )
    historical = CounterfactualBaselineSnapshot(
        label="Menu Asli pada Kondisi Lama (Konteks Historis)",
        feasible=baseline_run.validation_passed,
        total_cost_idr=hist_total,
        cost_per_serving_idr=baseline_run.cost_per_serving_average_idr,
        days_count=hist_days,
        servings_per_day=baseline_run.servings_per_day or impact.baseline_servings_per_day,
        total_servings=baseline_run.total_servings or (hist_days * impact.baseline_servings_per_day),
        cost_per_day_average_idr=hist_daily,
        notes=(
            "Biaya rencana saat disetujui sebelum gangguan terjadi. Hanya untuk referensi historis."
        ),
    )

    identical_candidates = _menus_identical(min_disruption.run_detail, min_cost.run_detail)

    # STRICT GUARDRAIL: never report cost savings if original counterfactual under NEW conditions
    # is infeasible OR if comparison is across mismatched historical prices/servings.
    cost_savings_claimed: Optional[float] = None
    same_valid = counterfactual.feasible and (min_disruption.validation_passed or min_cost.validation_passed)
    if same_valid and counterfactual.total_cost_idr is not None:
        best_valid_costs = [
            c.total_cost_idr
            for c in (min_disruption, min_cost)
            if c.validation_passed and c.total_cost_idr is not None
        ]
        if best_valid_costs:
            best_cost = min(best_valid_costs)
            diff = round(float(counterfactual.total_cost_idr) - float(best_cost), 2)
            if diff > 0:
                cost_savings_claimed = diff

    savings_min_cost_over_min_disruption: Optional[float] = None
    extra_slots: Optional[int] = None
    if (
        min_disruption.validation_passed
        and min_cost.validation_passed
        and min_disruption.total_cost_idr is not None
        and min_cost.total_cost_idr is not None
    ):
        savings_min_cost_over_min_disruption = round(
            float(min_disruption.total_cost_idr) - float(min_cost.total_cost_idr), 2
        )
        extra_slots = min_cost.changed_slots_count - min_disruption.changed_slots_count

    if not counterfactual.feasible:
        notice = (
            "Menu asli TIDAK LAYAK pada kondisi terbaru (melanggar ketersediaan stok/anggaran/gizi), "
            "sehingga selisih biaya terhadap menu asli tidak dihitung sebagai penghematan. "
            "Perbandingan biaya yang adil hanya berlaku antara Alternatif A (Minim Perubahan) dan Alternatif B (Biaya Minimum) pada kondisi terbaru yang sama."
        )
    elif prices_or_servings_changed:
        notice = (
            "Perbandingan selisih biaya dihitung terhadap menu asli yang dievaluasi ulang pada harga dan jumlah porsi TERBARU (bukan harga lama)."
        )
    else:
        notice = "Seluruh rencana dibandingkan pada harga, stok terverifikasi, dan target porsi yang sama."

    if identical_candidates and min_disruption.validation_passed:
        notice += " Alternatif Minim Perubahan dan Biaya Minimum menghasilkan susunan resep yang identik."

    return FairComparisonBundle(
        original_historical=historical,
        original_under_new_conditions=counterfactual,
        same_conditions_comparison_valid=same_valid,
        historical_price_comparison_allowed=False,
        cost_savings_claimed_idr=cost_savings_claimed,
        comparison_notice=notice,
        min_disruption_vs_min_cost_identical=identical_candidates,
        extra_slots_changed_for_min_cost=extra_slots,
        savings_by_choosing_min_cost_over_min_disruption_idr=savings_min_cost_over_min_disruption,
    )
