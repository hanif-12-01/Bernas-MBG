import React from "react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";

import InventoryPage from "@/app/inventory/page";

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      user_id: "u1",
      username: "perencana_menu",
      full_name: "Siti Rahma",
      active_kitchen_id: "k1",
      active_kitchen_name: "Dapur Simulasi A",
      active_role: "MENU_PLANNER",
      csrf_token: "csrf",
      kitchens: [],
    },
  }),
}));

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({
    datasets: [
      {
        id: "ds-1",
        name: "Simulasi Kualitas Stok (DEMO_ONLY)",
        source_type: "synthetic",
        source_url: null,
        is_synthetic: true,
        is_active: false,
        review_status: "reviewed",
        ingestion_metadata: {},
        created_at: "2026-11-20T00:00:00Z",
      },
    ],
    activeDataset: {
      id: "ds-1",
      name: "Simulasi Kualitas Stok (DEMO_ONLY)",
      source_type: "synthetic",
      source_url: null,
      is_synthetic: true,
      is_active: false,
      review_status: "reviewed",
      ingestion_metadata: {},
      created_at: "2026-11-20T00:00:00Z",
    },
  }),
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE_URL: "",
  apiClient: {
    getInventory: vi.fn().mockResolvedValue({
      dataset: {
        id: "ds-1",
        name: "Simulasi Kualitas Stok (DEMO_ONLY)",
        source_type: "synthetic",
        source_url: null,
        is_synthetic: true,
        is_active: false,
        review_status: "reviewed",
        ingestion_metadata: {},
        created_at: "2026-11-20T00:00:00Z",
      },
      uses_batch_ledger: true,
      verified_count: 1,
      warning_count: 2,
      unknown_count: 1,
      quarantined_events_count: 1,
      approved_plan_alerts: [
        {
          menu_review_id: "rev-1",
          run_id: "run-1",
          title: "Menu Minggu 1",
          status: "APPROVED",
          requires_inventory_review: true,
          affected_ingredients: ["Daging Ayam Fillet: butuh 15.00 kg, siap pakai 12.00 kg"],
          summary_message:
            "Rencana 'Menu Minggu 1' tetap tersimpan dengan snapshot aslinya, namun memerlukan peninjauan ulang.",
        },
      ],
      items: [
        {
          id: "i-1",
          code: "ING007",
          name: "Daging Ayam Fillet",
          category: "protein",
          edible_fraction: 1.0,
          allergens: [],
          nutrients: {
            energy_kcal_100g: 165,
            protein_g_100g: 24,
            fat_g_100g: 7,
            carb_g_100g: 0,
            fiber_g_100g: 0,
            iron_mg_100g: 1.1,
          },
          price_idr_per_g: 44,
          original_price_value: 44000,
          original_price_unit: "IDR/kg",
          price_region: "SIMULASI",
          price_observed_at: "2026-11-19",
          price_source_type: "synthetic",
          price_provenance: "SYNTHETIC_EXAMPLE",
          stock_raw_g: 12000,
          recorded_raw_g: 20000,
          usable_raw_g: 12000,
          reserved_raw_g: 5000,
          unavailable_raw_g: 3000,
          incoming_raw_g: 8000,
          delivery_status: "PARTIAL",
          data_quality_status: "PARTIAL_OR_ADJUSTED",
          data_classification: "synthetic",
          availability_explanation:
            "Stok Daging Ayam Fillet tercatat 20.00 kg, tetapi hanya 12.00 kg yang dapat digunakan untuk produksi pada tanggal ini.",
          availability_warnings: [],
          market_references: [
            {
              commodity_name: "Daging Ayam Ras",
              region: "DKI Jakarta",
              observed_date: "2026-11-18",
              price_value: 39500,
              unit: "IDR/kg",
              source_name: "Bapanas Manual",
              price_provenance: "OFFICIAL_MARKET_REFERENCE",
            },
          ],
          source_type: "synthetic",
          source_ref: "GiziOptima Fixture",
          review_status: "reviewed",
        },
        {
          id: "i-2",
          code: "ING016",
          name: "Brokoli Segar",
          category: "vegetable",
          edible_fraction: 0.8,
          allergens: [],
          nutrients: {
            energy_kcal_100g: 34,
            protein_g_100g: 2.8,
            fat_g_100g: 0.4,
            carb_g_100g: 6.6,
            fiber_g_100g: 2.6,
            iron_mg_100g: 0.7,
          },
          price_idr_per_g: 28,
          original_price_value: 28000,
          original_price_unit: "IDR/kg",
          price_region: "SIMULASI",
          price_observed_at: "2026-11-19",
          price_source_type: "synthetic",
          price_provenance: "UNKNOWN",
          stock_raw_g: null,
          recorded_raw_g: 5000,
          usable_raw_g: null,
          unverified_raw_g: 5000,
          data_quality_status: "UNVERIFIED",
          data_classification: "synthetic",
          availability_explanation:
            "Lot Brokoli Segar belum memiliki tanggal kedaluwarsa terverifikasi.",
          availability_warnings: ["Tanggal kedaluwarsa belum tersedia"],
          market_references: [],
          source_type: "synthetic",
          source_ref: "GiziOptima Fixture",
          review_status: "needs_review",
        },
      ],
    }),
  },
}));

describe("Sprint 3A.6 Inventory Data Quality & Provenance UI", () => {
  it("displays recorded vs usable stock, non-green unverified state, and approved-plan review alert", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InventoryPage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByText(/Daging Ayam Fillet/i).length).toBeGreaterThan(0);
    });

    // Approved plan non-destructive alert is shown
    expect(screen.getByText(/Rencana Menu Disetujui Memerlukan Tinjauan Ulang/i)).toBeInTheDocument();

    // 20 kg recorded vs 12 kg usable explanation & reservation/delivery detail shown
    expect(
      screen.getAllByText(/tercatat 20\.00 kg, tetapi hanya 12\.00 kg yang dapat digunakan/i).length
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/Ref Pasar \(DKI Jakarta\)/i).length).toBeGreaterThan(0);

    // Unverified stock badge MUST NOT show green success status
    const unverifiedBadges = screen.getAllByText("Belum Terverifikasi");
    expect(unverifiedBadges.length).toBeGreaterThan(0);
    for (const badge of unverifiedBadges) {
      expect(badge.className).not.toContain("15803D");
      expect(badge.className).not.toContain("E7F6EC");
    }
  });
});
