import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MenuDayCard } from "@/components/menu/MenuDayCard";
import { NextWeekPlannerCard } from "@/components/menu/NextWeekPlannerCard";
import { formatDayLabel, formatPeriodPhase } from "@/lib/formatters/indonesian";
import type { OptimizationRunResponse } from "@/types/api";

const mockListOperationalPlans = vi.fn();
const mockListMenuReviews = vi.fn();
const mockGetNextWeekDefaults = vi.fn();
const mockPrepareNextWeek = vi.fn();
const mockSetSelectedRunId = vi.fn();
const mockRefreshAll = vi.fn();

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      user_id: "u-planner",
      username: "perencana_menu",
      full_name: "Sari Wijaya",
      active_kitchen_id: "k1",
      active_kitchen_name: "Dapur SPPG A",
      active_role: "MENU_PLANNER",
      csrf_token: "csrf",
      memberships: [],
    },
    refreshAuth: vi.fn(),
  }),
}));

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({
    setSelectedRunId: mockSetSelectedRunId,
    refreshAll: mockRefreshAll,
  }),
}));

vi.mock("@/lib/api/client", () => ({
  ApiError: class extends Error {
    status = 400;
  },
  apiClient: {
    listOperationalPlans: (...args: unknown[]) => mockListOperationalPlans(...args),
    listMenuReviews: (...args: unknown[]) => mockListMenuReviews(...args),
    getNextWeekDefaults: (...args: unknown[]) => mockGetNextWeekDefaults(...args),
    prepareNextWeek: (...args: unknown[]) => mockPrepareNextWeek(...args),
  },
}));

