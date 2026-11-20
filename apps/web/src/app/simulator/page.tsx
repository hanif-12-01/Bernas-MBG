"use client";

import React, { Suspense, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Loader2,
  Play,
  RotateCcw,
  Search,
  Sparkles,
} from "lucide-react";

import {
  AccessDeniedState,
  EmptyState,
  ErrorState,
  LoadingSkeleton,
} from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { RecoveryWorkspace } from "@/components/recovery/RecoveryWorkspace";
import { ScenarioComparison } from "@/components/simulator/ScenarioComparison";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { NumericInput } from "@/components/ui/NumericInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatCategoryLabel,
  formatIDR,
  formatRunStatus,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";
import {
  formatNumericDisplay,
  parseNumericInput,
  type NumericParseResult,
} from "@/lib/formatters/numericInput";
import type {
  OptimizationRunResponse,
  PriceOverrideEntry,
  ScenarioComparisonResponse,
  StockOverrideEntry,
} from "@/types/api";

export default function SimulatorPage() {
  const { user } = useAuth();
  if (user && user.active_role !== "MENU_PLANNER") {
    return (
      <div className="space-y-6">
        <PageHeader title="Atasi Gangguan Bahan" />
        <AccessDeniedState
          title="Khusus Perencana Menu"
          description="Hanya peran Perencana Menu (MENU_PLANNER) yang diizinkan mengelola pemulihan gangguan, simulasi harga/stok, dan optimasi menu."
        />
      </div>
    );
  }
  return (
    <Suspense fallback={<LoadingSkeleton rows={4} />}>
      <SimulatorModeShell />
    </Suspense>
  );
}

function SimulatorModeShell() {
  const searchParams = useSearchParams();
  const initialModeParam = searchParams.get("mode") === "whatif" ? "whatif" : "recovery";
  const [activeTab, setActiveTab] = useState<"recovery" | "whatif">(initialModeParam);
  const baselineRun = searchParams.get("baselineRun");
  const reviewId = searchParams.get("reviewId");
  const ingredient = searchParams.get("ingredient");
  const eventId = searchParams.get("eventId");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#DCE6DE] bg-white p-3">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Mode Simulasi dan Pemulihan">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "recovery"}
            onClick={() => setActiveTab("recovery")}
            className={`min-h-[40px] rounded-xl px-4 py-2 text-xs font-bold transition ${
              activeTab === "recovery"
                ? "bg-[#0F766E] text-white"
                : "border border-[#DCE6DE] bg-[#F5F8F5] text-[#4A6170] hover:bg-[#EBF6F5]"
            }`}
          >
            Pemulihan Gangguan (Minim Perubahan)
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "whatif"}
            onClick={() => setActiveTab("whatif")}
            className={`min-h-[40px] rounded-xl px-4 py-2 text-xs font-bold transition ${
              activeTab === "whatif"
                ? "bg-[#0F766E] text-white"
                : "border border-[#DCE6DE] bg-[#F5F8F5] text-[#4A6170] hover:bg-[#EBF6F5]"
            }`}
          >
            Simulasi Bebas (What-If)
          </button>
        </div>
        <span className="text-[11px] text-[#647A87]">
          Rencana yang sudah disetujui tetap aman tersimpan di riwayat terpisah.
        </span>
      </div>

      {activeTab === "recovery" ? (
        <div className="space-y-6">
          <PageHeader
            title="Atasi Gangguan Bahan"
            subtitle="Identifikasi slot menu yang terdampak kekurangan stok/pengiriman/harga, bandingkan Alternatif A (Minim Perubahan) vs Alternatif B (Biaya Minimum), dan ajukan rencana pengganti ke Kepala Dapur."
          />
          <RecoveryWorkspace
            initialBaselineRunId={baselineRun}
            initialReviewId={reviewId}
            initialIngredientCode={ingredient}
            initialEventId={eventId}
          />
        </div>
      ) : (
        <SimulatorContent />
      )}
    </div>
  );
}

