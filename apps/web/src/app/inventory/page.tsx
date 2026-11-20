"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock, PackageCheck, Search, Truck, Upload } from "lucide-react";

import {
  AccessDeniedState,
  ErrorState,
  LoadingSkeleton,
} from "@/components/feedback/FeedbackStates";
import { IncidentPanel } from "@/components/incidents/IncidentPanel";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient } from "@/lib/api/client";
import {
  formatCategoryLabel,
  formatDateID,
  formatDateTimeID,
  formatDecimal,
  formatIDR,
  formatPercent,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";
import type { InventoryCatalogItem, PriceProvenanceEnum } from "@/types/api";

function getQualityBadge(item: InventoryCatalogItem): {
  tone: "success" | "warning" | "critical" | "neutral" | "teal";
  label: string;
} {
  const st = item.data_quality_status || "UNKNOWN";
  if (st === "VERIFIED") {
    return item.data_classification === "synthetic"
      ? { tone: "neutral", label: "Batch Simulasi Terverifikasi" }
      : { tone: "success", label: "Terverifikasi" };
  }
  if (st === "SYNTHETIC_BASELINE") {
    return { tone: "warning", label: "Simulasi (DEMO_ONLY)" };
  }
  if (st === "PARTIAL_OR_ADJUSTED") {
    return { tone: "warning", label: "Sebagian / Penyesuaian" };
  }
  if (st === "DISCREPANCY") {
    return { tone: "warning", label: "Selisih Fisik" };
  }
  if (st === "UNVERIFIED") {
    return { tone: "warning", label: "Belum Terverifikasi" };
  }
  if (st === "QUARANTINED") {
    return { tone: "critical", label: "Dikarantina" };
  }
  if (st === "SAFETY_HOLD") {
    return { tone: "critical", label: "Ditahan Keamanan (SAFETY HOLD)" };
  }
  if (st === "PARTIAL_SAFETY_HOLD") {
    return { tone: "critical", label: "Sebagian Lot Ditahan" };
  }
  return { tone: "critical", label: "Belum Diketahui (UNKNOWN)" };
}

function formatPriceProvenanceLabel(prov?: PriceProvenanceEnum): string {
  switch (prov) {
    case "ACTUAL_SUPPLIER":
      return "Harga Pemasok Nyata";
    case "OFFICIAL_MARKET_REFERENCE":
      return "Referensi Pasar Resmi";
    case "SYNTHETIC_EXAMPLE":
      return "Contoh Harga Simulasi";
    default:
      return "Sumber Tidak Diketahui";
  }
}

export default function InventoryPage() {
  const { user } = useAuth();
  if (user && user.active_role === "QC_OFFICER") {
    return (
      <div className="space-y-6">
        <PageHeader title="Bahan & Stok" />
        <AccessDeniedState
          title="Inventaris Tidak Tersedia untuk Petugas QC"
          description="Peran Petugas QC difokuskan pada pemeriksaan visual sampel makanan dan tidak mengakses data harga atau inventaris pengadaan."
        />
      </div>
    );
  }
  return <InventoryContent />;
}

function InventoryContent() {
  const { user } = useAuth();
  const isPlanner = user?.active_role === "MENU_PLANNER";
  const { datasets, activeDataset } = useWorkspace();
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
  const [productionDate, setProductionDate] = useState<string>("2026-11-20");
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [onlyWarnings, setOnlyWarnings] = useState(false);

  const effectiveDatasetId = selectedDatasetId || activeDataset?.id || "";
  const prodIso = productionDate ? `${productionDate}T08:00:00Z` : undefined;

  const invQuery = useQuery({
    queryKey: ["inventory", effectiveDatasetId, prodIso],
    queryFn: () => apiClient.getInventory(effectiveDatasetId || undefined, prodIso),
    enabled: Boolean(effectiveDatasetId) || datasets.length === 0,
  });

  const invData = invQuery.data;
  const items = invData?.items ?? [];
  const datasetMeta = invData?.dataset;
  const approvedAlerts = invData?.approved_plan_alerts ?? [];

  const categories = useMemo(
    () => Array.from(new Set(items.map((i) => i.category))).sort(),
    [items]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      if (categoryFilter !== "all" && item.category !== categoryFilter) return false;
      if (onlyWarnings) {
        const hasWarn =
          (item.availability_warnings?.length ?? 0) > 0 ||
          (item.unavailable_raw_g ?? 0) > 0 ||
          (item.reserved_raw_g ?? 0) > 0 ||
          (item.incoming_raw_g ?? 0) > 0 ||
          ["UNKNOWN", "UNVERIFIED", "DISCREPANCY", "QUARANTINED", "PARTIAL_OR_ADJUSTED"].includes(
            item.data_quality_status ?? ""
          );
        if (!hasWarn) return false;
      }
      if (!q) return true;
      return (
        item.name.toLowerCase().includes(q) ||
        item.code.toLowerCase().includes(q) ||
        formatCategoryLabel(item.category).toLowerCase().includes(q)
      );
    });
  }, [items, search, categoryFilter, onlyWarnings]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bahan & Stok"
        subtitle="Pantau stok siap pakai untuk tanggal produksi, alokasi terpesan, pengiriman tertunda, dan acuan harga tanpa mencampur data simulasi dengan data nyata."
        badges={
          <DatasetSimulationNotice compact simulationOnly={datasetMeta?.is_synthetic ?? true} />
        }
        actions={
          <Link
            href="/settings"
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] px-4 py-2.5 text-sm font-semibold text-[#0F766E] hover:bg-[#DDF0EE]"
          >
            <Upload className="h-4 w-4" aria-hidden="true" />
            <span>Impor CSV / Transaksi</span>
          </Link>
        }
      />

      <DatasetSimulationNotice
        simulationOnly={datasetMeta?.is_synthetic ?? true}
        datasetName={datasetMeta?.name}
      />

      {/* Non-destructive Approved Plan Review Alerts */}
      {approvedAlerts.length > 0 && (
        <div
          role="alert"
          className="rounded-2xl border border-[#F3D19B] bg-[#FFFBEB] p-4 text-xs text-[#8A5300]"
        >
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#B45309]" aria-hidden="true" />
            <div className="space-y-1.5">
              <p className="text-sm font-bold text-[#92400E]">
                Rencana Menu Disetujui Memerlukan Tinjauan Ulang ({approvedAlerts.length})
              </p>
              {approvedAlerts.map((al) => (
                <div key={al.menu_review_id} className="flex flex-wrap items-center gap-2 leading-relaxed">
                  <span>{al.summary_message}</span>
                  <Link href={`/menu-planning?run=${al.run_id}`} className="font-bold underline">
                    Tinjau Rencana
                  </Link>
                  {isPlanner && (
                    <Link
                      href={`/simulator?baselineRun=${al.run_id}&reviewId=${al.menu_review_id}`}
                      data-testid={`alert-recover-${al.run_id}`}
                      className="inline-flex min-h-[34px] items-center rounded-lg bg-[#92400E] px-2.5 py-1 text-xs font-bold text-white hover:bg-[#78350F]"
                    >
                      Atasi Gangguan
                    </Link>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Compact Data Quality Summary Strip */}
      {invData && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl border border-[#DCE6DE] bg-white p-3">
            <p className="text-[11px] font-medium text-[#647A87]">Stok Terverifikasi</p>
            <p className="mt-1 text-lg font-bold text-[#16354A] tabular-nums">
              {invData.verified_count ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-[#F3D19B] bg-[#FFFDF7] p-3">
            <p className="text-[11px] font-medium text-[#8A5300]">Penyesuaian / Peringatan</p>
            <p className="mt-1 text-lg font-bold text-[#92400E] tabular-nums">
              {invData.warning_count ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-[#F5C2C2] bg-[#FFF8F8] p-3">
            <p className="text-[11px] font-medium text-[#991B1B]">Belum Diketahui</p>
            <p className="mt-1 text-lg font-bold text-[#991B1B] tabular-nums">
              {invData.unknown_count ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-[#DCE6DE] bg-white p-3">
            <p className="text-[11px] font-medium text-[#647A87]">Catatan Dikarantina</p>
            <p className="mt-1 text-lg font-bold text-[#16354A] tabular-nums">
              {invData.quarantined_events_count ?? 0}
            </p>
          </div>
        </div>
      )}

      {/* Operational Safety Hold & Compromised Ingredient Reporting (Sprint 3C) */}
      <IncidentPanel defaultDatasetId={effectiveDatasetId} compact />

      {/* Filter Bar */}
      <div className="grid grid-cols-1 gap-3 rounded-2xl border border-[#DCE6DE] bg-white p-4 md:grid-cols-4">
        <div>
          <label htmlFor="inv-search" className="block text-xs font-semibold text-[#4A6170]">
            Cari Bahan
          </label>
          <div className="relative mt-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#647A87]"
              aria-hidden="true"
            />
            <input
              id="inv-search"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Nama atau kode bahan..."
              className="h-10 w-full rounded-xl border border-[#DCE6DE] bg-white pl-9 pr-3 text-sm text-[#16354A]"
            />
          </div>
        </div>

        <div>
          <label htmlFor="inv-cat" className="block text-xs font-semibold text-[#4A6170]">
            Kategori Bahan
          </label>
          <select
            id="inv-cat"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="mt-1 h-10 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
          >
            <option value="all">Semua Kategori ({items.length})</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {formatCategoryLabel(cat)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="inv-ds" className="block text-xs font-semibold text-[#4A6170]">
            Versi Dataset
          </label>
          <select
            id="inv-ds"
            value={effectiveDatasetId}
            onChange={(e) => setSelectedDatasetId(e.target.value)}
            className="mt-1 h-10 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
          >
            {datasets.map((ds) => (
              <option key={ds.id} value={ds.id}>
                {ds.name} {ds.is_active ? "(Aktif)" : "(Tersimpan)"}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="inv-prod-date" className="block text-xs font-semibold text-[#4A6170]">
            Tanggal Produksi Acuan
          </label>
          <input
            id="inv-prod-date"
            type="date"
            value={productionDate}
            onChange={(e) => setProductionDate(e.target.value)}
            className="mt-1 h-10 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
          />
          <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-[#4A6170]">
            <input
              type="checkbox"
              checked={onlyWarnings}
              onChange={(e) => setOnlyWarnings(e.target.checked)}
              className="h-4 w-4 accent-[#0F766E]"
            />
            <span>Hanya item dengan penyesuaian / peringatan</span>
          </label>
        </div>
      </div>

      {invQuery.isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : invQuery.isError ? (
        <ErrorState
          message={(invQuery.error as Error).message}
          onRetry={() => invQuery.refetch()}
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-[#DCE6DE] bg-white shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          {/* Mobile Cards (320px / 375px / 390px) */}
          <ul className="space-y-2.5 p-3 md:hidden" aria-label="Daftar bahan dan stok">
            {filtered.map((item) => {
              const qBadge = getQualityBadge(item);
              const usableLabel =
                item.usable_raw_g !== null && item.usable_raw_g !== undefined
                  ? formatWeightFromGrams(item.usable_raw_g)
                  : "Tidak Diketahui";
              const recordedLabel =
                item.recorded_raw_g !== null && item.recorded_raw_g !== undefined
                  ? formatWeightFromGrams(item.recorded_raw_g)
                  : "—";
              return (
                <li key={item.id} className="rounded-xl border border-[#DCE6DE] p-3.5 space-y-2.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="break-words text-sm font-bold text-[#16354A]">{item.name}</h3>
                      <p className="text-xs text-[#647A87]">
                        {item.code} • {formatCategoryLabel(item.category)}
                      </p>
                    </div>
                    <StatusBadge tone={qBadge.tone} label={qBadge.label} />
                  </div>

                  <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                    <div>
                      <dt className="text-[#647A87]">Stok Siap Pakai</dt>
                      <dd className="font-bold text-[#16354A]">{usableLabel}</dd>
                    </div>
                    <div>
                      <dt className="text-[#647A87]">Tercatat di Buku</dt>
                      <dd className="font-semibold text-[#4A6170]">{recordedLabel}</dd>
                    </div>
                    {(item.safety_held_raw_g ?? 0) > 0 && (
                      <div className="col-span-2">
                        <dt className="text-[#991B1B] font-semibold">Ditahan Keamanan (SAFETY HOLD)</dt>
                        <dd className="font-bold text-[#991B1B]">
                          {formatWeightFromGrams(item.safety_held_raw_g ?? 0)}
                          {(item.held_lot_codes?.length ?? 0) > 0
                            ? ` (${item.held_lot_codes!.join(", ")})`
                            : ""}
                        </dd>
                      </div>
                    )}
                    {(item.reserved_raw_g ?? 0) > 0 && (
                      <div>
                        <dt className="text-[#647A87]">Dialokasikan</dt>
                        <dd className="font-semibold text-[#92400E]">
                          {formatWeightFromGrams(item.reserved_raw_g ?? 0)}
                        </dd>
                      </div>
                    )}
                    {(item.unavailable_raw_g ?? 0) > 0 && (
                      <div>
                        <dt className="text-[#647A87]">Tidak Tersedia</dt>
                        <dd className="font-semibold text-[#991B1B]">
                          {formatWeightFromGrams(item.unavailable_raw_g ?? 0)}
                        </dd>
                      </div>
                    )}
                    {(item.incoming_raw_g ?? 0) > 0 && (
                      <div className="col-span-2">
                        <dt className="text-[#647A87]">Pengiriman Pemasok ({item.delivery_status})</dt>
                        <dd className="font-semibold text-[#8A5300]">
                          {formatWeightFromGrams(item.incoming_raw_g ?? 0)} belum tiba (tidak masuk stok siap pakai)
                        </dd>
                      </div>
                    )}
                    <div>
                      <dt className="text-[#647A87]">Acuan Harga</dt>
                      <dd className="font-semibold">
                        {item.original_price_value === null
                          ? "Belum tersedia"
                          : `${formatIDR(item.original_price_value)} / ${
                              item.original_price_unit?.replace("IDR/", "") ?? "kg"
                            }`}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[#647A87]">Provenance Harga</dt>
                      <dd className="text-[#4A6170]">
                        {formatPriceProvenanceLabel(item.price_provenance)}
                      </dd>
                    </div>
                  </dl>

                  {item.availability_explanation && (
                    <p className="rounded-lg bg-[#F5F8F5] px-2.5 py-2 text-xs leading-relaxed text-[#334E5E]">
                      {item.availability_explanation}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[#647A87]">
                    <span>Sumber: {item.source_ref}</span>
                    {item.last_verified_at && (
                      <span>Verifikasi: {formatDateTimeID(item.last_verified_at)}</span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          {/* Desktop Table */}
          <div className="hidden max-w-full overflow-x-auto md:block">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-[#DCE6DE] bg-[#F5F8F5] text-[#4A6170]">
                <tr>
                  <th className="px-4 py-3 font-semibold">Bahan Pangan & Sumber</th>
                  <th className="px-4 py-3 font-semibold">Harga & Provenance</th>
                  <th className="px-4 py-3 text-right font-semibold">Siap Pakai vs Tercatat</th>
                  <th className="px-4 py-3 font-semibold">Rincian Kualitas & Pengiriman</th>
                  <th className="px-4 py-3 text-right font-semibold">Gizi / 100g & BDD</th>
                  <th className="px-4 py-3 font-semibold">Status Stok</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EEF3EE]">
                {filtered.map((item) => {
                  const qBadge = getQualityBadge(item);
                  const usableLabel =
                    item.usable_raw_g !== null && item.usable_raw_g !== undefined
                      ? formatWeightFromGrams(item.usable_raw_g)
                      : "Tidak Diketahui";
                  const recordedDiff =
                    item.recorded_raw_g !== null &&
                    item.recorded_raw_g !== undefined &&
                    item.usable_raw_g !== null &&
                    item.usable_raw_g !== undefined &&
                    Math.abs(item.recorded_raw_g - item.usable_raw_g) > 1;
                  return (
                    <tr key={item.id} className="align-top hover:bg-[#F5F8F5]/60">
                      <td className="px-4 py-3">
                        <span className="block font-semibold text-[#16354A]">{item.name}</span>
                        <span className="block text-[11px] text-[#647A87]">
                          {item.code} • {formatCategoryLabel(item.category)}
                          {item.allergens.length > 0 ? ` • Alergen: ${item.allergens.join(", ")}` : ""}
                        </span>
                        <span className="mt-1 block text-[11px] text-[#526675]">
                          Sumber: {item.source_ref}
                        </span>
                      </td>

                      <td className="px-4 py-3 tabular-nums">
                        <span className="block font-semibold text-[#16354A]">
                          {item.original_price_value !== null
                            ? `${formatIDR(item.original_price_value)} / ${
                                item.original_price_unit?.replace("IDR/", "") ?? "kg"
                              }`
                            : "Belum tersedia"}
                        </span>
                        <span className="block text-[11px] text-[#526675]">
                          {formatPriceProvenanceLabel(item.price_provenance)}
                        </span>
                        <span className="block text-[11px] text-[#647A87]">
                          {item.price_observed_at ? formatDateID(item.price_observed_at) : "—"}
                        </span>
                        {item.market_references && item.market_references.length > 0 && (
                          <span className="mt-1 block rounded bg-[#EBF6F5] px-1.5 py-0.5 text-[10px] text-[#0F766E]">
                            Ref Pasar ({item.market_references[0].region}):{" "}
                            {formatIDR(item.market_references[0].price_value)}/kg
                          </span>
                        )}
                      </td>

                      <td className="px-4 py-3 text-right tabular-nums">
                        <span className="block text-sm font-bold text-[#16354A]">
                          {usableLabel}
                        </span>
                        {recordedDiff && (
                          <span className="block text-[11px] text-[#647A87]">
                            Tercatat: {formatWeightFromGrams(item.recorded_raw_g ?? 0)}
                          </span>
                        )}
                        {item.physical_raw_g !== null && item.physical_raw_g !== undefined && (
                          <span className="block text-[11px] text-[#526675]">
                            Hitung Fisik: {formatWeightFromGrams(item.physical_raw_g)}
                          </span>
                        )}
                      </td>

                      <td className="max-w-xs px-4 py-3 text-[11px] text-[#334E5E]">
                        {item.availability_explanation && (
                          <p className="leading-relaxed">{item.availability_explanation}</p>
                        )}
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {(item.safety_held_raw_g ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-1 rounded bg-[#991B1B] px-1.5 py-0.5 font-semibold text-white">
                              Ditahan Keamanan: {formatWeightFromGrams(item.safety_held_raw_g ?? 0)}
                              {(item.held_lot_codes?.length ?? 0) > 0
                                ? ` (${item.held_lot_codes!.join(", ")})`
                                : ""}
                            </span>
                          )}
                          {(item.rejected_disposed_raw_g ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-1 rounded bg-[#334E5E] px-1.5 py-0.5 font-medium text-white">
                              Dimusnahkan: {formatWeightFromGrams(item.rejected_disposed_raw_g ?? 0)}
                            </span>
                          )}
                          {(item.reserved_raw_g ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-1 rounded bg-[#FEF3C7] px-1.5 py-0.5 font-medium text-[#92400E]">
                              <PackageCheck className="h-3 w-3" aria-hidden="true" />
                              Dialokasikan: {formatWeightFromGrams(item.reserved_raw_g ?? 0)}
                            </span>
                          )}
                          {(item.unavailable_raw_g ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-1 rounded bg-[#FEE2E2] px-1.5 py-0.5 font-medium text-[#991B1B]">
                              Tidak tersedia: {formatWeightFromGrams(item.unavailable_raw_g ?? 0)}
                            </span>
                          )}
                          {(item.incoming_raw_g ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-1 rounded bg-[#E0F2FE] px-1.5 py-0.5 font-medium text-[#075985]">
                              <Truck className="h-3 w-3" aria-hidden="true" />
                              Menunggu ({item.delivery_status}):{" "}
                              {formatWeightFromGrams(item.incoming_raw_g ?? 0)}
                            </span>
                          )}
                        </div>
                        {item.last_verified_at && (
                          <span className="mt-1 inline-flex items-center gap-1 text-[10px] text-[#647A87]">
                            <Clock className="h-3 w-3" aria-hidden="true" />
                            Diverifikasi: {formatDateTimeID(item.last_verified_at)}
                          </span>
                        )}
                      </td>

                      <td className="px-4 py-3 text-right text-[#4A6170] tabular-nums">
                        <div>
                          BDD: <strong>{formatPercent(item.edible_fraction * 100, 0)}</strong>
                        </div>
                        <div>
                          Energi:{" "}
                          <strong className="text-[#16354A]">
                            {formatDecimal(item.nutrients.energy_kcal_100g, 0)}
                          </strong>{" "}
                          kkal
                        </div>
                        <div>
                          Protein:{" "}
                          <strong className="text-[#16354A]">
                            {formatDecimal(item.nutrients.protein_g_100g, 1)}
                          </strong>{" "}
                          g
                        </div>
                      </td>

                      <td className="px-4 py-3">
                        <StatusBadge tone={qBadge.tone} label={qBadge.label} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {filtered.length === 0 && (
            <p className="p-6 text-center text-sm text-[#647A87]">
              Tidak ada bahan yang cocok dengan filter yang dipilih.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
