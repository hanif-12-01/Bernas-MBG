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
const mockUploadIncidentImage = vi.fn();
const mockGetIncident = vi.fn();
const mockRecordIncidentDisposal = vi.fn();

let currentRole = "QC_OFFICER";
let currentIsCustodian = true;

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
      is_active_stock_custodian: currentRole === "QC_OFFICER" && currentIsCustodian,
      stock_custodian: {
        is_assigned: true,
        custodian_username: "petugas_qc",
        custodian_full_name: "Dina Lestari",
      },
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
      listIncidents: (...args: unknown[]) => mockListIncidents(...args),
      getInventoryLots: (...args: unknown[]) => mockGetInventoryLots(...args),
      createIncident: (...args: unknown[]) => mockCreateIncident(...args),
      uploadIncidentImage: (...args: unknown[]) => mockUploadIncidentImage(...args),
      getIncident: (...args: unknown[]) => mockGetIncident(...args),
      recordIncidentDisposal: (...args: unknown[]) => mockRecordIncidentDisposal(...args),
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
      usable_raw_g: 16000,
      safety_held_raw_g: 24000,
      rejected_disposed_raw_g: 0,
      data_quality_status: "PARTIAL_SAFETY_HOLD",
      held_lot_codes: ["LOT-3C-AYAM-A"],
      lots: [
        {
          id: "lot-ayam-a",
          lot_code: "LOT-3C-AYAM-A",
          recorded_raw_g: 24000,
          usable_raw_g: 0,
          damaged_raw_g: 0,
          expires_at: "2027-06-30T23:59:59Z",
          expiry_known: true,
          verification_status: "VERIFIED",
          safety_hold_status: "ON_HOLD",
          notes: "Bau asam rak 1",
        },
        {
          id: "lot-ayam-b",
          lot_code: "LOT-3C-AYAM-B",
          recorded_raw_g: 16000,
          usable_raw_g: 16000,
          damaged_raw_g: 0,
          expires_at: "2027-06-30T23:59:59Z",
          expiry_known: true,
          verification_status: "VERIFIED",
          safety_hold_status: "NONE",
          notes: "Lot B bersih",
        },
      ],
    },
  ],
};

const SAMPLE_INCIDENT: IngredientIncidentResponse = {
  id: "inc-1",
  kitchen_id: "k1",
  dataset_version_id: "55555555-5555-4555-8555-555555555555",
  title: "Tahan Keamanan: Daging Ayam Fillet (Basi / Rusak)",
  category: "SPOILAGE",
  severity: "HIGH",
  status: "ON_HOLD",
  notes: "Penahanan cepat (Basi / Rusak) pada 1 lot bahan.",
  supplier_name: null,
  delivery_ref: null,
  related_batch_code: null,
  observed_at: "2026-11-23T09:00:00Z",
  reported_by_user_id: "u1",
  reported_by_name: "Dina Lestari",
  reporter_role: "QC_OFFICER",
  created_at: "2026-11-23T09:00:00Z",
  updated_at: "2026-11-23T09:00:00Z",
  affected_lots: [
    {
      id: "al-1",
      incident_id: "inc-1",
      lot_id: "lot-ayam-a",
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
      updated_at: "2026-11-23T09:00:00Z",
    },
  ],
  affected_ingredient_codes: ["ING007"],
  affected_ingredient_names: ["Daging Ayam Fillet"],
  total_held_kg: 24,
  total_clean_remaining_kg: 16,
  affected_plans: [],
  exposure_status: "POTENTIAL_PRODUCTION_EXPOSURE",
  production_exposures: [],
  recovery_event_id: null,
  disposal_authorized: true,
  disposal_authorized_by_name: "Budi Santoso",
  disposal_authorized_at: "2026-11-23T09:10:00Z",
  disposal_executed_at: null,
  images: [],
  actions: [],
  safety_notice: "STATUS TAHAN KEAMANAN",
  simulation_only: true,
};

function renderWithQuery(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("IncidentPanel & Single Stock Custodian Safety Hold UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentRole = "QC_OFFICER";
    currentIsCustodian = true;
    mockGetInventoryLots.mockResolvedValue(SAMPLE_LOTS);
    mockListIncidents.mockResolvedValue([SAMPLE_INCIDENT]);
    mockCreateIncident.mockResolvedValue(SAMPLE_INCIDENT);
    mockGetIncident.mockResolvedValue(SAMPLE_INCIDENT);
    mockRecordIncidentDisposal.mockResolvedValue({
      ...SAMPLE_INCIDENT,
      status: "REJECTED",
      disposal_executed_at: "2026-11-23T09:30:00Z",
    });
  });

  it("allows fast 2-field incident submission without opening optional fields", async () => {
    renderWithQuery(<IncidentPanel />);

    const checkbox = await screen.findByLabelText(/Daging Ayam Fillet/i);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: /Tahan Bahan & Kirim Laporan/i }));

    await waitFor(() => {
      expect(mockCreateIncident).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "SPOILAGE",
          affected_lots: [expect.objectContaining({ lot_code: "LOT-3C-AYAM-B" })],
        })
      );
    });
  });

  it("decouples failed photo upload so safety hold succeeds and shows retry button", async () => {
    mockUploadIncidentImage.mockRejectedValueOnce(new Error("Koneksi foto terputus"));
    renderWithQuery(<IncidentPanel />);

    const checkbox = await screen.findByLabelText(/Daging Ayam Fillet/i);
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: /Detail Tambahan \(Opsional\)/i }));

    const fileInput = screen.getByLabelText(/Foto Bukti Kondisi Bahan/i);
    const fakePhoto = new File(["img"], "bukti.jpg", { type: "image/jpeg" });
    fireEvent.change(fileInput, { target: { files: [fakePhoto] } });

    fireEvent.click(screen.getByRole("button", { name: /Tahan Bahan & Kirim Laporan/i }));

    expect(
      await screen.findByText(/Laporan berhasil dan bahan sudah ditahan\. Foto belum berhasil diunggah\. Coba unggah ulang\./i)
    ).toBeInTheDocument();

    mockUploadIncidentImage.mockResolvedValueOnce({ id: "img-1" });
    fireEvent.click(screen.getByRole("button", { name: /Unggah Ulang Foto/i }));
    await waitFor(() => {
      expect(mockUploadIncidentImage).toHaveBeenCalledTimes(2);
    });
  });

  it("hides report form from non-custodian QC or Planner and lets custodian execute authorized disposal", async () => {
    const first = renderWithQuery(<IncidentPanel />);
    const disposeBtn = await screen.findByRole("button", { name: /Catat Pemusnahan Fisik/i });
    fireEvent.click(disposeBtn);
    await waitFor(() => {
      expect(mockRecordIncidentDisposal).toHaveBeenCalledWith("inc-1");
    });
    first.unmount();

    currentIsCustodian = false;
    renderWithQuery(<IncidentPanel />);
    expect(screen.queryByRole("button", { name: /Tahan Bahan & Kirim Laporan/i })).not.toBeInTheDocument();
  });
});
