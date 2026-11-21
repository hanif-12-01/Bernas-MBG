"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Eye,
  FileSpreadsheet,
  Info,
  Loader2,
  PackageCheck,
  Pencil,
  Search,
  ShieldAlert,
  UserCheck,
  X,
} from "lucide-react";

import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { IncidentPanel } from "@/components/incidents/IncidentPanel";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import { formatIDR, formatWeightFromGrams } from "@/lib/formatters/indonesian";
import {
  formatJakartaDate,
  formatJakartaDateTime,
  getJakartaTodayISO,
} from "@/lib/formatters/jakartaDate";
import type {
  InventoryCatalogItem,
  ManualStockAdjustmentTypeEnum,
} from "@/types/api";

function getPriorityStatus(item: InventoryCatalogItem): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
  needsAttention: boolean;
} {
  const dq = item.data_quality_status ?? "SYNTHETIC_BASELINE";
  if (
    dq === "SAFETY_HOLD" ||
    dq === "PARTIAL_SAFETY_HOLD" ||
    (item.safety_held_raw_g ?? 0) > 0 ||
    (item.rejected_disposed_raw_g ?? 0) > 0
  ) {
    return { label: "Ditahan Keamanan", tone: "critical", needsAttention: true };
  }
  if (dq === "UNKNOWN" || dq === "QUARANTINED" || dq === "UNVERIFIED") {
    return { label: "Perlu Verifikasi", tone: "warning", needsAttention: true };
  }
  if (item.days_until_nearest_expiry != null && item.days_until_nearest_expiry <= 3) {
    return { label: "Segera Kedaluwarsa", tone: "warning", needsAttention: true };
  }
  if (
    item.coverage?.coverage_status === "LOW_COVERAGE" ||
    item.coverage?.coverage_status === "EXPIRES_BEFORE_USE" ||
    (item.usable_raw_g !== null && item.usable_raw_g !== undefined && item.usable_raw_g < 10000)
  ) {
    return { label: "Stok Menipis", tone: "warning", needsAttention: true };
  }
  return { label: "Aman", tone: "success", needsAttention: false };
}

