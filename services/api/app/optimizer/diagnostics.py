from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

import pulp
from pulp.constants import LpSolveStatus

from app.domain.models.schemas import (
    DiagnosticHint,
    Ingredient,
    NutritionTargetProfile,
    RecipeFeatures,
    RecipeVariant,
    Scenario,
)
from app.optimizer.model_builder import build_recipe_milp


def _is_feasible_under(
    scenario: Scenario,
    recipes: List[RecipeVariant],
    features_by_id: Dict[UUID, RecipeFeatures],
    target: NutritionTargetProfile,
    stock_raw_g: Dict[str, float],
    solver: pulp.LpSolver,
    ingredients_by_code: Optional[Dict[str, Ingredient]] = None,
) -> bool:
    try:
        built = build_recipe_milp(
            scenario,
            recipes,
            features_by_id,
            target,
            stock_raw_g,
            ingredients_by_code=ingredients_by_code,
        )
        stats = built.problem.solve(solver)
        status = getattr(stats, "status", stats)
        has_solution = bool(getattr(stats, "has_solution", False))
        return has_solution and status in {
            LpSolveStatus.Optimal,
            LpSolveStatus.GapLimit,
            LpSolveStatus.SolutionLimit,
        }
    except Exception:
        return False


def diagnose_infeasibility(
    scenario: Scenario,
    recipes: List[RecipeVariant],
    features_by_id: Dict[UUID, RecipeFeatures],
    target: NutritionTargetProfile,
    stock_raw_g: Dict[str, float],
    solver: pulp.LpSolver,
    ingredients_by_code: Optional[Dict[str, Ingredient]] = None,
) -> List[DiagnosticHint]:
    """Run isolated relaxation probes to identify candidate bottlenecks.

    NEVER returns relaxed solutions as valid menu assignments.
    """
    hints: List[DiagnosticHint] = []

    # 1. Relax budget
    relaxed_budget = scenario.model_copy(update={"budget_idr_per_serving": 1e9})
    if _is_feasible_under(
        relaxed_budget, recipes, features_by_id, target, stock_raw_g, solver, ingredients_by_code
    ):
        hints.append(
            DiagnosticHint(
                family="budget",
                message=(
                    f"Anggaran Rp{scenario.budget_idr_per_serving:,.0f}/porsi kemungkinan terlalu ketat "
                    "untuk kombinasi resep yang memenuhi seluruh target gizi dan stok."
                ),
            )
        )

    # 2. Relax stock
    unlimited_stock = {k: 1e12 for k in stock_raw_g}
    if _is_feasible_under(
        scenario, recipes, features_by_id, target, unlimited_stock, solver, ingredients_by_code
    ):
        hints.append(
            DiagnosticHint(
                family="stock",
                message="Stok bahan mentah pada satu atau lebih bahan berpotensi membatasi kelayakan menu 5 hari.",
            )
        )

    # 3. Relax repeat cap
    relaxed_repeat = scenario.model_copy(update={"max_repeat_per_family": scenario.days})
    if _is_feasible_under(
        relaxed_repeat, recipes, features_by_id, target, stock_raw_g, solver, ingredients_by_code
    ):
        hints.append(
            DiagnosticHint(
                family="repeat_cap",
                message=f"Batas pengulangan maksimal {scenario.max_repeat_per_family}x per keluarga resep membatasi alternatif yang tersedia.",
            )
        )

    # 4. Relax nutrition bounds
    relaxed_limits = [
        lim.model_copy(update={"min_per_serving": 0.0, "max_per_serving": None})
        for lim in target.limits
    ]
    relaxed_target = target.model_copy(update={"limits": relaxed_limits})
    if _is_feasible_under(
        scenario, recipes, features_by_id, relaxed_target, stock_raw_g, solver, ingredients_by_code
    ):
        hints.append(
            DiagnosticHint(
                family="nutrition",
                message="Target batas minimum/maksimum zat gizi tidak dapat dicapai oleh kandidat resep dalam anggaran/stok saat ini.",
            )
        )

    # 5. Relax excluded allergens (only if allergens were configured)
    if scenario.excluded_allergens:
        relaxed_allergens = scenario.model_copy(update={"excluded_allergens": []})
        if _is_feasible_under(
            relaxed_allergens, recipes, features_by_id, target, stock_raw_g, solver, ingredients_by_code
        ):
            hints.append(
                DiagnosticHint(
                    family="allergen",
                    message=(
                        f"Eksklusi alergen ({', '.join(sorted(scenario.excluded_allergens))}) "
                        "mengurangi kandidat resep hingga tidak ada kombinasi feasible."
                    ),
                )
            )

    if not hints:
        hints.append(
            DiagnosticHint(
                family="combined",
                message="Kombinasi beberapa kendala (anggaran, stok, gizi, alergen, atau pengulangan) membuat tidak ada solusi valid.",
            )
        )

    return hints
