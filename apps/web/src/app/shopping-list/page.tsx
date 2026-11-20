"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpDown,
  CheckCircle2,
  Download,
  Info,
  Search,
  SlidersHorizontal,
} from "lucide-react";

import {
  AccessDeniedState,
  EmptyState,
  ErrorState,
  LoadingSkeleton,
} from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatIDR,
  formatPercent,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";

export default function ShoppingListPage() {
  const { user } = useAuth();
  if (user && user.active_role === "QC_OFFICER") {
    return (
      <div className="space-y-6">
        <PageHeader title="Daftar Belanja" />
        <AccessDeniedState
          title="Daftar Belanja Tidak Tersedia untuk Petugas QC"
          description="Daftar belanja pengadaan hanya dapat diakses oleh Perencana Menu dan Kepala Dapur."
        />
      </div>
    );
  }
  return <ShoppingListContent />;
}

function ShoppingListContent() {
  const { user } = useAuth();
  const {
    selectedRun,
    selectedScenario,
    isLoadingList,
    isLoadingRun,
    refreshAll,
  } = useWorkspace();

  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"qty_desc" | "name_asc" | "cost_desc">("qty_desc");
  const [exportMessage, setExportMessage] = useState<{ tone: "ok" | "err"; text: string } | null>(
    null
  );
  const [isExporting, setIsExporting] = useState(false);

  const recoveryEventsQuery = useQuery({
    queryKey: ["recovery-events"],
    queryFn: apiClient.listRecoveryEvents,
    enabled: Boolean(selectedRun),
  });

  const matchedRecovery = useMemo(() => {
    if (!selectedRun || !recoveryEventsQuery.data) return null;
    return (
      recoveryEventsQuery.data.find(
        (ev) =>
          ev.selected_run_id === selectedRun.run_id ||
          ev.min_disruption.run_id === selectedRun.run_id ||
          ev.min_cost.run_id === selectedRun.run_id
      ) ?? null
    );
  }, [selectedRun, recoveryEventsQuery.data]);

  const shoppingQuery = useQuery({
    queryKey: ["shopping-list", selectedRun?.run_id],
    queryFn: () => apiClient.getShoppingList(selectedRun!.run_id),
    enabled: Boolean(selectedRun?.run_id && selectedRun?.validation_passed),
    retry: 0,
  });

  const pricesPerG = selectedRun?.input_snapshot?.prices_idr_per_g ?? {};

  const enrichedItems = useMemo(() => {
    const raw = shoppingQuery.data ?? [];
    const mapped = raw.map((item) => {
      const priceG = pricesPerG[item.ingredient_code] ?? null;
      const estimatedCost = priceG !== null ? item.used_raw_g * priceG : null;
      const remainingAfterUse = item.available_raw_g - item.used_raw_g;
      const additionalPurchaseG = Math.max(0, item.used_raw_g - item.available_raw_g);
      const utilPct =
        item.available_raw_g > 0 ? (item.used_raw_g / item.available_raw_g) * 100 : null;
      return {
        ...item,
        pricePerKg: priceG !== null ? priceG * 1000 : null,
        estimatedCost,
        remainingAfterUse,
        additionalPurchaseG,
        utilPct,
      };
    });

    const q = search.trim().toLowerCase();
    const filtered = q
      ? mapped.filter(
          (i) =>
            i.ingredient_name.toLowerCase().includes(q) ||
            i.ingredient_code.toLowerCase().includes(q)
        )
      : mapped;

    return filtered.sort((a, b) => {
      if (sortBy === "name_asc") return a.ingredient_name.localeCompare(b.ingredient_name, "id");
      if (sortBy === "cost_desc") return (b.estimatedCost ?? 0) - (a.estimatedCost ?? 0);
      return b.used_raw_g - a.used_raw_g;
    });
  }, [shoppingQuery.data, pricesPerG, search, sortBy]);

  const handleExportCsv = async () => {
    if (!selectedRun) return;
    setIsExporting(true);
    setExportMessage(null);
    try {
      const { blob, filename } = await apiClient.downloadRunCsv(selectedRun.run_id);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      setExportMessage({
        tone: "ok",
        text: `Berhasil mengunduh file ${filename} (termasuk penanda data simulasi).`,
      });
    } catch (err) {
      setExportMessage({
        tone: "err",
        text: err instanceof ApiError ? err.message : "Gagal mengekspor CSV dari server.",
      });
    } finally {
      setIsExporting(false);
    }
  };

  if (isLoadingList || isLoadingRun) {
    return (
      <div className="space-y-6">
        <PageHeader title="Daftar Belanja" />
        <LoadingSkeleton rows={5} />
      </div>
    );
  }

  if (!selectedRun || !selectedRun.validation_passed) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Daftar Belanja"
          subtitle="Rekap kebutuhan bahan mentah dari rencana menu yang sudah lolos verifikasi kelayakan."
        />
        <EmptyState
          title="Daftar Belanja Belum Tersedia"
          description="Daftar belanja dan ekspor CSV hanya dapat dibuat untuk rencana menu yang lolos verifikasi seluruh batasan."
          action={
            <Link
              href="/simulator"
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58]"
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
              <span>Buka Simulator</span>
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Daftar Belanja"
        subtitle={`${selectedScenario?.name ?? "Rencana Aktif"} • ${
          selectedRun.days_count ?? selectedRun.days.length
        } hari × ${
          selectedRun.servings_per_day ?? selectedScenario?.servings_per_day ?? "—"
        } porsi/hari${
          selectedRun.total_servings
            ? ` = ${selectedRun.total_servings.toLocaleString("id-ID")} total porsi`
            : ""
        } • Total ${formatIDR(selectedRun.objective_total_idr)}`}
        badges={<DatasetSimulationNotice compact simulationOnly={selectedRun.simulation_only} />}
        actions={
          <button
            type="button"
            disabled={isExporting}
            onClick={handleExportCsv}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            <span>{isExporting ? "Menyiapkan CSV..." : "Ekspor CSV Rencana"}</span>
          </button>
        }
      />

      <DatasetSimulationNotice simulationOnly={selectedRun.simulation_only} />

      {exportMessage && (
        <div
          role={exportMessage.tone === "err" ? "alert" : "status"}
          className={`flex items-center gap-2.5 rounded-xl border px-4 py-3 text-sm ${
            exportMessage.tone === "ok"
              ? "border-[#BBE9CC] bg-[#ECFDF3] text-[#166534]"
              : "border-[#F5C2C2] bg-[#FEF0F0] text-[#991B1B]"
          }`}
        >
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{exportMessage.text}</span>
        </div>
      )}

      {/* Recovery Procurement Delta Banner (when plan originates from disruption recovery) */}
      {matchedRecovery && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#B5DFDA] bg-[#F4FAF9] px-4 py-3 text-xs text-[#16354A]">
          <div className="space-y-0.5">
            <p className="font-bold text-[#0F766E]">
              Terkait Pemulihan Gangguan: {matchedRecovery.title}
            </p>
            <p className="text-[#4A6170]">{matchedRecovery.disruption_summary}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={apiClient.getRecoveryProcurementCsvUrl(
                matchedRecovery.id,
                matchedRecovery.min_cost.run_id === selectedRun.run_id
                  ? "MIN_COST"
                  : "MIN_DISRUPTION"
              )}
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg bg-[#0F766E] px-3 py-1.5 font-semibold text-white hover:bg-[#0B5F58]"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Unduh CSV Delta Belanja Pemulihan</span>
            </a>
            {user?.active_role === "MENU_PLANNER" && (
              <Link
                href={`/simulator?eventId=${matchedRecovery.id}`}
                className="inline-flex min-h-[38px] items-center gap-1 rounded-lg border border-[#B5DFDA] bg-white px-3 py-1.5 font-semibold text-[#0F766E]"
              >
                <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Buka Pemulihan</span>
              </Link>
            )}
          </div>
        </div>
      )}

      {/* Clarification Banner */}
      <div className="flex items-start gap-2.5 rounded-xl border border-[#DCE6DE] bg-white px-4 py-3 text-xs text-[#4A6170]">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
        <p className="leading-relaxed">
          <strong className="text-[#16354A]">Perbedaan Total Kebutuhan vs Tambahan Beli:</strong>{" "}
          <em>Total Kebutuhan</em> adalah seluruh berat bahan mentah yang dipakai selama rencana.
          Karena seluruh kebutuhan berada dalam batas stok tersedia pada skenario ini, kolom{" "}
          <em>Tambahan Pembelian Mendesak</em> menunjukkan kekurangan terhadap stok tercatat (0 bila
          stok mencukupi). Daftar ini merupakan alat bantu perencanaan, <strong>bukan</strong>{" "}
          pemesanan resmi ke pemasok.
        </p>
      </div>

      {/* Search & Sort Controls */}
      <div className="flex flex-col gap-3 rounded-2xl border border-[#DCE6DE] bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 sm:max-w-xs">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#647A87]"
            aria-hidden="true"
          />
          <label htmlFor="shop-search" className="sr-only">
            Cari bahan belanja
          </label>
          <input
            id="shop-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Cari bahan belanja..."
            className="h-10 w-full rounded-xl border border-[#DCE6DE] bg-white pl-9 pr-3 text-sm text-[#16354A]"
          />
        </div>

        <div className="flex items-center gap-2">
          <ArrowUpDown className="h-4 w-4 text-[#647A87]" aria-hidden="true" />
          <label htmlFor="shop-sort" className="text-xs font-semibold text-[#4A6170]">
            Urutkan:
          </label>
          <select
            id="shop-sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="h-10 rounded-xl border border-[#DCE6DE] bg-white px-3 text-xs font-semibold text-[#16354A]"
          >
            <option value="qty_desc">Kebutuhan Terbanyak</option>
            <option value="cost_desc">Estimasi Biaya Tertinggi</option>
            <option value="name_asc">Nama Bahan (A–Z)</option>
          </select>
        </div>
      </div>

      {shoppingQuery.isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : shoppingQuery.isError ? (
        <ErrorState
          message={(shoppingQuery.error as Error).message}
          onRetry={() => {
            shoppingQuery.refetch();
            refreshAll();
          }}
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-[#DCE6DE] bg-white shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="p-3 md:hidden">
            <ul className="space-y-2" aria-label="Kebutuhan bahan per item">
              {enrichedItems.map((item) => (
                <li key={item.ingredient_code} className="rounded-xl border border-[#DCE6DE] p-3">
                  <h3 className="break-words text-sm font-bold">{item.ingredient_name}</h3>
                  <p className="text-xs text-[#647A87]">{item.ingredient_code} • Pemakaian stok {formatPercent(item.utilPct, 0)}</p>
                  <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                    <div><dt className="text-[#647A87]">Total kebutuhan</dt><dd className="font-semibold">{formatWeightFromGrams(item.used_raw_g)}</dd></div>
                    <div><dt className="text-[#647A87]">Stok tercatat</dt><dd>{formatWeightFromGrams(item.available_raw_g)}</dd></div>
                    <div><dt className="text-[#647A87]">Tambahan beli</dt><dd>{item.additionalPurchaseG > 0 ? formatWeightFromGrams(item.additionalPurchaseG) : "0 gram (Cukup)"}</dd></div>
                    <div><dt className="text-[#647A87]">Harga acuan</dt><dd>{item.pricePerKg !== null ? `${formatIDR(item.pricePerKg)}/kg` : "—"}</dd></div>
                    <div><dt className="text-[#647A87]">Estimasi biaya</dt><dd className="font-semibold text-[#0F766E]">{formatIDR(item.estimatedCost)}</dd></div>
                  </dl>
                </li>
              ))}
            </ul>
            <p className="mt-3 rounded-xl bg-[#F5F8F5] p-3 text-sm font-semibold">
              Total estimasi ({selectedRun.days.length} hari) <span className="block text-[#0F766E]">{formatIDR(selectedRun.objective_total_idr)}</span>
            </p>
          </div>
          <div className="hidden max-w-full overflow-x-auto md:block">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-[#DCE6DE] bg-[#F5F8F5] text-[#4A6170]">
                <tr>
                  <th className="px-4 py-3 font-semibold">Bahan Pangan</th>
                  <th className="px-4 py-3 text-right font-semibold">Total Kebutuhan</th>
                  <th className="px-4 py-3 text-right font-semibold">Stok Tercatat</th>
                  <th className="px-4 py-3 text-right font-semibold">Tambahan Beli</th>
                  <th className="px-4 py-3 text-right font-semibold">Harga Acuan</th>
                  <th className="px-4 py-3 text-right font-semibold">Estimasi Biaya</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EEF3EE] tabular-nums">
                {enrichedItems.map((m) => (
                  <tr key={m.ingredient_code} className="hover:bg-[#F5F8F5]/60">
                    <td className="px-4 py-3">
                      <span className="block font-semibold text-[#16354A]">
                        {m.ingredient_name}
                      </span>
                      <span className="text-[11px] text-[#647A87]">
                        {m.ingredient_code} • Pemakaian stok {formatPercent(m.utilPct, 0)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-[#16354A]">
                      {formatWeightFromGrams(m.used_raw_g)}
                    </td>
                    <td className="px-4 py-3 text-right text-[#4A6170]">
                      {formatWeightFromGrams(m.available_raw_g)}
                    </td>
                    <td className="px-4 py-3 text-right text-[#4A6170]">
                      {m.additionalPurchaseG > 0
                        ? formatWeightFromGrams(m.additionalPurchaseG)
                        : "0 gram (Cukup)"}
                    </td>
                    <td className="px-4 py-3 text-right text-[#4A6170]">
                      {m.pricePerKg !== null ? `${formatIDR(m.pricePerKg)}/kg` : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-[#0F766E]">
                      {formatIDR(m.estimatedCost)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t border-[#DCE6DE] bg-[#F5F8F5] font-bold text-[#16354A] tabular-nums">
                <tr>
                  <td colSpan={5} className="px-4 py-3 text-right">
                    Total Estimasi Biaya Pengadaan ({selectedRun.days.length} Hari)
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-[#0F766E]">
                    {formatIDR(selectedRun.objective_total_idr)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