function InventoryContent() {
  const { user } = useAuth();
  const { datasets, activeDataset, refreshAll } = useWorkspace();
  const qc = useQueryClient();
  const searchParams = useSearchParams();

  const isCustodian = Boolean(user?.active_role === "QC_OFFICER" && user?.is_active_stock_custodian);
  const canSeePricing = user?.active_role !== "QC_OFFICER";
  const canImportCatalog = user?.active_role === "MENU_PLANNER";

  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("");
  const [productionDate, setProductionDate] = useState<string>(() => getJakartaTodayISO());
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "ATTENTION" | "SAFE">("ALL");

  const [showIncidentDrawer, setShowIncidentDrawer] = useState(
    () => searchParams.get("action") === "report-incident"
  );
  const [incidentLotCode, setIncidentLotCode] = useState<string | null>(null);
  const [detailCode, setDetailCode] = useState<string | null>(null);
  const [adjustTarget, setAdjustTarget] = useState<InventoryCatalogItem | null>(null);
  const [showAdvancedTools, setShowAdvancedTools] = useState(false);

  // Manual Adjustment Form State (Custodian QC only)
  const [adjType, setAdjType] = useState<ManualStockAdjustmentTypeEnum>("PURCHASE_RECEIPT");
  const [adjQty, setAdjQty] = useState<string>("5");
  const [adjUnit, setAdjUnit] = useState<string>("kg");
  const [adjLotCode, setAdjLotCode] = useState<string>("");
  const [adjSupplier, setAdjSupplier] = useState<string>("");
  const [adjExpiry, setAdjExpiry] = useState<string>("");
  const [adjNotes, setAdjNotes] = useState<string>("");
  const [adjFeedback, setAdjFeedback] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  // CSV Transaction Import State (Custodian QC only)
  const [txFile, setTxFile] = useState<File | null>(null);
  const [txClass, setTxClass] = useState<"synthetic" | "pilot_real">("pilot_real");
  const [txAuthorized, setTxAuthorized] = useState(true);
  const [txStatusMsg, setTxStatusMsg] = useState<string | null>(null);

  // Catalog Dataset Import State (Planner only)
  const [dsName, setDsName] = useState("Dataset Dapur Baru");
  const [dsFiles, setDsFiles] = useState<{
    ing?: File;
    price?: File;
    stock?: File;
    rec?: File;
  }>({});
  const [dsMsg, setDsMsg] = useState<string | null>(null);

  useEffect(() => {
    if (searchParams.get("action") === "report-incident") {
      setShowIncidentDrawer(true);
    }
  }, [searchParams]);

  const effectiveDatasetId = selectedDatasetId || activeDataset?.id || "";

  const invQuery = useQuery({
    queryKey: ["inventory", user?.active_kitchen_id, effectiveDatasetId, productionDate],
    queryFn: () =>
      apiClient.getInventory(effectiveDatasetId || undefined, productionDate || undefined),
    enabled: Boolean(user),
  });

  const detailQuery = useQuery({
    queryKey: [
      "inventory-detail",
      user?.active_kitchen_id,
      effectiveDatasetId,
      productionDate,
      detailCode,
    ],
    queryFn: () =>
      apiClient.getInventoryDetail(
        detailCode!,
        effectiveDatasetId || undefined,
        productionDate || undefined
      ),
    enabled: Boolean(user && detailCode),
  });

  const adjustMutation = useMutation({
    mutationFn: () => {
      if (!adjustTarget) throw new Error("Pilih bahan terlebih dahulu.");
      const parsed = Number(adjQty);
      if (!Number.isFinite(parsed) || parsed < 0) {
        throw new Error("Masukkan jumlah berat/kuantitas yang valid.");
      }
      return apiClient.recordInventoryAdjustment({
        dataset_version_id: invQuery.data?.dataset.id || effectiveDatasetId || undefined,
        ingredient_code: adjustTarget.code,
        lot_code: adjLotCode.trim() || undefined,
        adjustment_type: adjType,
        quantity: parsed,
        unit: adjUnit,
        expires_at: adjExpiry.trim() || undefined,
        supplier_name: adjSupplier.trim() || undefined,
        notes: adjNotes.trim() || undefined,
      });
    },
    onSuccess: (res) => {
      setAdjFeedback({ tone: "ok", text: res.message });
      setAdjLotCode("");
      setAdjNotes("");
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["inventory-detail"] });
      refreshAll?.();
    },
    onError: (err) => {
      setAdjFeedback({
        tone: "err",
        text: err instanceof ApiError || err instanceof Error ? err.message : "Gagal memperbarui stok.",
      });
    },
  });

  const txImportMutation = useMutation({
    mutationFn: async () => {
      if (!txFile) throw new Error("Pilih file CSV transaksi terlebih dahulu.");
      const fd = new FormData();
      fd.append("transactions_file", txFile);
      if (effectiveDatasetId) fd.append("dataset_version_id", effectiveDatasetId);
      fd.append("data_classification", txClass);
      fd.append("authorization_confirmed", txAuthorized ? "true" : "false");
      fd.append("dry_run", "false");
      return apiClient.importInventoryTransactions(fd);
    },
    onSuccess: (res) => {
      setTxStatusMsg(
        `Impor selesai: ${res.applied_count} diterapkan, ${res.duplicate_skipped_count} duplikat dilewati, ${res.quarantined_count} dikarantina.`
      );
      qc.invalidateQueries({ queryKey: ["inventory"] });
      refreshAll();
    },
    onError: (err) => {
      setTxStatusMsg(err instanceof Error ? err.message : "Gagal mengimpor CSV transaksi.");
    },
  });

  const dsImportMutation = useMutation({
    mutationFn: async () => {
      if (!dsFiles.ing || !dsFiles.price || !dsFiles.stock || !dsFiles.rec) {
        throw new Error("Lengkapi 4 berkas CSV (bahan, harga, stok, resep).");
      }
      const fd = new FormData();
      fd.append("name", dsName.trim() || "Dataset Dapur");
      fd.append("ingredients_file", dsFiles.ing);
      fd.append("prices_file", dsFiles.price);
      fd.append("stock_file", dsFiles.stock);
      fd.append("recipes_file", dsFiles.rec);
      return apiClient.importDatasetCsv(fd);
    },
    onSuccess: (res) => {
      setDsMsg(`Dataset "${res.name}" berhasil diimpor (${res.ingredients_imported} bahan).`);
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["inventory"] });
      refreshAll();
    },
    onError: (err) => {
      setDsMsg(err instanceof Error ? err.message : "Gagal mengimpor dataset.");
    },
  });

  const filteredItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (invQuery.data?.items ?? []).filter((item) => {
      const matchesQ =
        !q || item.name.toLowerCase().includes(q) || item.code.toLowerCase().includes(q);
      if (!matchesQ) return false;
      const st = getPriorityStatus(item);
      if (statusFilter === "ATTENTION") return st.needsAttention;
      if (statusFilter === "SAFE") return !st.needsAttention;
      return true;
    });
  }, [invQuery.data?.items, search, statusFilter]);

  if (invQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Stok Bahan Dapur" subtitle="Memuat stok siap pakai dan kedaluwarsa..." />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (invQuery.error || !invQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Stok Bahan Dapur" />
        <ErrorState
          message={invQuery.error?.message ?? "Gagal memuat data stok bahan."}
          onRetry={() => invQuery.refetch()}
        />
      </div>
    );
  }

  const invData = invQuery.data;
  const attentionCount = invData.items.filter((i) => getPriorityStatus(i).needsAttention).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Stok Bahan Dapur"
        subtitle="Pantau stok siap pakai, tanggal kedaluwarsa terdekat, dan perkiraan kecukupan sesuai rencana menu aktif."
        badges={
          <DatasetSimulationNotice
            compact
            simulationOnly={invData.dataset.is_synthetic}
            datasetName={invData.dataset.name}
          />
        }
        actions={
          isCustodian ? (
            <button
              type="button"
              onClick={() => {
                setIncidentLotCode(null);
                setShowIncidentDrawer((v) => !v);
              }}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-700"
            >
              <ShieldAlert className="h-4 w-4" />
              {showIncidentDrawer ? "Tutup Form Penahanan" : "Laporkan Bahan Bermasalah"}
            </button>
          ) : undefined
        }
      />

      {/* Single Authoritative Custodian Status Banner */}
      <div
        className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-xs ${
          isCustodian
            ? "border-emerald-200 bg-emerald-50/80 text-emerald-950"
            : "border-slate-200 bg-white text-slate-700"
        }`}
        data-testid="custodian-authority-banner"
      >
        <div className="flex items-center gap-2">
          <UserCheck
            className={`h-4 w-4 shrink-0 ${isCustodian ? "text-emerald-700" : "text-slate-500"}`}
          />
          <div>
            {isCustodian ? (
              <span>
                <strong>Wewenang Aktif:</strong> Anda ditugaskan sebagai{" "}
                <strong>Petugas QC Pengelola Stok</strong> untuk memperbarui stok & menahan bahan bermasalah.
              </span>
            ) : user?.stock_custodian?.is_assigned ? (
              <span>
                <strong>Mode Lihat Saja:</strong> Pengelola Stok aktif saat ini adalah{" "}
                <strong>{user.stock_custodian.custodian_full_name}</strong>.
              </span>
            ) : (
              <span>
                <strong>Belum Ada Pengelola Stok Aktif:</strong> Kepala Dapur perlu menunjuk 1 Petugas QC sebelum perubahan stok dapat dicatat.
              </span>
            )}
          </div>
        </div>
        {isCustodian && (
          <Link
            href="/shopping-list?tab=receipts"
            className="font-semibold text-emerald-800 underline hover:text-emerald-950"
          >
            Catat Penerimaan Barang Baru →
          </Link>
        )}
      </div>

      {/* Approved Plan Re-review Alerts */}
      {invData.approved_plan_alerts && invData.approved_plan_alerts.length > 0 && (
        <div
          role="alert"
          className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-xs text-amber-950"
        >
          <div className="flex items-center gap-2 font-bold text-amber-950">
            <AlertTriangle className="h-4 w-4 text-amber-700" />
            Rencana Menu Disetujui Membutuhkan Penyesuaian Stok ({invData.approved_plan_alerts.length})
          </div>
          <ul className="mt-1.5 list-disc space-y-1 pl-5">
            {invData.approved_plan_alerts.map((al) => (
              <li key={al.menu_review_id}>
                <strong>{al.title}</strong>: {al.summary_message}
              </li>
            ))}
          </ul>
          {user?.active_role === "MENU_PLANNER" && (
            <Link
              href="/simulator"
              className="mt-2 inline-block font-semibold text-amber-900 underline"
            >
              Atasi di Pemulihan Menu →
            </Link>
          )}
        </div>
      )}

      {/* Incident Drawer (Only rendered for active Stock Custodian QC when opened) */}
      {showIncidentDrawer && isCustodian && (
        <IncidentPanel
          defaultDatasetId={effectiveDatasetId}
          preselectedLotCode={incidentLotCode}
          onIncidentChanged={() => {
            qc.invalidateQueries({ queryKey: ["inventory"] });
            qc.invalidateQueries({ queryKey: ["inventory-detail"] });
          }}
        />
      )}

      {/* Filter & Date Toolbar */}
      <div className="grid grid-cols-1 gap-3 rounded-xl border border-[#DCE6DE] bg-white p-4 sm:grid-cols-4">
        <div className="sm:col-span-2">
          <label className="block text-[11px] font-semibold text-[#4A6170]">Cari Bahan</label>
          <div className="relative mt-1">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Contoh: Ayam, Beras, Bayam..."
              className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm"
            />
          </div>
        </div>
        <div>
          <label htmlFor="inv-prod-date" className="block text-[11px] font-semibold text-[#4A6170]">
            Tanggal Masak (WIB)
          </label>
          <input
            id="inv-prod-date"
            type="date"
            value={productionDate}
            onChange={(e) => setProductionDate(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-[11px] font-semibold text-[#4A6170]">Sumber Data</label>
          <select
            value={effectiveDatasetId}
            onChange={(e) => setSelectedDatasetId(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-4">
          <button
            type="button"
            onClick={() => setStatusFilter("ALL")}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              statusFilter === "ALL"
                ? "bg-[#0F766E] text-white"
                : "border border-slate-300 bg-white text-slate-700"
            }`}
          >
            Semua ({invData.items.length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("ATTENTION")}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              statusFilter === "ATTENTION"
                ? "bg-amber-600 text-white"
                : "border border-slate-300 bg-white text-slate-700"
            }`}
          >
            Perlu Perhatian ({attentionCount})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("SAFE")}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              statusFilter === "SAFE"
                ? "bg-emerald-700 text-white"
                : "border border-slate-300 bg-white text-slate-700"
            }`}
          >
            Aman ({invData.items.length - attentionCount})
          </button>
        </div>
      </div>

      {/* Quick Custodian Adjustment Modal / Card */}
      {adjustTarget && isCustodian && (
        <div className="rounded-xl border border-[#0F766E] bg-[#F4FAF9] p-4 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-bold text-[#16354A]">
              Perbarui Stok: {adjustTarget.name} ({adjustTarget.code})
            </h3>
            <button
              type="button"
              onClick={() => {
                setAdjustTarget(null);
                setAdjFeedback(null);
              }}
              className="rounded-md p-1 text-slate-500 hover:bg-white"
              aria-label="Tutup form pembaruan stok"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {adjFeedback && (
            <div
              className={`mt-2 rounded-lg border px-3 py-2 text-xs ${
                adjFeedback.tone === "ok"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                  : "border-rose-200 bg-rose-50 text-rose-900"
              }`}
            >
              {adjFeedback.text}
            </div>
          )}
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div>
              <label className="block text-[11px] font-semibold text-slate-700">Jenis Pembaruan</label>
              <select
                value={adjType}
                onChange={(e) => setAdjType(e.target.value as ManualStockAdjustmentTypeEnum)}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              >
                <option value="PURCHASE_RECEIPT">Barang Masuk / Belanja</option>
                <option value="USAGE_CONSUMPTION">Pemakaian Masak</option>
                <option value="SPOILAGE_DAMAGE">Bahan Rusak / Susut</option>
                <option value="STOCK_OPNAME_COUNT">Hitung Ulang Fisik (Opname)</option>
                <option value="STOCK_CORRECTION">Koreksi Saldo Lot</option>
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700">Jumlah & Satuan</label>
              <div className="mt-1 flex gap-1.5">
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  value={adjQty}
                  onChange={(e) => setAdjQty(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
                />
                <select
                  value={adjUnit}
                  onChange={(e) => setAdjUnit(e.target.value)}
                  className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs"
                >
                  <option value="kg">kg</option>
                  <option value="g">g</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700">Kode Lot</label>
              <input
                type="text"
                value={adjLotCode}
                onChange={(e) => setAdjLotCode(e.target.value)}
                placeholder={adjustTarget.lots?.[0]?.lot_code ?? "Otomatis jika baru"}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700">Kedaluwarsa (opsional)</label>
              <input
                type="date"
                value={adjExpiry}
                onChange={(e) => setAdjExpiry(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700">Pemasok (opsional)</label>
              <input
                type="text"
                value={adjSupplier}
                onChange={(e) => setAdjSupplier(e.target.value)}
                placeholder="Nama pemasok nyata"
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700">Catatan</label>
              <input
                type="text"
                value={adjNotes}
                onChange={(e) => setAdjNotes(e.target.value)}
                placeholder="Keterangan singkat..."
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs"
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => adjustMutation.mutate()}
              disabled={adjustMutation.isPending}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
            >
              {adjustMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <PackageCheck className="h-3.5 w-3.5" />
              )}
              Simpan Pembaruan Stok
            </button>
          </div>
        </div>
      )}

      {/* Clean Prioritized 6-Fact Ingredient List */}
      {filteredItems.length === 0 ? (
        <EmptyState
          title="Tidak ada bahan sesuai pencarian"
          description="Coba ubah kata kunci atau filter status di atas."
        />
      ) : (
        <div className="space-y-2.5" data-testid="inventory-list">
          {filteredItems.map((item) => {
            const st = getPriorityStatus(item);
            const isExpanded = detailCode === item.code;
            const cleanLots = (item.lots ?? []).filter((l) => l.safety_hold_status === "NONE");

            return (
              <div
                key={item.id}
                className="rounded-xl border border-[#DCE6DE] bg-white p-4 shadow-[0_1px_2px_rgba(22,53,74,0.03)]"
              >
                <div className="grid grid-cols-1 items-center gap-3 md:grid-cols-12">
                  {/* 1. Nama Bahan & 3. Status */}
                  <div className="md:col-span-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-bold text-[#16354A]">{item.name}</span>
                      <StatusBadge label={st.label} tone={st.tone} />
                    </div>
                    <div className="mt-0.5 text-[11px] text-[#647A87]">
                      {item.code} · {item.category}
                    </div>
                  </div>

                  {/* 2. Stok Siap Pakai */}
                  <div className="md:col-span-2">
                    <div className="text-[11px] text-[#647A87]">Stok Siap Pakai</div>
                    <div className="text-base font-bold text-[#16354A] tabular-nums">
                      {item.usable_raw_g === null || item.usable_raw_g === undefined
                        ? "Belum tercatat"
                        : formatWeightFromGrams(item.usable_raw_g)}
                    </div>
                  </div>

                  {/* 4. Kedaluwarsa Terdekat */}
                  <div className="md:col-span-2">
                    <div className="text-[11px] text-[#647A87]">Kedaluwarsa Terdekat</div>
                    <div className="text-xs font-semibold text-slate-800">
                      {item.nearest_expiry_at ? formatJakartaDate(item.nearest_expiry_at) : "Belum dicatat"}
                    </div>
                    {item.days_until_nearest_expiry != null && (
                      <div className="text-[11px] text-[#647A87]">
                        {item.days_until_nearest_expiry >= 0
                          ? `Sisa ${item.days_until_nearest_expiry} hari`
                          : "Sudah melewati tanggal"}
                      </div>
                    )}
                  </div>

                  {/* 5. Perkiraan Kecukupan FEFO */}
                  <div className="md:col-span-3">
                    <div className="text-[11px] text-[#647A87]">Perkiraan Kecukupan</div>
                    <div className="text-xs font-medium text-slate-800">
                      {item.coverage?.human_summary_id ?? "Belum dapat diperkirakan"}
                    </div>
                  </div>

                  {/* 6. Aksi Sesuai Peran */}
                  <div className="flex flex-wrap justify-start gap-1.5 md:col-span-2 md:justify-end">
                    <button
                      type="button"
                      onClick={() => setDetailCode(isExpanded ? null : item.code)}
                      className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      <Eye className="h-3.5 w-3.5" />
                      {isExpanded ? "Tutup" : "Lihat Rincian"}
                    </button>
                    {isCustodian && (
                      <>
                        <button
                          type="button"
                          onClick={() => {
                            setAdjustTarget(item);
                            setAdjLotCode(cleanLots[0]?.lot_code ?? "");
                            setAdjFeedback(null);
                          }}
                          className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-[#B5DFDA] bg-[#EBF6F5] px-2.5 py-1 text-xs font-semibold text-[#0F766E] hover:bg-[#DDF0EE]"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                          Perbarui
                        </button>
                        {cleanLots.length > 0 && (
                          <button
                            type="button"
                            onClick={() => {
                              setIncidentLotCode(cleanLots[0].lot_code);
                              setShowIncidentDrawer(true);
                            }}
                            className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-100"
                          >
                            <ShieldAlert className="h-3.5 w-3.5" />
                            Laporkan
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* Expandable Detail Drawer */}
                {isExpanded && (
                  <div className="mt-4 space-y-3 border-t border-slate-200 pt-3 text-xs">
                    {detailQuery.isLoading ? (
                      <div className="flex items-center gap-2 text-slate-500">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Memuat rincian lot...
                      </div>
                    ) : detailQuery.data ? (
                      <>
                        {detailQuery.data.ingredient.availability_explanation && (
                          <p className="rounded-lg bg-slate-50 px-3 py-2 text-slate-700">
                            {detailQuery.data.ingredient.availability_explanation}
                          </p>
                        )}

                        {detailQuery.data.ingredient.coverage && (
                          <p className="flex items-start gap-1.5 text-[11px] text-slate-500">
                            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
                            {detailQuery.data.ingredient.coverage.disclaimer}
                          </p>
                        )}

                        <div>
                          <h4 className="font-bold text-slate-900">
                            Rincian Batch / Lot ({detailQuery.data.ingredient.lots?.length ?? 0})
                          </h4>
                          {(detailQuery.data.ingredient.lots?.length ?? 0) === 0 ? (
                            <p className="mt-1 text-slate-500">Belum ada catatan lot terpisah.</p>
                          ) : (
                            <div className="mt-1.5 overflow-x-auto">
                              <table className="w-full border-collapse text-left text-[11px]">
                                <thead>
                                  <tr className="border-b border-slate-200 text-slate-500">
                                    <th className="py-1.5 pr-3">Kode Lot</th>
                                    <th className="py-1.5 pr-3">Pemasok</th>
                                    <th className="py-1.5 pr-3">Diterima</th>
                                    <th className="py-1.5 pr-3">Kedaluwarsa</th>
                                    <th className="py-1.5 pr-3">Siap Pakai</th>
                                    <th className="py-1.5">Status</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {detailQuery.data.ingredient.lots!.map((l) => (
                                    <tr key={l.id} className="border-b border-slate-100">
                                      <td className="py-1.5 pr-3 font-mono font-semibold">{l.lot_code}</td>
                                      <td className="py-1.5 pr-3">{l.supplier_name ?? "Belum dicatat"}</td>
                                      <td className="py-1.5 pr-3">
                                        {l.received_at ? formatJakartaDateTime(l.received_at) : "Belum dicatat"}
                                      </td>
                                      <td className="py-1.5 pr-3">
                                        {l.expiry_known && l.expires_at
                                          ? formatJakartaDate(l.expires_at)
                                          : "Belum dicatat"}
                                      </td>
                                      <td className="py-1.5 pr-3 font-semibold">
                                        {formatWeightFromGrams(l.usable_raw_g)}
                                      </td>
                                      <td className="py-1.5">
                                        {l.safety_hold_status !== "NONE"
                                          ? l.safety_hold_status
                                          : l.verification_status}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>

                        {detailQuery.data.recent_movements.length > 0 && (
                          <div>
                            <h4 className="font-bold text-slate-900">Riwayat Mutasi Terakhir</h4>
                            <ul className="mt-1 space-y-1 text-[11px] text-slate-600">
                              {detailQuery.data.recent_movements.slice(0, 5).map((m) => (
                                <li key={m.id}>
                                  {formatJakartaDateTime(m.event_at)} · <strong>{m.movement_type}</strong>{" "}
                                  ({m.original_value} {m.original_unit})
                                  {m.lot_code ? ` · Lot ${m.lot_code}` : ""}
                                  {m.actor_name ? ` · oleh ${m.actor_name}` : ""}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {canSeePricing && detailQuery.data.ingredient.original_price_value != null && (
                          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-700">
                            <strong>Harga Referensi Katalog:</strong>{" "}
                            {formatIDR(detailQuery.data.ingredient.original_price_value)} /{" "}
                            {detailQuery.data.ingredient.original_price_unit ?? "kg"}
                            {detailQuery.data.ingredient.market_references &&
                              detailQuery.data.ingredient.market_references.length > 0 && (
                                <span className="ml-2 text-slate-500">
                                  · Ref Pasar ({detailQuery.data.ingredient.market_references[0].region}):{" "}
                                  {formatIDR(detailQuery.data.ingredient.market_references[0].price_value)}/
                                  {detailQuery.data.ingredient.market_references[0].unit}
                                </span>
                              )}
                          </div>
                        )}
                      </>
                    ) : null}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Collapsible Advanced CSV Tools gated strictly by role */}
      {(isCustodian || canImportCatalog) && (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <button
            type="button"
            onClick={() => setShowAdvancedTools((v) => !v)}
            className="flex w-full items-center justify-between text-xs font-bold text-slate-700"
          >
            <span className="inline-flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-slate-500" />
              Alat Lanjutan: Impor Data CSV
            </span>
            {showAdvancedTools ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>

          {showAdvancedTools && (
            <div className="mt-4 grid gap-4 border-t border-slate-200 pt-4 sm:grid-cols-2">
              {isCustodian && (
                <div className="space-y-2 rounded-lg border border-slate-200 p-3 text-xs">
                  <div className="font-bold text-slate-900">Impor Transaksi Lot (CSV)</div>
                  <a
                    href={apiClient.getInventoryTemplateUrl("pilot-transactions")}
                    className="inline-block text-[#0F766E] underline"
                  >
                    Unduh Templat CSV Transaksi
                  </a>
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    onChange={(e) => setTxFile(e.target.files?.[0] ?? null)}
                    className="block w-full text-xs"
                  />
                  <div className="flex items-center gap-2">
                    <select
                      value={txClass}
                      onChange={(e) => setTxClass(e.target.value as "synthetic" | "pilot_real")}
                      className="rounded border border-slate-300 px-2 py-1 text-xs"
                    >
                      <option value="pilot_real">Dapur Nyata (Pilot)</option>
                      <option value="synthetic">Simulasi (DEMO_ONLY)</option>
                    </select>
                    <label className="flex items-center gap-1 text-[11px]">
                      <input
                        type="checkbox"
                        checked={txAuthorized}
                        onChange={(e) => setTxAuthorized(e.target.checked)}
                      />
                      Terotorisasi
                    </label>
                  </div>
                  <button
                    type="button"
                    onClick={() => txImportMutation.mutate()}
                    disabled={txImportMutation.isPending}
                    className="rounded-lg bg-[#0F766E] px-3 py-1.5 font-semibold text-white"
                  >
                    Unggah CSV Transaksi
                  </button>
                  {txStatusMsg && <p className="text-slate-700">{txStatusMsg}</p>}
                </div>
              )}

              {canImportCatalog && (
                <div className="space-y-2 rounded-lg border border-slate-200 p-3 text-xs">
                  <div className="font-bold text-slate-900">Impor Paket Dataset Menu Baru</div>
                  <input
                    type="text"
                    value={dsName}
                    onChange={(e) => setDsName(e.target.value)}
                    placeholder="Nama dataset"
                    className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                  />
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <label>
                      ingredients.csv
                      <input
                        type="file"
                        accept=".csv"
                        onChange={(e) =>
                          setDsFiles((p) => ({ ...p, ing: e.target.files?.[0] }))
                        }
                      />
                    </label>
                    <label>
                      prices.csv
                      <input
                        type="file"
                        accept=".csv"
                        onChange={(e) =>
                          setDsFiles((p) => ({ ...p, price: e.target.files?.[0] }))
                        }
                      />
                    </label>
                    <label>
                      stock.csv
                      <input
                        type="file"
                        accept=".csv"
                        onChange={(e) =>
                          setDsFiles((p) => ({ ...p, stock: e.target.files?.[0] }))
                        }
                      />
                    </label>
                    <label>
                      recipes.csv
                      <input
                        type="file"
                        accept=".csv"
                        onChange={(e) =>
                          setDsFiles((p) => ({ ...p, rec: e.target.files?.[0] }))
                        }
                      />
                    </label>
                  </div>
                  <button
                    type="button"
                    onClick={() => dsImportMutation.mutate()}
                    disabled={dsImportMutation.isPending}
                    className="rounded-lg bg-slate-800 px-3 py-1.5 font-semibold text-white"
                  >
                    Impor Paket Dataset
                  </button>
                  {dsMsg && <p className="text-slate-700">{dsMsg}</p>}
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default function InventoryPage() {
  return (
    <Suspense fallback={<LoadingSkeleton rows={4} />}>
      <InventoryContent />
    </Suspense>
  );
}
