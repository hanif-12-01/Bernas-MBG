import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { IncidentPanel } from "@/components/incidents/IncidentPanel";
import type { IngredientIncidentResponse, InventoryLotsResponse } from "@/types/api";

const mockPush = vi.fn();
const mockListIncidents = vi.fn();
const mockGetInventoryLots = vi.fn();
const mockCreateIncident = vi.fn();
const mockStartIncidentRecovery = vi.fn();
const mockUpdateIncidentStatus = vi.fn();

let currentRole = "QC_OFFICER";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      user_id: "u1",
      username: currentRole === "MENU_PLANNER" ? "perencana_menu" : "petugas_qc",
      full_name: currentRole === "MENU_PLANNER" ? "Siti Rahma" : "Dina Lestari",
      active_kitchen_id: "k1",
      active_kitchen_name: "Dapur SPPG Simulasi A",
      active_role: currentRole,
      csrf_token: "csrf",
      memberships: [],
    },
  }),
}));

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({
    datasets: [
      {
        id: "55555555-5555-4555-8555-555555555555",
        name: "Dataset Simulasi Insiden Bahan Pangan 3C (DEMO_ONLY)",
        source_type: "synthetic",
        source_url: null,
        is_synthetic: true,
        is_active: false,
        review_status: "reviewed",
        ingestion_metadata: {},
        created_at: "2026-11-23T00:00:00Z",
      },
    ],
    activeDataset: {
      id: "55555555-5555-4555-8555-555555555555",
      name: "Dataset Simulasi Insiden Bahan Pangan 3C (DEMO_ONLY)",
    },
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
      listIncidents: (...args: unknown[]) => mockListIncidents(...args),
      getInventoryLots: (...args: unknown[]) => mockGetInventoryLots(...args),
      createIncident: (...args: unknown[]) => mockCreateIncident(...args),
      startIncidentRecovery: (...args: unknown[]) => mockStartIncidentRecovery(...args),
      updateIncidentStatus: (...args: unknown[]) => mockUpdateIncidentStatus(...args),
      uploadIncidentImage: vi.fn(),
    },
  };
});

const SAMPLE_LOTS: InventoryLotsResponse = {
  kitchen_id: "k1",
  dataset_version_id: "55555555-5555-4555-8555-555555555555",
  production_date: "2026-11-23T08:00:00Z",
  items: [
    {
      ingredient_id: "ing-chicken",
      ingredient_code: "ING007",
      ingredient_name: "Daging Ayam Fillet",
      recorded_raw_g: 40000,
      usable_raw_g: 40000,
      safety_held_raw_g: 0,
      rejected_disposed_raw_g: 0,
      data_quality_status: "VERIFIED",
      held_lot_codes: [],
      lots: [
        {
          id: "lot-a",
          lot_code: "LOT-3C-AYAM-A",
          recorded_raw_g: 24000,
          usable_raw_g: 24000,
          damaged_raw_g: 0,
          expires_at: "2027-01-01T00:00:00Z",
          expiry_known: true,
          verification_status: "VERIFIED",
          safety_hold_status: "NONE",
          notes: "Cold storage rak 1",
        },
        {
          id: "lot-b",
          lot_code: "LOT-3C-AYAM-B",
          recorded_raw_g: 16000,
          usable_raw_g: 16000,
          damaged_raw_g: 0,
          expires_at: "2027-01-01T00:00:00Z",
          expiry_known: true,
          verification_status: "VERIFIED",
          safety_hold_status: "NONE",
          notes: "Cold storage rak 2",
        },
      ],
    },
    {
      ingredient_id: "ing-egg",
      ingredient_code: "ING006",
      ingredient_name: "Telur Ayam Ras",
      recorded_raw_g: 40000,
      usable_raw_g: 40000,
      safety_held_raw_g: 0,
      rejected_disposed_raw_g: 0,
      data_quality_status: "VERIFIED",
      held_lot_codes: [],
      lots: [
        {
          id: "lot-egg",
          lot_code: "LOT-3C-TELUR-A",
          recorded_raw_g: 40000,
          usable_raw_g: 40000,
          damaged_raw_g: 0,
          expires_at: "2027-01-01T00:00:00Z",
          expiry_known: true,
          verification_status: "VERIFIED",
          safety_hold_status: "NONE",
          notes: "Rak telur",
        },
      ],
    },
  ],
};

