import React from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { BudgetProgress } from "@/components/dashboard/BudgetProgress";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
} from "@/components/feedback/FeedbackStates";
import { ScenarioComparison } from "@/components/simulator/ScenarioComparison";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { KPIStatCard } from "@/components/ui/KPIStatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  formatDayLabel,
  formatDecimal,
  formatIDR,
  formatRunStatus,
  formatSignedIDR,
  formatSlotLabel,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";
import type { ScenarioComparisonResponse } from "@/types/api";

describe("Indonesian Formatters", () => {
  it("formats currency, signed delta, decimals, weights, days, and slots", () => {
    expect(formatIDR(7530)).toBe("Rp7.530");
    expect(formatIDR(3765100)).toBe("Rp3.765.100");
    expect(formatIDR(null)).toBe("Belum tersedia");
    expect(formatSignedIDR(103000)).toBe("+Rp103.000");
    expect(formatSignedIDR(-5000)).toBe("-Rp5.000");
    expect(formatDecimal(7.5, 1)).toBe("7,5");
    expect(formatWeightFromGrams(7500)).toBe("7,5 kg");
    expect(formatWeightFromGrams(450)).toBe("450 gram");
    expect(formatDayLabel(1)).toBe("Hari 1 (Senin)");
    expect(formatSlotLabel("protein")).toBe("Lauk Protein");
  });

  it("maps solver statuses honestly in Indonesian", () => {
    expect(formatRunStatus("OPTIMAL", true).tone).toBe("success");
    expect(formatRunStatus("FEASIBLE", true).tone).toBe("warning");
    expect(formatRunStatus("FEASIBLE", true).label).toContain("Belum Terbukti Paling Murah");
    expect(formatRunStatus("INFEASIBLE", false).tone).toBe("critical");
    expect(formatRunStatus("TIME_LIMIT", false).tone).toBe("critical");
    expect(formatRunStatus("ERROR", false).tone).toBe("critical");
  });
});

describe("Core UI Components & Mathematical Honesty", () => {
  it("renders KPIStatCard, StatusBadge, and DatasetSimulationNotice", () => {
    render(
      <div>
        <KPIStatCard label="Biaya per Porsi" value="Rp7.530" helper="Rata-rata 5 hari" />
        <StatusBadge tone="success" label="Layak & Optimal" />
        <DatasetSimulationNotice simulationOnly datasetName="Fixture v0.1" />
      </div>
    );
    expect(screen.getByText("Biaya per Porsi")).toBeInTheDocument();
    expect(screen.getByText("Rp7.530")).toBeInTheDocument();
    expect(screen.getByText("Layak & Optimal")).toBeInTheDocument();
    expect(screen.getByText(/DEMO_ONLY/i)).toBeInTheDocument();
  });

  it("renders BudgetProgress without calling unused budget savings", () => {
    render(<BudgetProgress averageCostPerServing={7530} budgetPerServing={12000} />);
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText(/bukan klaim penghematan/i)).toBeInTheDocument();
  });

  it("renders EmptyState, ErrorState retry, and ConfirmDialog", () => {
    const onRetry = vi.fn();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <div>
        <EmptyState title="Kosong" description="Belum ada skenario" />
        <ErrorState message="Server offline" onRetry={onRetry} />
        <ConfirmDialog
          open
          title="Konfirmasi"
          description="Lanjutkan aksi?"
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      </div>
    );

    fireEvent.click(screen.getByText("Coba Lagi"));
    expect(onRetry).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText("Lanjutkan"));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("renders ScenarioComparison honestly for price shock and infeasible states", () => {
    const baseComp: ScenarioComparisonResponse = {
      base: {
        run_id: "r0",
        scenario_id: "s0",
        dataset_version_id: "ds1",
        solver_status: "OPTIMAL",
        validation_passed: true,
        simulation_only: true,
        objective_total_idr: 3765100,
        cost_per_serving_average_idr: 7530.2,
        input_sha256: "abc",
        model_version: "recipe-milp-v0.1",
        solver_name: "COIN_CMD",
        solver_version: "Devel",
      },
      candidate: {
        run_id: "r1",
        scenario_id: "s1",
        dataset_version_id: "ds1",
        solver_status: "OPTIMAL",
        validation_passed: true,
        simulation_only: true,
        objective_total_idr: 3868100,
        cost_per_serving_average_idr: 7736.2,
        input_sha256: "def",
        model_version: "recipe-milp-v0.1",
        solver_name: "COIN_CMD",
        solver_version: "Devel",
      },
      compatibility: {
        same_dataset_version: true,
        same_nutrition_target: true,
        same_horizon_and_servings: true,
        same_prices: false,
        same_stock: true,
        same_constraints: true,
        changed_prices: [
          {
            ingredient_code: "ING006",
            base_price_idr_per_g: 28,
            candidate_price_idr_per_g: 56,
            delta_pct: 100,
          },
        ],
        changed_stock: [],
        constraint_differences: [],
        apples_to_apples_comparable: false,
        comparison_basis: "input_price_or_constraint_change",
      },
      cost_comparison: {
        base_total_idr: 3765100,
        candidate_total_idr: 3868100,
        delta_total_idr: 103000,
        base_cost_per_serving_idr: 7530.2,
        candidate_cost_per_serving_idr: 7736.2,
        delta_cost_per_serving_idr: 206,
        delta_cost_pct: 2.74,
        cost_savings_achieved_idr: null,
        cost_savings_pct: null,
        interpretation: "Scenario delta under different input prices.",
      },
      nutrient_comparison: [],
      recipe_changes: [
        {
          day_index: 1,
          slot: "protein",
          base_recipe_name: "Telur Balado & Tahu",
          candidate_recipe_name: "Ikan Kembung Goreng",
          changed: true,
        },
      ],
      total_slot_swaps: 1,
      ingredient_usage_comparison: [],
      warnings: [],
    };

    const { rerender } = render(
      <ScenarioComparison
        comparison={baseComp}
        baseName="Rencana Awal"
        candidateName="Telur +100%"
      />
    );
    expect(screen.getByText(/Perbedaan Biaya Berasal dari Perubahan Kondisi Input/i)).toBeInTheDocument();
    expect(screen.getByText("Ikan Kembung Goreng")).toBeInTheDocument();

    // Now test INFEASIBLE candidate
    const infComp: ScenarioComparisonResponse = {
      ...baseComp,
      candidate: {
        ...baseComp.candidate,
        solver_status: "INFEASIBLE",
        validation_passed: false,
        objective_total_idr: null,
        cost_per_serving_average_idr: null,
      },
      compatibility: {
        ...baseComp.compatibility,
        comparison_basis: "not_comparable_infeasible",
      },
      cost_comparison: {
        ...baseComp.cost_comparison,
        candidate_total_idr: null,
        delta_total_idr: null,
      },
    };
    rerender(
      <ScenarioComparison
        comparison={infComp}
        baseName="Rencana Awal"
        candidateName="Stok Habis"
      />
    );
    expect(
      screen.getByText(/Belum ditemukan kombinasi menu yang memenuhi seluruh batasan/i)
    ).toBeInTheDocument();
  });
});
