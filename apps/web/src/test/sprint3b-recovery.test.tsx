import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { RecoveryWorkspace } from "@/components/recovery/RecoveryWorkspace";
import { RecoveryReviewSummaryCard } from "@/components/recovery/RecoveryReviewSummaryCard";
import type { RecoveryEventResponse } from "@/types/api";

const mockPreviewImpact = vi.fn();
const mockCreateRecovery = vi.fn();
const mockSubmitRecovery = vi.fn();
const mockGetRecovery = vi.fn();
const mockListRecovery = vi.fn();

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      user_id: "u1",
      username: "perencana_menu",
      full_name: "Siti Rahma",
      active_kitchen_id: "k1",
      active_kitchen_name: "Dapur SPPG Simulasi A",
      active_role: "MENU_PLANNER",
      csrf_token: "csrf",
      memberships: [],
    },
  }),
}));

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({
    runs: [
      {
        run_id: "run-base-1",
        scenario_id: "sc-base-1",
        dataset_version_id: "ds-rec-1",
        solver_status: "OPTIMAL",
        validation_passed: true,
        simulation_only: true,
        objective_total_idr: 15000000,
        cost_per_serving_average_idr: 12000,
        created_at: "2026-11-20T06:00:00Z",
      },
    ],
    selectedRunId: "run-base-1",
    refreshAll: vi.fn(),
  }),
}));

vi.mock("@/lib/api/client", () => {
  class MockApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    API_BASE_URL: "",
    ApiError: MockApiError,
    apiClient: {
      listMenuReviews: vi.fn().mockResolvedValue([
        {
          id: "rev-base-1",
          kitchen_id: "k1",
          scenario_id: "sc-base-1",
          scenario_name: "Menu Mingguan SPPG-A",
          run_id: "run-base-1",
          dataset_version_id: "ds-rec-1",
          version_number: 1,
          status: "APPROVED",
          title: "Menu Mingguan SPPG-A (Butuh 20 kg Ayam)",
          created_by_user_id: "u1",
          created_by_name: "Siti Rahma",
          submitted_by_user_id: "u1",
          submitted_by_name: "Siti Rahma",
          reviewed_by_user_id: "u2",
          reviewed_by_name: "Budi Santoso",
          created_at: "2026-11-20T06:00:00Z",
          updated_at: "2026-11-20T07:00:00Z",
          cost_per_serving_average_idr: 12000,
          objective_total_idr: 15000000,
          days_count: 5,
          simulation_only: true,
          approval_scope_notice: "Operasional internal.",
        },
      ]),
      listRecoveryEvents: (...args: unknown[]) => mockListRecovery(...args),
      getRun: vi.fn().mockResolvedValue({
        run_id: "run-base-1",
        scenario_id: "sc-base-1",
        dataset_version_id: "ds-rec-1",
        price_snapshot_id: "snap-1",
        simulation_only: true,
        solver_status: "OPTIMAL",
        validation_passed: true,
        objective_total_idr: 15000000,
        cost_per_serving_average_idr: 12000,
        solver_name: "CBC",
        raw_solver_status: "Optimal",
        solver_seconds: 0.12,
        input_sha256: "abc",
        model_version: "1.0",
        days: [],
        material_usage: [],
        constraint_audit: { all_hard_constraints_pass: true, tolerance: 1e-6, violations: [] },
        constraint_diagnostics: [],
        warnings: [],
        created_at: "2026-11-20T06:00:00Z",
      }),
      getScenario: vi.fn().mockResolvedValue({
        id: "sc-base-1",
        name: "Menu Mingguan SPPG-A",
        dataset_version_id: "ds-rec-1",
        nutrition_target_id: "t1",
        meal_type: "lunch",
        servings_per_day: 250,
        days: 5,
        budget_idr_per_serving: 16500,
        max_repeat_per_family: 2,
        excluded_allergens: [],
        price_overrides_idr_per_g: {},
        stock_overrides_raw_g: {},
        source_label: "synthetic",
        locked: true,
        created_at: "2026-11-20T06:00:00Z",
      }),
      getInventory: vi.fn().mockResolvedValue({
        dataset: { id: "ds-rec-1", name: "Simulasi Pemulihan Ayam Parsial", is_synthetic: true },
        items: [
          {
            id: "i7",
            code: "ING007",
            name: "Daging Ayam Fillet",
            category: "protein",
            edible_fraction: 1.0,
            stock_raw_g: 20000,
            usable_raw_g: 12000,
            incoming_raw_g: 8000,
            delivery_status: "PARTIAL",
            price_idr_per_g: 28,
            nutrients: {
              energy_kcal_100g: 165,
              protein_g_100g: 24,
              fat_g_100g: 7,
              carb_g_100g: 0,
              fiber_g_100g: 0,
              iron_mg_100g: 1,
            },
          },
        ],
        approved_plan_alerts: [],
      }),
      previewRecoveryImpact: (...args: unknown[]) => mockPreviewImpact(...args),
      createRecoveryEvent: (...args: unknown[]) => mockCreateRecovery(...args),
      submitRecoveryEvent: (...args: unknown[]) => mockSubmitRecovery(...args),
      getRecoveryEvent: (...args: unknown[]) => mockGetRecovery(...args),
      getRecoveryProcurementCsvUrl: (id: string, mode: string) =>
        `/api/v1/recovery/events/${id}/procurement.csv?mode=${mode}`,
    },
  };
});