describe("Cross-Week Menu Planning UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListOperationalPlans.mockResolvedValue([
      {
        id: "assign-w1",
        kitchen_id: "k1",
        dataset_version_id: "ds1",
        menu_review_id: "rev-w1",
        run_id: "run-w1",
        scenario_id: "sc-w1",
        plan_title: "Rencana Minggu 1 Berjalan",
        scenario_name: "Minggu 1",
        review_version_number: 1,
        historical_review_status: "APPROVED",
        operational_status: "ACTIVE",
        production_date: "2027-01-18",
        horizon_days: 5,
        service_dates: ["2027-01-18", "2027-01-19", "2027-01-20", "2027-01-21", "2027-01-22"],
        period_start_date: "2027-01-18",
        period_end_date: "2027-01-22",
        derived_period_phase: "IN_PROGRESS",
        meal_type: "lunch",
        target_cohort: "SD_4_6",
        batch_label: "DEFAULT",
        scope_key: "k1|2027-01-18|lunch|SD_4_6|DEFAULT",
        scope_label: "2027-01-18 s.d. 2027-01-22",
        supersedes_assignment_id: null,
        hold_incident_id: null,
        hold_reason: null,
        held_at: null,
        activated_by_user_id: "u-mgr",
        activated_by_name: "Budi Santoso",
        activated_at: "2027-01-17T08:00:00Z",
        superseded_at: null,
        inventory_snapshot_sha256: "abc",
        is_stale_inventory: false,
        is_ready_for_execution: true,
        servings_per_day: 100,
        total_servings: 500,
        total_menu_slots: 20,
        total_cost_idr: 5500000,
        cost_per_serving_idr: 11000,
        cost_per_day_average_idr: 1100000,
        simulation_only: true,
      },
    ]);
    mockListMenuReviews.mockResolvedValue([
      {
        id: "rev-w2",
        kitchen_id: "k1",
        scenario_id: "sc-w2",
        scenario_name: "Minggu 2 Draft",
        run_id: "run-w2",
        dataset_version_id: "ds1",
        version_number: 1,
        status: "DRAFT",
        title: "Rencana Mingguan (2027-01-25 s.d. 2027-01-29)",
        planner_notes: null,
        reviewer_notes: null,
        created_by_user_id: "u-planner",
        created_by_name: "Sari Wijaya",
        submitted_by_user_id: null,
        submitted_by_name: null,
        reviewed_by_user_id: null,
        reviewed_by_name: null,
        submitted_at: null,
        reviewed_at: null,
        created_at: "2027-01-20T08:00:00Z",
        updated_at: "2027-01-20T08:00:00Z",
        cost_per_serving_average_idr: 10800,
        objective_total_idr: 5400000,
        days_count: 5,
        servings_per_day: 100,
        total_servings: 500,
        cost_per_day_average_idr: 1080000,
        simulation_only: true,
        service_dates: ["2027-01-25", "2027-01-26", "2027-01-27", "2027-01-28", "2027-01-29"],
        period_start_date: "2027-01-25",
        period_end_date: "2027-01-29",
        derived_period_phase: "UPCOMING",
        continuation_of_run_id: "run-w1",
        stock_confirmation_required: true,
        stock_confirmation_reason: "Minggu 1 belum selesai.",
        approval_scope_notice: "Operasional internal.",
      },
    ]);
    mockGetNextWeekDefaults.mockResolvedValue({
      source_run_id: "run-w1",
      source_assignment_id: "assign-w1",
      source_plan_title: "Rencana Minggu 1 Berjalan",
      source_service_dates: ["2027-01-18", "2027-01-19", "2027-01-20", "2027-01-21", "2027-01-22"],
      suggested_name: "Rencana Mingguan (2027-01-25 s.d. 2027-01-29)",
      suggested_service_dates: ["2027-01-25", "2027-01-26", "2027-01-27", "2027-01-28", "2027-01-29"],
      dataset_version_id: "ds1",
      nutrition_target_id: "t1",
      meal_type: "lunch",
      servings_per_day: 100,
      days: 5,
      budget_idr_per_serving: 12000,
      max_repeat_per_family: 2,
      excluded_allergens: [],
      history_source_type: "OPERATIONAL_PLAN",
      history_source_notice:
        "Histori 5 hari pelayanan sebelumnya bersumber dari rencana operasional yang diberlakukan.",
      stock_confirmation_required: true,
      stock_confirmation_reason: "Rencana periode berjalan belum selesai; sisa stok perlu dikonfirmasi.",
    });
    mockPrepareNextWeek.mockResolvedValue({
      scenario_id: "sc-w2-new",
      run_id: "run-w2-new",
      menu_review_id: "rev-w2-new",
      menu_review_status: "DRAFT",
      service_dates: ["2027-01-25", "2027-01-26", "2027-01-27", "2027-01-28", "2027-01-29"],
      solver_status: "OPTIMAL",
      validation_passed: true,
      stock_confirmation_required: true,
      stock_confirmation_reason: "Perlu konfirmasi.",
      history_context: {},
      warnings: [],
    });
  });

  it("formats day labels with actual service dates and derives period phases accurately", () => {
    const label = formatDayLabel(1, "2027-01-25");
    expect(label).toContain("Hari 1");
    expect(label).toContain("Jan");

    expect(formatPeriodPhase("IN_PROGRESS")).toEqual({
      label: "Minggu Berjalan",
      tone: "success",
    });
    expect(formatPeriodPhase("UPCOMING")).toEqual({
      label: "Minggu Mendatang",
      tone: "warning",
    });
    expect(formatPeriodPhase("COMPLETED")).toEqual({
      label: "Periode Selesai",
      tone: "neutral",
    });
  });

  it("renders MenuDayCard with the actual bound service date", () => {
    render(
      <MenuDayCard
        day={{
          day_index: 1,
          service_date: "2027-01-25",
          recipes_by_slot: {
            staple: "r1",
            protein: "r2",
            vegetable: "r3",
            fruit: "r4",
          },
          recipe_names_by_slot: {
            staple: "Nasi Putih",
            protein: "Ayam Panggang",
            vegetable: "Sayur Bayam",
            fruit: "Pisang Ambon",
          },
          daily_cost_idr_per_serving: 10500,
          nutrients_per_serving: { energy_kcal: 620, protein_g: 22.5 },
        }}
        budgetPerServing={12000}
      />
    );
    expect(screen.getByText(/Hari 1/i)).toBeInTheDocument();
    expect(screen.getByText(/Jan/i)).toBeInTheDocument();
    expect(screen.getByText("Nasi Putih")).toBeInTheDocument();
  });

  it("renders NextWeekPlannerCard with current/next periods, stock warning, comparison, and editable dates", async () => {
    const selectedRun: OptimizationRunResponse = {
      run_id: "run-w2",
      scenario_id: "sc-w2",
      dataset_version_id: "ds1",
      price_snapshot_id: "snap-1",
      solver_status: "OPTIMAL",
      validation_passed: true,
      simulation_only: true,
      objective_total_idr: 5400000,
      cost_per_serving_average_idr: 10800,
      service_dates: ["2027-01-25", "2027-01-26", "2027-01-27", "2027-01-28", "2027-01-29"],
      stock_confirmation_required: true,
      stock_confirmation_reason:
        "Rencana minggu berjalan belum selesai; ketersediaan stok perlu dikonfirmasi sebelum aktivasi.",
      history_context: {
        window_days: 5,
        history_days_count: 5,
        primary_source_type: "OPERATIONAL_PLAN",
        source_notice: "Histori 5 hari pelayanan bersumber dari rencana operasional.",
        previous_run_id: "run-w1",
        previous_plan_title: "Rencana Minggu 1 Berjalan",
        previous_cost_per_serving_idr: 11000,
        previous_period_dates: ["2027-01-18", "2027-01-19", "2027-01-20", "2027-01-21", "2027-01-22"],
        history_days: [],
        comparison: {
          previous_unique_recipes_count: 10,
          new_unique_recipes_count: 11,
          fresh_recipes_count: 4,
          repeated_recipes_from_previous_week_count: 7,
          boundary_day5_to_day1_repeat_count: 0,
          max_boundary_5day_family_repeat: 2,
          previous_cost_per_serving_idr: 11000,
          new_cost_per_serving_idr: 10800,
          cost_delta_per_serving_idr: -200,
        },
      },
      best_bound: null,
      gap_abs: null,
      gap_rel: null,
      solver_name: "CBC",
      solver_version: "2.10",
      raw_solver_status: "Optimal",
      solver_seconds: 0.2,
      input_sha256: "sha",
      model_version: "v1",
      input_snapshot: {},
      days: [],
      material_usage: [],
      constraint_audit: { all_hard_constraints_pass: true, tolerance: 1e-6, violations: [] },
      constraint_diagnostics: [],
      warnings: [],
      created_at: "2027-01-20T08:00:00Z",
    };

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <NextWeekPlannerCard selectedRun={selectedRun} />
      </QueryClientProvider>
    );

    expect(await screen.findByText("Rencana Minggu 1 Berjalan")).toBeInTheDocument();
    expect(screen.getByText("Minggu Berjalan")).toBeInTheDocument();
    expect(screen.getByText("Minggu Mendatang")).toBeInTheDocument();
    expect(screen.getByText(/Perlu Konfirmasi Stok Sebelum Aktivasi/i)).toBeInTheDocument();
    expect(screen.getByText(/0 resep/i)).toBeInTheDocument();
    expect(screen.getByText(/4 dari 11 resep unik/i)).toBeInTheDocument();

    const triggerBtn = screen.getByRole("button", { name: /Siapkan Menu Minggu Berikutnya/i });
    fireEvent.click(triggerBtn);

    expect(await screen.findByLabelText("Tanggal pelayanan Hari 1")).toHaveValue("2027-01-25");

    const submitBtn = screen.getByRole("button", { name: /Hitung & Simpan Draf Minggu Berikutnya/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockPrepareNextWeek).toHaveBeenCalledWith(
        expect.objectContaining({
          source_assignment_id: "assign-w1",
          service_dates: ["2027-01-25", "2027-01-26", "2027-01-27", "2027-01-28", "2027-01-29"],
        })
      );
    });
  });
});
