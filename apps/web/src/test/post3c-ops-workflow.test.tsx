import React from "react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ManagerIncidentReviewList } from "@/components/incidents/ManagerIncidentReviewList";
import { CustodianDelegationCard } from "@/components/custodian/CustodianDelegationCard";

const mockListIncidents = vi.fn().mockResolvedValue([
  {
    id: "inc-mgr-1",
    kitchen_id: "k1",
    dataset_version_id: "ds-1",
    title: "Tahan Keamanan: Bayam Hijau (Basi / Rusak)",
    category: "SPOILAGE",
    severity: "HIGH",
    status: "ON_HOLD",
    notes: "Daun layu berlendir",
    supplier_name: null,
    delivery_ref: null,
    related_batch_code: null,
    observed_at: "2026-11-21T08:00:00Z",
    reported_by_user_id: "u-qc",
    reported_by_name: "Dina Lestari",
    reporter_role: "QC_OFFICER",
    created_at: "2026-11-21T08:00:00Z",
    updated_at: "2026-11-21T08:00:00Z",
    affected_lots: [
      {
        id: "al-1",
        incident_id: "inc-mgr-1",
        lot_id: "lot-1",
        lot_code: "LOT-BAYAM-01",
        ingredient_id: "ing-bayam",
        ingredient_code: "ING012",
        ingredient_name: "Bayam Hijau",
        lot_safety_status: "ON_HOLD",
        prior_lot_verification_status: "VERIFIED",
        recorded_raw_g_snapshot: 15000,
        usable_before_hold_raw_g: 15000,
        usable_after_hold_raw_g: 0,
        clean_remaining_raw_g: 0,
        reason_detail: null,
        updated_at: "2026-11-21T08:00:00Z",
      },
    ],
    affected_ingredient_codes: ["ING012"],
    affected_ingredient_names: ["Bayam Hijau"],
    total_held_kg: 15,
    total_clean_remaining_kg: 0,
    affected_plans: [],
    exposure_status: "NO_RECORDED_PRODUCTION_EXPOSURE",
    production_exposures: [],
    recovery_event_id: null,
    disposal_authorized: false,
    disposal_executed_at: null,
    images: [],
    actions: [],
    safety_notice: "SAFETY HOLD",
    simulation_only: true,
  },
]);

const mockUpdateIncidentStatus = vi.fn().mockResolvedValue({
  id: "inc-mgr-1",
  title: "Tahan Keamanan: Bayam Hijau (Basi / Rusak)",
  status: "REJECTED",
  disposal_authorized: true,
});

const mockGetStockCustodian = vi.fn().mockResolvedValue({
  kitchen_id: "k1",
  kitchen_code: "SPPG-A",
  kitchen_name: "Dapur A",
  active_assignment: {
    id: "ca-1",
    kitchen_id: "k1",
    custodian_user_id: "qc-1",
    custodian_username: "petugas_qc",
    custodian_full_name: "Dina Lestari",
    status: "ACTIVE",
    effective_from: "2026-11-21T07:00:00Z",
    created_at: "2026-11-21T07:00:00Z",
  },
  eligible_qc_candidates: [
    {
      user_id: "qc-1",
      username: "petugas_qc",
      full_name: "Dina Lestari",
      email: "qc.a@test",
      is_active_custodian: true,
    },
    {
      user_id: "qc-2",
      username: "petugas_qc_2",
      full_name: "Rizal Mahendra",
      email: "qc2.a@test",
      is_active_custodian: false,
    },
  ],
  history: [],
});

const mockAssignStockCustodian = vi.fn().mockResolvedValue({
  active_assignment: {
    custodian_user_id: "qc-2",
    custodian_full_name: "Rizal Mahendra",
  },
});

const mockRevokeStockCustodian = vi.fn().mockResolvedValue({
  active_assignment: null,
});

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      user_id: "u-mgr",
      username: "kepala_dapur",
      full_name: "Budi Santoso",
      active_kitchen_id: "k1",
      active_kitchen_name: "Dapur A",
      active_role: "KITCHEN_MANAGER",
      csrf_token: "csrf",
      memberships: [],
    },
    refreshAuth: vi.fn(),
  }),
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE_URL: "",
  apiClient: {
    listIncidents: (...args: unknown[]) => mockListIncidents(...args),
    updateIncidentStatus: (...args: unknown[]) => mockUpdateIncidentStatus(...args),
    getStockCustodian: (...args: unknown[]) => mockGetStockCustodian(...args),
    assignStockCustodian: (...args: unknown[]) => mockAssignStockCustodian(...args),
    revokeStockCustodian: (...args: unknown[]) => mockRevokeStockCustodian(...args),
    getProtectedImageUrl: (u: string) => u,
  },
}));

describe("Post-3C Manager Delegation & Two-Step Disposal UI", () => {
  it("allows Kitchen Manager to delegate/revoke active stock custodian and authorize disposal without direct ledger write", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <CustodianDelegationCard />
        <ManagerIncidentReviewList />
      </QueryClientProvider>
    );

    expect(await screen.findByText(/Aktif: Dina Lestari/i)).toBeInTheDocument();
    const select = screen.getByLabelText(/Pilih Petugas QC/i);
    fireEvent.change(select, { target: { value: "qc-2" } });
    fireEvent.click(screen.getByRole("button", { name: /Tugaskan Pengelola Stok/i }));

    await waitFor(() => {
      expect(mockAssignStockCustodian).toHaveBeenCalledWith(
        expect.objectContaining({ custodian_user_id: "qc-2" })
      );
    });

    fireEvent.click(screen.getByRole("button", { name: /Cabut Penugasan/i }));
    await waitFor(() => {
      expect(mockRevokeStockCustodian).toHaveBeenCalled();
    });

    const authBtn = await screen.findByRole("button", { name: /Setujui Pemusnahan Lot/i });
    fireEvent.click(authBtn);
    await waitFor(() => {
      expect(mockUpdateIncidentStatus).toHaveBeenCalledWith(
        "inc-mgr-1",
        expect.objectContaining({ status: "REJECTED", dispose_held_lots: true })
      );
    });
  });
});