function SimulatorContent() {
  const router = useRouter();
  const qc = useQueryClient();
  const {
    runs,
    scenarios,
    selectedRunId,
    setSelectedRunId,
    isLoadingList,
    listError,
    refreshAll,
  } = useWorkspace();

  const validatedRuns = useMemo(() => runs.filter((r) => r.validation_passed), [runs]);
  const [baselineRunId, setBaselineRunId] = useState<string>("");

  const effectiveBaselineId =
    baselineRunId && validatedRuns.some((r) => r.run_id === baselineRunId)
      ? baselineRunId
      : validatedRuns.find((r) => r.run_id === selectedRunId)?.run_id ??
        validatedRuns[0]?.run_id ??
        "";

  const baseRunQuery = useQuery({
    queryKey: ["run", effectiveBaselineId],
    queryFn: () => apiClient.getRun(effectiveBaselineId),
    enabled: Boolean(effectiveBaselineId),
  });

  const baseRun = baseRunQuery.data;
  const baseScenario = scenarios.find((s) => s.id === baseRun?.scenario_id);

  const inventoryQuery = useQuery({
    queryKey: ["inventory", baseRun?.dataset_version_id],
    queryFn: () => apiClient.getInventory(baseRun?.dataset_version_id),
    enabled: Boolean(baseRun?.dataset_version_id),
  });

  const [simName, setSimName] = useState("Simulasi Perubahan Harga & Stok");
  const [search, setSearch] = useState("");
  const [priceInputs, setPriceInputs] = useState<Record<string, string>>({});
  const [stockInputs, setStockInputs] = useState<Record<string, string>>({});
  const [blurredFields, setBlurredFields] = useState<Record<string, boolean>>({});
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [resultRun, setResultRun] = useState<OptimizationRunResponse | null>(null);
  const [resultComparison, setResultComparison] = useState<ScenarioComparisonResponse | null>(null);
  const [resultName, setResultName] = useState<string>("");

  const inventoryItems = inventoryQuery.data?.items ?? [];

  const basePricesKgMap = useMemo(() => {
    const snapPrices = baseRun?.input_snapshot?.prices_idr_per_g ?? {};
    const map: Record<string, number> = {};
    for (const item of inventoryItems) {
      const perG = snapPrices[item.code] ?? item.price_idr_per_g ?? 0;
      map[item.code] = Math.round(perG * 1000);
    }
    return map;
  }, [baseRun, inventoryItems]);

  const baseStockKgMap = useMemo(() => {
    const snapStock = baseRun?.input_snapshot?.stock_raw_g ?? {};
    const map: Record<string, number> = {};
    for (const item of inventoryItems) {
      const rawG = snapStock[item.code] ?? item.stock_raw_g ?? 0;
      map[item.code] = Number((rawG / 1000).toFixed(3));
    }
    return map;
  }, [baseRun, inventoryItems]);

  const filteredItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return inventoryItems;
    return inventoryItems.filter(
      (i) =>
        i.name.toLowerCase().includes(q) ||
        i.code.toLowerCase().includes(q) ||
        formatCategoryLabel(i.category).toLowerCase().includes(q)
    );
  }, [inventoryItems, search]);

  const parsedPriceMap = useMemo(() => {
    const map: Record<string, NumericParseResult> = {};
    for (const [code, raw] of Object.entries(priceInputs)) {
      map[code] = parseNumericInput(raw, {
        mode: "integer",
        min: 1,
        minErrorMessage: "Harga minimal Rp1/kg sesuai aturan sistem.",
      });
    }
    return map;
  }, [priceInputs]);

  const parsedStockMap = useMemo(() => {
    const map: Record<string, NumericParseResult> = {};
    for (const [code, raw] of Object.entries(stockInputs)) {
      map[code] = parseNumericInput(raw, {
        mode: "decimal",
        min: 0,
        minErrorMessage: "Stok tidak boleh negatif.",
      });
    }
    return map;
  }, [stockInputs]);

  const pendingPriceChanges = useMemo(() => {
    const changes: Array<[string, number]> = [];
    for (const [code, result] of Object.entries(parsedPriceMap)) {
      if (result.valid && Math.abs(result.value - (basePricesKgMap[code] ?? 0)) > 0.01) {
        changes.push([code, result.value]);
      }
    }
    return changes;
  }, [parsedPriceMap, basePricesKgMap]);

  const pendingStockChanges = useMemo(() => {
    const changes: Array<[string, number]> = [];
    for (const [code, result] of Object.entries(parsedStockMap)) {
      if (result.valid && Math.abs(result.value - (baseStockKgMap[code] ?? 0)) > 0.001) {
        changes.push([code, result.value]);
      }
    }
    return changes;
  }, [parsedStockMap, baseStockKgMap]);

  const invalidPriceCodes = useMemo(
    () => Object.entries(parsedPriceMap).filter(([, res]) => !res.valid).map(([code]) => code),
    [parsedPriceMap]
  );

  const invalidStockCodes = useMemo(
    () => Object.entries(parsedStockMap).filter(([, res]) => !res.valid).map(([code]) => code),
    [parsedStockMap]
  );

  const invalidInputCount = invalidPriceCodes.length + invalidStockCodes.length;
  const totalPendingChanges = pendingPriceChanges.length + pendingStockChanges.length;
  const hasAnyDraftInput =
    Object.keys(priceInputs).length > 0 || Object.keys(stockInputs).length > 0;

  const resetEdits = () => {
    setPriceInputs({});
    setStockInputs({});
    setBlurredFields({});
    setRunError(null);
  };

  // Illustrative presets (clearly labeled as examples, NOT real market data)
  const applyPreset = (preset: "egg20" | "egg100" | "tempeLow" | "infeasibleStock") => {
    setRunError(null);
    setBlurredFields({});
    if (preset === "egg20") {
      const base = basePricesKgMap["ING006"] ?? 28000;
      setPriceInputs({ ING006: formatNumericDisplay(Math.round(base * 1.2), "integer") });
      setStockInputs({});
      setSimName("Simulasi: Harga Telur Naik 20%");
    } else if (preset === "egg100") {
      const base = basePricesKgMap["ING006"] ?? 28000;
      setPriceInputs({ ING006: formatNumericDisplay(Math.round(base * 2.0), "integer") });
      setStockInputs({});
      setSimName("Simulasi: Lonjakan Harga Telur +100%");
    } else if (preset === "tempeLow") {
      setPriceInputs({});
      setStockInputs({ ING009: formatNumericDisplay(7.5, "decimal") });
      setSimName("Simulasi: Stok Tempe Terbatas (7,5 kg)");
    } else if (preset === "infeasibleStock") {
      setPriceInputs({});
      setStockInputs({
        ING001: "0",
        ING002: "0",
        ING003: "0",
        ING004: "0",
        ING005: "0",
      });
      setSimName("Uji Tidak Layak: Stok Bahan Pokok Habis");
    }
  };

  const handleRunSimulation = async () => {
    if (!baseRun || !baseScenario) return;
    setRunError(null);

    if (invalidInputCount > 0) {
      setRunError(
        `Terdapat ${invalidInputCount} input angka yang belum valid. Perbaiki kolom bertanda merah sebelum menghitung ulang menu.`
      );
      return;
    }

    // Double-check numeric constraints before sending to backend
    for (const [code, val] of pendingPriceChanges) {
      if (!Number.isFinite(val) || val <= 0) {
        setRunError(`Harga bahan ${code} harus lebih dari Rp0/kg.`);
        return;
      }
    }
    for (const [code, val] of pendingStockChanges) {
      if (!Number.isFinite(val) || val < 0) {
        setRunError(`Stok bahan ${code} tidak boleh negatif.`);
        return;
      }
    }

    setIsRunning(true);
    try {
      const cleanName = simName.trim() || `${baseScenario.name} (Simulasi)`;
      // Step 1: Clone baseline scenario (baseline remains immutable)
      const cloned = await apiClient.cloneScenario(baseScenario.id, cleanName);

      // Step 2: Apply price overrides if any
      if (pendingPriceChanges.length > 0) {
        const overrides: PriceOverrideEntry[] = pendingPriceChanges.map(([code, priceKg]) => ({
          ingredient_code: code,
          price_value: priceKg,
          unit: "IDR/kg",
        }));
        await apiClient.patchPriceOverrides(cloned.id, overrides);
      }

      // Step 3: Apply stock overrides if any
      if (pendingStockChanges.length > 0) {
        const overrides: StockOverrideEntry[] = pendingStockChanges.map(([code, stockKg]) => ({
          ingredient_code: code,
          stock_raw_g: Math.round(stockKg * 1000),
        }));
        await apiClient.patchStockOverrides(cloned.id, overrides);
      }

      // Step 4: Execute real backend optimization
      const newRun = await apiClient.optimizeScenario(cloned.id);

      // Step 5: Fetch authoritative comparison from backend
      const comparison = await apiClient.compareRuns(baseRun.run_id, newRun.run_id);

      setResultRun(newRun);
      setResultComparison(comparison);
      setResultName(cleanName);

      qc.invalidateQueries({ queryKey: ["scenarios"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.setQueryData(["run", newRun.run_id], newRun);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
          ? err.message
          : "Terjadi kesalahan saat menjalankan simulasi.";
      setRunError(msg);
    } finally {
      setIsRunning(false);
    }
  };

  if (isLoadingList) {
    return (
      <div className="space-y-6">
        <PageHeader title="Simulasi Harga & Stok" />
        <LoadingSkeleton rows={5} />
      </div>
    );
  }

  if (listError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Simulasi Harga & Stok" />
        <ErrorState message={listError.message} onRetry={refreshAll} />
      </div>
    );
  }

  if (validatedRuns.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Simulasi Harga & Stok"
          subtitle="Uji dampak kenaikan harga atau berkurangnya pasokan bahan pangan tanpa mengubah rencana awal."
        />
        <EmptyState
          title="Belum Ada Rencana Awal yang Layak"
          description="Buat rencana menu yang lolos validasi untuk dijadikan acuan simulasi perubahan harga atau stok."
          action={
            <Link
              href="/menu-planning?new=1"
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58]"
            >
              Buat Rencana Menu
            </Link>
          }
        />
      </div>
    );
  }

  const baseStatus = formatRunStatus(baseRun?.solver_status, baseRun?.validation_passed);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Simulasi Harga & Stok"
        subtitle="Ubah harga atau ketersediaan stok bahan pangan, lalu hitung ulang kombinasi menu terverifikasi untuk melihat dampaknya terhadap biaya dan susunan menu."
        badges={<DatasetSimulationNotice compact simulationOnly={baseRun?.simulation_only ?? true} />}
      />

      {/* Step 1 — Select Baseline */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-[#0F766E]">
              Langkah 1
            </span>
            <h2 className="text-base font-bold text-[#16354A]">
              Pilih Rencana Awal (Baseline)
            </h2>
          </div>
          {baseRun && <StatusBadge tone={baseStatus.tone} label={baseStatus.shortLabel} />}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div>
            <label htmlFor="baseline-select" className="block text-xs font-semibold text-[#4A6170]">
              Rencana Pembanding
            </label>
            <select
              id="baseline-select"
              value={effectiveBaselineId}
              onChange={(e) => {
                setBaselineRunId(e.target.value);
                resetEdits();
                setResultComparison(null);
                setResultRun(null);
              }}
              className="mt-1.5 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm font-medium text-[#16354A]"
            >
              {validatedRuns.map((r) => {
                const sc = scenarios.find((s) => s.id === r.scenario_id);
                return (
                  <option key={r.run_id} value={r.run_id}>
                    {sc?.name ?? `Skenario ${r.scenario_id.slice(0, 6)}`} (
                    {formatIDR(r.cost_per_serving_average_idr)}/porsi)
                  </option>
                );
              })}
            </select>
          </div>

          {baseRun && (
            <div className="grid grid-cols-2 gap-3 rounded-xl border border-[#EEF3EE] bg-[#F5F8F5] p-3 text-xs sm:grid-cols-3 lg:col-span-2">
              <div>
                <span className="block text-[#647A87]">Total Biaya Awal</span>
                <strong className="mt-0.5 block text-sm text-[#16354A] tabular-nums">
                  {formatIDR(baseRun.objective_total_idr)}
                </strong>
              </div>
              <div>
                <span className="block text-[#647A87]">Rata-rata / Porsi</span>
                <strong className="mt-0.5 block text-sm text-[#16354A] tabular-nums">
                  {formatIDR(baseRun.cost_per_serving_average_idr)}
                </strong>
              </div>
              <div>
                <span className="block text-[#647A87]">Horizon & Porsi</span>
                <strong className="mt-0.5 block text-sm text-[#16354A]">
                  {baseScenario?.days ?? baseRun.days.length} hari ×{" "}
                  {baseScenario?.servings_per_day ?? 100} porsi
                </strong>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Step 2 — Modify Conditions */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-[#0F766E]">
              Langkah 2
            </span>
            <h2 className="text-base font-bold text-[#16354A]">
              Ubah Harga atau Ketersediaan Stok Bahan
            </h2>
            <p className="mt-0.5 text-xs text-[#647A87]">
              Perubahan tidak langsung disimpan hingga Anda menekan tombol{" "}
              <strong>Hitung Ulang Menu</strong>. Rencana awal tetap aman dan tidak berubah.
            </p>
          </div>

          {(totalPendingChanges > 0 || hasAnyDraftInput) && (
            <button
              type="button"
              onClick={resetEdits}
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl border border-[#DCE6DE] px-3 py-1.5 text-xs font-semibold text-[#4A6170] hover:bg-[#F5F8F5]"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              <span>
                {totalPendingChanges > 0
                  ? `Reset ${totalPendingChanges} Perubahan`
                  : "Reset Input"}
              </span>
            </button>
          )}
        </div>

        {/* Illustrative Presets */}
        <div className="mt-4 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-[#16354A]">
            <Sparkles className="h-3.5 w-3.5 text-[#0F766E]" aria-hidden="true" />
            <span>Contoh Skenario Cepat (Ilustratif — Bukan Data Pasar Aktual):</span>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => applyPreset("egg20")}
              className="min-h-[36px] rounded-lg border border-[#B5DFDA] bg-white px-3 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#EBF6F5]"
            >
              Harga Telur Naik 20%
            </button>
            <button
              type="button"
              onClick={() => applyPreset("egg100")}
              className="min-h-[36px] rounded-lg border border-[#B5DFDA] bg-white px-3 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#EBF6F5]"
            >
              Lonjakan Harga Telur +100%
            </button>
            <button
              type="button"
              onClick={() => applyPreset("tempeLow")}
              className="min-h-[36px] rounded-lg border border-[#F5D59B] bg-white px-3 py-1.5 text-xs font-semibold text-[#8A5300] hover:bg-[#FEF6E7]"
            >
              Stok Tempe Terbatas (7,5 kg)
            </button>
            <button
              type="button"
              onClick={() => applyPreset("infeasibleStock")}
              className="min-h-[36px] rounded-lg border border-[#F5C2C2] bg-white px-3 py-1.5 text-xs font-semibold text-[#991B1B] hover:bg-[#FEF0F0]"
            >
              Uji Tidak Layak: Stok Pokok Habis
            </button>
          </div>
        </div>

        {/* Name + Search */}
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <label htmlFor="sim-name" className="block text-xs font-semibold text-[#4A6170]">
              Nama Skenario Simulasi
            </label>
            <input
              id="sim-name"
              type="text"
              value={simName}
              onChange={(e) => setSimName(e.target.value)}
              className="mt-1.5 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
              placeholder="Contoh: Harga Telur Naik 20%"
            />
          </div>
          <div>
            <label htmlFor="sim-search" className="block text-xs font-semibold text-[#4A6170]">
              Cari Bahan Pangan
            </label>
            <div className="relative mt-1.5">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#647A87]"
                aria-hidden="true"
              />
              <input
                id="sim-search"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Cari telur, ayam, tempe, beras..."
                className="h-11 w-full rounded-xl border border-[#DCE6DE] bg-white pl-9 pr-3 text-sm text-[#16354A]"
              />
            </div>
          </div>
        </div>

        {/* Editable Ingredient Table */}
        <div className="mt-4 max-h-[380px] overflow-auto rounded-xl border border-[#DCE6DE]">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 z-10 border-b border-[#DCE6DE] bg-[#F5F8F5] text-[#4A6170]">
              <tr>
                <th className="px-3.5 py-2.5 font-semibold">Bahan Pangan</th>
                <th className="px-3.5 py-2.5 font-semibold">Kategori</th>
                <th className="px-3.5 py-2.5 font-semibold">Harga Baru (Rp/kg)</th>
                <th className="px-3.5 py-2.5 font-semibold">Stok Tersedia (kg)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EEF3EE] bg-white">
              {filteredItems.map((item) => {
                const basePriceKg = basePricesKgMap[item.code] ?? 0;
                const priceRaw =
                  priceInputs[item.code] ?? formatNumericDisplay(basePriceKg, "integer");
                const priceParsed = parsedPriceMap[item.code];
                const priceChanged = Boolean(
                  priceParsed?.valid && Math.abs(priceParsed.value - basePriceKg) > 0.01
                );
                const priceFieldKey = `price-${item.code}`;
                const priceError =
                  priceParsed && !priceParsed.valid
                    ? priceParsed.isIntermediate && !blurredFields[priceFieldKey]
                      ? null
                      : priceParsed.error
                    : null;

                const baseStockKg = baseStockKgMap[item.code] ?? 0;
                const stockRaw =
                  stockInputs[item.code] ?? formatNumericDisplay(baseStockKg, "decimal");
                const stockParsed = parsedStockMap[item.code];
                const stockChanged = Boolean(
                  stockParsed?.valid && Math.abs(stockParsed.value - baseStockKg) > 0.001
                );
                const stockFieldKey = `stock-${item.code}`;
                const stockError =
                  stockParsed && !stockParsed.valid
                    ? stockParsed.isIntermediate && !blurredFields[stockFieldKey]
                      ? null
                      : stockParsed.error
                    : null;

                const hasRowError = Boolean(priceError || stockError);

                return (
                  <tr
                    key={item.code}
                    className={
                      hasRowError
                        ? "bg-[#FEF0F0]/50"
                        : priceChanged || stockChanged
                        ? "bg-[#EBF6F5]/40"
                        : ""
                    }
                  >
                    <td className="px-3.5 py-2.5 align-top">
                      <span className="block font-semibold text-[#16354A]">{item.name}</span>
                      <span className="text-[11px] text-[#647A87]">
                        Awal: {formatIDR(basePriceKg)}/kg • Stok {formatWeightFromGrams(baseStockKg * 1000)}
                      </span>
                    </td>
                    <td className="px-3.5 py-2.5 align-top text-[#4A6170]">
                      {formatCategoryLabel(item.category)}
                    </td>
                    <td className="px-3.5 py-2.5 align-top">
                      <NumericInput
                        id={priceFieldKey}
                        label={`Harga per kg ${item.name}`}
                        mode="integer"
                        min={1}
                        minErrorMessage="Harga minimal Rp1/kg sesuai aturan sistem."
                        value={priceRaw}
                        disabled={isRunning}
                        error={priceError}
                        isModified={priceChanged}
                        modifiedTone="teal"
                        className="w-32"
                        onChange={(raw) => {
                          setBlurredFields((prev) => ({ ...prev, [priceFieldKey]: false }));
                          setPriceInputs((prev) => ({ ...prev, [item.code]: raw }));
                        }}
                        onBlurNormalize={(res) => {
                          setBlurredFields((prev) => ({ ...prev, [priceFieldKey]: true }));
                          if (res.valid) {
                            if (Math.abs(res.value - basePriceKg) <= 0.01) {
                              setPriceInputs((prev) => {
                                const next = { ...prev };
                                delete next[item.code];
                                return next;
                              });
                            } else {
                              setPriceInputs((prev) => ({
                                ...prev,
                                [item.code]: res.normalizedText,
                              }));
                            }
                          }
                        }}
                      />
                    </td>
                    <td className="px-3.5 py-2.5 align-top">
                      <NumericInput
                        id={stockFieldKey}
                        label={`Stok kg ${item.name}`}
                        mode="decimal"
                        min={0}
                        minErrorMessage="Stok tidak boleh negatif."
                        value={stockRaw}
                        disabled={isRunning}
                        error={stockError}
                        isModified={stockChanged}
                        modifiedTone="amber"
                        className="w-28"
                        onChange={(raw) => {
                          setBlurredFields((prev) => ({ ...prev, [stockFieldKey]: false }));
                          setStockInputs((prev) => ({ ...prev, [item.code]: raw }));
                        }}
                        onBlurNormalize={(res) => {
                          setBlurredFields((prev) => ({ ...prev, [stockFieldKey]: true }));
                          if (res.valid) {
                            if (Math.abs(res.value - baseStockKg) <= 0.001) {
                              setStockInputs((prev) => {
                                const next = { ...prev };
                                delete next[item.code];
                                return next;
                              });
                            } else {
                              setStockInputs((prev) => ({
                                ...prev,
                                [item.code]: res.normalizedText,
                              }));
                            }
                          }
                        }}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Preview Changes & Step 3 CTA */}
        <div className="mt-5 flex flex-col justify-between gap-4 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-4 sm:flex-row sm:items-center">
          <div className="space-y-1 text-xs text-[#4A6170]">
            <p className="font-semibold text-[#16354A]">
              Ringkasan Perubahan Siap Dihitung ({totalPendingChanges} item):
            </p>
            {invalidInputCount > 0 ? (
              <p className="font-medium text-[#C43D3D]" role="alert">
                Terdapat {invalidInputCount} input angka yang belum valid. Perbaiki kolom bertanda
                merah sebelum menghitung ulang menu.
              </p>
            ) : totalPendingChanges === 0 ? (
              <p>Belum ada perubahan harga/stok. Menjalankan sekarang akan menguji ulang kondisi identik.</p>
            ) : (
              <p>
                {pendingPriceChanges.length} perubahan harga, {pendingStockChanges.length} perubahan
                stok. Rencana awal tetap tersimpan terpisah.
              </p>
            )}
          </div>

          <button
            type="button"
            disabled={isRunning || !baseRun || invalidInputCount > 0}
            onClick={handleRunSimulation}
            className="inline-flex min-h-[44px] shrink-0 items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-[#0B5F58] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isRunning ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                <span>Sedang menghitung alternatif menu...</span>
              </>
            ) : (
              <>
                <Play className="h-4 w-4" aria-hidden="true" />
                <span>Hitung Ulang Menu</span>
              </>
            )}
          </button>
        </div>

        {runError && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2.5 rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-3.5 text-sm text-[#991B1B]"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{runError}</span>
          </div>
        )}
      </section>

      {/* Step 4 — Side-by-Side Comparison */}
      {resultComparison && (
        <ScenarioComparison
          comparison={resultComparison}
          baseName={baseScenario?.name ?? "Rencana Awal"}
          candidateName={resultName}
          candidateRun={resultRun ?? undefined}
          onAdoptCandidate={
            resultRun?.validation_passed
              ? () => {
                  setSelectedRunId(resultRun.run_id);
                  router.push("/dashboard");
                }
              : undefined
          }
        />
      )}
    </div>
  );
}