const SAMPLE_INCIDENT: IngredientIncidentResponse = {
  id: "inc-1",
  kitchen_id: "k1",
  dataset_version_id: "55555555-5555-4555-8555-555555555555",
  title: "Ayam Lot A Bau Asam + Telur Retak",
  category: "SPOILAGE",
  severity: "CRITICAL",
  status: "ON_HOLD",
  notes: "Bau asam di rak 1 cold storage.",
  supplier_name: null,
  delivery_ref: null,
  related_batch_code: null,
  observed_at: "2026-11-23T08:00:00Z",
  reported_by_user_id: "u1",
  reported_by_name: "Dina Lestari",
  reporter_role: "QC_OFFICER",
  created_at: "2026-11-23T08:00:00Z",
  updated_at: "2026-11-23T08:00:00Z",
  affected_lots: [
    {
      id: "al-1",
      incident_id: "inc-1",
      lot_id: "lot-a",
      lot_code: "LOT-3C-AYAM-A",
      ingredient_id: "ing-chicken",
      ingredient_code: "ING007",
      ingredient_name: "Daging Ayam Fillet",
      lot_safety_status: "ON_HOLD",
      prior_lot_verification_status: "VERIFIED",
      recorded_raw_g_snapshot: 24000,
      usable_before_hold_raw_g: 24000,
      usable_after_hold_raw_g: 0,
      clean_remaining_raw_g: 16000,
      reason_detail: "Bau asam",
      updated_at: "2026-11-23T08:00:00Z",
    },
  ],
  affected_ingredient_codes: ["ING007"],
  affected_ingredient_names: ["Daging Ayam Fillet"],
  total_held_kg: 24.0,
  total_clean_remaining_kg: 16.0,
  affected_plans: [],
  exposure_status: "POTENTIAL_PRODUCTION_EXPOSURE",
  production_exposures: [
    {
      exposure_status: "POTENTIAL_PRODUCTION_EXPOSURE",
      summary: "Batch BATCH-01 sudah diporsikan menggunakan Daging Ayam Fillet.",
    },
  ],
  recovery_event_id: null,
  images: [],
  actions: [],
  safety_notice: "SAFETY HOLD terkunci.",
  simulation_only: true,
};

function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("IncidentPanel & Safety Hold UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentRole = "QC_OFFICER";
    mockGetInventoryLots.mockResolvedValue(SAMPLE_LOTS);
    mockListIncidents.mockResolvedValue([SAMPLE_INCIDENT]);
    mockCreateIncident.mockResolvedValue(SAMPLE_INCIDENT);
    mockStartIncidentRecovery.mockResolvedValue({ id: "rec-ev-1" });
  });

  it("displays held vs clean stock, production exposure warning, and forbids internal release", async () => {
    renderWithQuery(<IncidentPanel />);

    expect(await screen.findByText(/Ayam Lot A Bau Asam \+ Telur Retak/i)).toBeInTheDocument();
    expect(screen.getByText(/24\.00 kg \(1 lot\)/i)).toBeInTheDocument();
    expect(screen.getAllByText(/16\.00 kg/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/PERINGATAN PAPARAN PRODUKSI/i)).toBeInTheDocument();
    expect(screen.getByText(/tidak dapat dilepaskan sepihak/i)).toBeInTheDocument();
    // QC cannot see recovery trigger or release-hold buttons
    expect(screen.queryByRole("button", { name: /Cari Alternatif Menu/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Lepaskan/i })).not.toBeInTheDocument();
  });

  it("submits multiple selected lots atomically without exposing pricing to QC", async () => {
    renderWithQuery(<IncidentPanel />);

    await screen.findAllByText(/LOT-3C-AYAM-A/);
    fireEvent.change(screen.getByLabelText(/Judul Laporan Insiden/i), {
      target: { value: "Ayam A dan Telur Bermasalah" },
    });
    fireEvent.change(screen.getByLabelText(/Keterangan Kondisi/i), {
      target: { value: "Bau asam di rak 1 dan telur retak" },
    });

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]); // LOT-3C-AYAM-A
    fireEvent.click(checkboxes[2]); // LOT-3C-TELUR-A

    fireEvent.click(screen.getByRole("button", { name: /Tahan Lot & Laporkan Insiden/i }));

    await waitFor(() => {
      expect(mockCreateIncident).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Ayam A dan Telur Bermasalah",
          affected_lots: expect.arrayContaining([
            expect.objectContaining({ lot_code: "LOT-3C-AYAM-A" }),
            expect.objectContaining({ lot_code: "LOT-3C-TELUR-A" }),
          ]),
        })
      );
    });
  });

  it("lets MENU_PLANNER launch recovery directly from an active safety hold incident", async () => {
    currentRole = "MENU_PLANNER";
    renderWithQuery(<IncidentPanel onNavigate={mockPush} />);

    const recoverBtn = await screen.findByRole("button", { name: /Cari Alternatif Menu/i });
    fireEvent.click(recoverBtn);

    await waitFor(() => {
      expect(mockStartIncidentRecovery).toHaveBeenCalledWith("inc-1", expect.any(Object));
      expect(mockPush).toHaveBeenCalledWith("/simulator?eventId=rec-ev-1");
    });
  });
});