function makePartialChickenEvent(
  overrides: Partial<RecoveryEventResponse> = {}
): RecoveryEventResponse {
  return {
    id: "ev-rec-1",
    kitchen_id: "k1",
    dataset_version_id: "ds-rec-1",
    baseline_menu_review_id: "rev-base-1",
    baseline_run_id: "run-base-1",
    baseline_scenario_id: "sc-base-1",
    title: "Pemulihan Menu Ayam Parsial",
    status: "ANALYZED",
    disruption_types: ["PARTIAL_DELIVERY", "STOCK_SHORTAGE"],
    disruption_summary: "Ayam hanya tiba 12 kg dari kebutuhan 20 kg (kurang 8 kg).",
    impact: {
      baseline_run_id: "run-base-1",
      baseline_menu_review_id: "rev-base-1",
      baseline_title: "Menu Mingguan SPPG-A (Butuh 20 kg Ayam)",
      baseline_status: "APPROVED",
      dataset_version_id: "ds-rec-1",
      dataset_name: "Simulasi Pemulihan Ayam Parsial",
      production_date: "2026-11-20T08:00:00Z",
      days: 5,
      baseline_servings_per_day: 250,
      servings_per_day: 250,
      baseline_budget_idr_per_serving: 16500,
      budget_idr_per_serving: 16500,
      inventory_snapshot_sha256: "sha-live-1",
      is_disrupted: true,
      baseline_still_feasible_at_new_conditions: false,
      disruption_types: ["PARTIAL_DELIVERY", "STOCK_SHORTAGE"],
      affected_ingredients: [
        {
          ingredient_code: "ING007",
          ingredient_name: "Daging Ayam Fillet",
          baseline_required_kg: 20,
          previous_usable_kg: 20,
          current_usable_kg: 12,
          shortfall_kg: 8,
          previous_price_idr_per_kg: 28000,
          current_price_idr_per_kg: 28000,
          price_delta_pct: null,
          delivery_status: "PARTIAL",
          incoming_kg: 8,
          data_quality_status: "PARTIAL_OR_ADJUSTED",
          causes: ["Pengiriman pemasok hanya tiba sebagian (12 kg dari 20 kg)."],
        },
      ],
      affected_slots: [
        {
          day_index: 1,
          slot: "protein",
          original_recipe_id: "r6",
          original_recipe_name: "Ayam Tumis Kecap",
          affected_ingredients: ["ING007"],
          reasons: ["Kekurangan Daging Ayam Fillet: butuh 20.00 kg, tersedia 12.00 kg (kurang 8.00 kg)."],
        },
      ],
      budget_violations: [],
      stock_shortages: ["Daging Ayam Fillet kurang 8.00 kg"],
      nutrition_or_other_issues: [],
      summary_message: "Gangguan memengaruhi 1 slot menu (Daging Ayam Fillet kurang 8.00 kg).",
      warnings: [],
    },
    min_disruption: {
      mode: "MIN_DISRUPTION",
      scenario_id: "sc-md-1",
      run_id: "run-md-1",
      solver_status: "OPTIMAL",
      validation_passed: true,
      changed_slots_count: 1,
      unchanged_slots_count: 19,
      total_slots_count: 20,
      changed_slots: [
        {
          day_index: 1,
          slot: "protein",
          original_recipe_id: "r6",
          original_recipe_name: "Ayam Tumis Kecap",
          new_recipe_id: "r8",
          new_recipe_name: "Telur Balado",
          reason: "Kekurangan Daging Ayam Fillet (kurang 8.00 kg).",
        },
      ],
      total_cost_idr: 15250000,
      cost_per_serving_idr: 12200,
      delta_vs_original_historical_idr: 250000,
      delta_vs_original_at_new_conditions_idr: null,
      delta_vs_min_disruption_idr: null,
      constraint_diagnostics: [],
      warnings: [],
      run_detail: null,
    },
    min_cost: {
      mode: "MIN_COST",
      scenario_id: "sc-mc-1",
      run_id: "run-mc-1",
      solver_status: "OPTIMAL",
      validation_passed: true,
      changed_slots_count: 4,
      unchanged_slots_count: 16,
      total_slots_count: 20,
      changed_slots: [],
      total_cost_idr: 14750000,
      cost_per_serving_idr: 11800,
      delta_vs_original_historical_idr: -250000,
      delta_vs_original_at_new_conditions_idr: null,
      delta_vs_min_disruption_idr: -500000,
      constraint_diagnostics: [],
      warnings: [],
      run_detail: null,
    },
    comparison: {
      original_historical: {
        label: "Menu Asli pada Kondisi Lama",
        feasible: true,
        total_cost_idr: 15000000,
        cost_per_serving_idr: 12000,
        notes: "Konteks historis",
        budget_violations: [],
        stock_shortages: [],
        nutrition_or_other_issues: [],
      },
      original_under_new_conditions: {
        label: "Menu Asli pada Kondisi Baru",
        feasible: false,
        total_cost_idr: 15000000,
        cost_per_serving_idr: 12000,
        notes: "Menu asli TIDAK LAYAK pada kondisi baru.",
        budget_violations: [],
        stock_shortages: ["Daging Ayam Fillet kurang 8.00 kg"],
        nutrition_or_other_issues: [],
      },
      same_conditions_comparison_valid: false,
      historical_price_comparison_allowed: false,
      cost_savings_claimed_idr: null,
      comparison_notice:
        "Menu asli TIDAK LAYAK pada kondisi terbaru, sehingga selisih biaya terhadap menu asli tidak dihitung sebagai penghematan.",
      min_disruption_vs_min_cost_identical: false,
      extra_slots_changed_for_min_cost: 3,
      savings_by_choosing_min_cost_over_min_disruption_idr: 500000,
    },
    procurement_delta_by_mode: {
      MIN_DISRUPTION: [
        {
          ingredient_code: "ING007",
          ingredient_name: "Daging Ayam Fillet",
          baseline_required_kg: 20,
          required_kg: 0,
          delta_vs_baseline_required_kg: -20,
          usable_on_hand_kg: 12,
          incoming_kg: 8,
          delivery_status: "PARTIAL",
          net_to_buy_kg: 0,
          unit_price_idr_per_kg: 28000,
          estimated_net_purchase_cost_idr: 0,
          reason: "Pengurangan kebutuhan karena substitusi slot ayam.",
        },
      ],
      MIN_COST: [],
    },
    selected_mode: null,
    selected_run_id: null,
    submitted_review_id: null,
    inventory_snapshot_sha256: "sha-live-1",
    is_stale_inventory: false,
    simulation_only: true,
    created_at: "2026-11-20T08:05:00Z",
    updated_at: "2026-11-20T08:05:00Z",
    ...overrides,
  };
}

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("Sprint 3B — Procurement Recovery UI Contracts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const baseEvent = makePartialChickenEvent();
    mockPreviewImpact.mockResolvedValue(baseEvent.impact);
    mockListRecovery.mockResolvedValue([]);
    mockCreateRecovery.mockResolvedValue(baseEvent);
    mockSubmitRecovery.mockResolvedValue({
      recovery_event: { ...baseEvent, status: "SUBMITTED", selected_mode: "MIN_DISRUPTION" },
      review: { id: "rev-new-1", title: "Usulan Pengganti Ayam", status: "SUBMITTED" },
    });
    mockGetRecovery.mockResolvedValue(baseEvent);
  });

  it("renders partial chicken shortage impact, Alternative A vs B, fair guardrail, and submits replacement proposal", async () => {
    renderWithQuery(<RecoveryWorkspace />);

    await waitFor(() => {
      expect(screen.getByText(/1 Slot Menu Terdampak/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Ayam Tumis Kecap/i)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("btn-compute-recovery"));

    await waitFor(() => {
      expect(screen.getByText(/Alternatif A — Minim Perubahan Menu/i)).toBeInTheDocument();
      expect(screen.getByText(/Alternatif B — Biaya Bahan Terendah/i)).toBeInTheDocument();
    });

    // Fair comparison never claims fake savings against infeasible original plan
    expect(
      screen.getByText(/selisih biaya terhadap menu asli tidak dihitung sebagai penghematan/i)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("btn-submit-recovery"));

    await waitFor(() => {
      expect(mockSubmitRecovery).toHaveBeenCalledWith(
        "ev-rec-1",
        expect.objectContaining({ mode: "MIN_DISRUPTION", submit_for_review: true })
      );
      expect(screen.getByText(/berhasil diajukan ke Kepala Dapur/i)).toBeInTheDocument();
    });
  });

  it("collapses duplicate Alternative A/B cards when min_disruption_vs_min_cost_identical is true", async () => {
    const base = makePartialChickenEvent();
    mockCreateRecovery.mockResolvedValueOnce({
      ...base,
      comparison: { ...base.comparison, min_disruption_vs_min_cost_identical: true },
    });

    renderWithQuery(<RecoveryWorkspace />);
    await waitFor(() => expect(screen.getByTestId("btn-compute-recovery")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("btn-compute-recovery"));

    await waitFor(() => {
      expect(screen.getByText(/Alternatif Optimal Tunggal/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Alternatif B — Biaya Bahan Terendah/i)).not.toBeInTheDocument();
  });

  it("renders honest INFEASIBLE diagnostics and hides submission when no valid recovery plan exists", async () => {
    const base = makePartialChickenEvent();
    mockCreateRecovery.mockResolvedValueOnce({
      ...base,
      status: "INFEASIBLE",
      min_disruption: {
        ...base.min_disruption,
        solver_status: "INFEASIBLE",
        validation_passed: false,
        constraint_diagnostics: [
          { family: "stock", message: "Stok sumber protein seluruhnya habis (0 kg)." },
        ],
      },
      min_cost: {
        ...base.min_cost,
        solver_status: "INFEASIBLE",
        validation_passed: false,
        constraint_diagnostics: [
          { family: "stock", message: "Stok sumber protein seluruhnya habis (0 kg)." },
        ],
      },
    });

    renderWithQuery(<RecoveryWorkspace />);
    await waitFor(() => expect(screen.getByTestId("btn-compute-recovery")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("btn-compute-recovery"));

    await waitFor(() => {
      expect(screen.getAllByText(/Tidak Layak \(INFEASIBLE\)/i).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.queryByTestId("btn-submit-recovery")).not.toBeInTheDocument();
  });

  it("renders stale-snapshot blocking warning in RecoveryReviewSummaryCard when inventory changed", async () => {
    const base = makePartialChickenEvent({
      selected_mode: "MIN_DISRUPTION",
      status: "SUBMITTED",
      is_stale_inventory: true,
    });
    mockGetRecovery.mockResolvedValueOnce(base);

    renderWithQuery(
      <RecoveryReviewSummaryCard recoveryEventId="ev-rec-1" isStaleInventoryHint={true} />
    );

    await waitFor(() => {
      expect(screen.getByText(/Snapshot Stok Berubah/i)).toBeInTheDocument();
      expect(screen.getByText(/1 dari 20 slot diubah/i)).toBeInTheDocument();
    });
  });
});
