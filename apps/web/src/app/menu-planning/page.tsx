"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  SlidersHorizontal,
  Utensils,
} from "lucide-react";

import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { MenuDayCard } from "@/components/menu/MenuDayCard";
import { MenuReviewActionBar } from "@/components/menu/MenuReviewActionBar";
import { ScenarioPlanningForm } from "@/components/menu/ScenarioPlanningForm";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient } from "@/lib/api/client";
import {
  formatDayLabel,
  formatDecimal,
  formatIDR,
  formatMealTypeLabel,
  formatNutrientLabel,
  formatPercent,
  formatRunStatus,
  formatSlotLabel,
} from "@/lib/formatters/indonesian";
import type { SlotEnum } from "@/types/api";

const SLOT_ORDER: SlotEnum[] = ["staple", "protein", "vegetable", "fruit"];

export default function MenuPlanningPage() {
  return <Suspense fallback={<LoadingSkeleton rows={3} />}><MenuPlanningContent /></Suspense>;
}

function MenuPlanningContent() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const requestedRunId = searchParams.get("run");
  const requestedDatasetId = searchParams.get("dataset") ?? "";
  const {
    datasets,
    runs,
    setSelectedRunId,
    selectedRun,
    selectedScenario,
    isLoadingList,
    isLoadingRun,
    listError,
    runError,
    refreshAll,
  } = useWorkspace();

  const [activeDayIndex, setActiveDayIndex] = useState<number>(1);
  const [expandedRecipeId, setExpandedRecipeId] = useState<string | null>(null);
  const [appliedRequestedRun, setAppliedRequestedRun] = useState<string | null>(null);

  useEffect(() => {
    if (requestedRunId && requestedRunId !== appliedRequestedRun && runs.some((run) => run.run_id === requestedRunId)) {
      setSelectedRunId(requestedRunId);
      setAppliedRequestedRun(requestedRunId);
    }
  }, [appliedRequestedRun, requestedRunId, runs, setSelectedRunId]);

  const canReadInventory = user?.active_role === "MENU_PLANNER" || user?.active_role === "KITCHEN_MANAGER";
  const kitchenId = user?.active_kitchen_id;
  const isPlanner = user?.active_role === "MENU_PLANNER";
  const planForm = isPlanner && (
    <ScenarioPlanningForm key={`${kitchenId}-${requestedDatasetId}`}
      initialDatasetId={requestedDatasetId}
      expanded={Boolean(requestedDatasetId || searchParams.has("new") || !selectedRun)} />
  );

  const recipesQuery = useQuery({
    queryKey: ["recipes", kitchenId, selectedRun?.dataset_version_id],
    queryFn: () => apiClient.listRecipes(selectedRun?.dataset_version_id, true),
    enabled: Boolean(selectedRun?.dataset_version_id),
  });

  const inventoryQuery = useQuery({
    queryKey: ["inventory", kitchenId, selectedRun?.dataset_version_id],
    queryFn: () => apiClient.getInventory(selectedRun?.dataset_version_id),
    enabled: canReadInventory && Boolean(selectedRun?.dataset_version_id),
  });

  const recipesById = useMemo(
    () => new Map((recipesQuery.data ?? []).map((r) => [r.id, r])),
    [recipesQuery.data]
  );
  const ingredientNameByCode = useMemo(
    () => new Map((inventoryQuery.data?.items ?? []).map((i) => [i.code, i.name])),
    [inventoryQuery.data]
  );

  if (isLoadingList || (isLoadingRun && !isPlanner)) {
    return (
      <div className="space-y-6">
        <PageHeader title="Rencana Menu" />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (listError || runError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Rencana Menu" />
        <ErrorState
          message={(listError || runError)?.message ?? "Gagal memuat rencana menu."}
          onRetry={refreshAll}
        />
      </div>
    );
  }

  if (!selectedRun || !selectedRun.validation_passed || selectedRun.days.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Rencana Menu"
          subtitle="Tinjau susunan resep terverifikasi, komposisi bahan, biaya harian, dan kesesuaian terhadap target gizi simulasi."
        />
        {planForm}
        <div id="hasil-rencana" className="scroll-mt-20">
          {isLoadingRun ? <LoadingSkeleton rows={2} /> : selectedRun ? (
            <ErrorState
              title={formatRunStatus(selectedRun.solver_status, false).label}
              message={selectedRun.constraint_diagnostics[0]?.message ?? "Periksa anggaran, stok bahan, dan jumlah hari, lalu hitung ulang dengan skenario baru."}
            />
          ) : (
            <EmptyState
              title="Belum ada rencana menu"
              description={isPlanner ? "Pilih dataset dan hitung rencana pertama melalui formulir di atas." : "Rencana akan muncul setelah Perencana Menu menyimpan hasil pertama."}
            />
          )}
        </div>
      </div>
    );
  }

  const params = selectedRun.input_snapshot?.scenario_params;
  const budgetPerServing =
    selectedScenario?.budget_idr_per_serving ?? params?.budget_idr_per_serving ?? 0;
  const mealTypeLabel = formatMealTypeLabel(selectedScenario?.meal_type ?? params?.meal_type);
  const targetLimits = selectedRun.input_snapshot?.nutrition_target?.limits ?? [];
  const statusInfo = formatRunStatus(selectedRun.solver_status, selectedRun.validation_passed);
  const datasetName = datasets.find((dataset) => dataset.id === selectedRun.dataset_version_id)?.name;

  const activeDay =
    selectedRun.days.find((d) => d.day_index === activeDayIndex) ?? selectedRun.days[0];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Rencana Menu"
        subtitle={`${selectedScenario?.name ?? "Rencana Aktif"} • Sesi: ${mealTypeLabel} • ${
          selectedRun.days_count ?? selectedRun.days.length
        } hari kerja × ${
          selectedRun.servings_per_day ?? selectedScenario?.servings_per_day ?? "—"
        } porsi/hari (${
          selectedRun.total_servings ? `${selectedRun.total_servings.toLocaleString("id-ID")} total porsi` : ""
        }, ${selectedRun.total_menu_slots ?? selectedRun.days.length * 4} slot hidangan)${
          datasetName ? ` • Dataset: ${datasetName}` : ""
        }`}
        badges={
          <>
            <StatusBadge tone={statusInfo.tone} label={statusInfo.shortLabel} size="md" />
            <DatasetSimulationNotice compact simulationOnly={selectedRun.simulation_only} />
          </>
        }
        actions={
          user?.active_role === "MENU_PLANNER" ? (
            <Link
              href={`/simulator?baselineRun=${selectedRun.run_id}`}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58]"
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
              <span>Atasi Gangguan / Simulasi</span>
            </Link>
          ) : undefined
        }
      />

      {planForm}
      <div id="hasil-rencana" className="scroll-mt-20">
      <DatasetSimulationNotice simulationOnly={selectedRun.simulation_only} />
      </div>

      <MenuReviewActionBar
        key={selectedRun.run_id}
        runId={selectedRun.run_id}
        scenarioName={selectedScenario?.name ?? "Rencana Menu"}
        validationPassed={selectedRun.validation_passed}
      />
      {recipesQuery.error && <ErrorState title="Rincian resep gagal dimuat" message={recipesQuery.error.message}
        onRetry={() => void recipesQuery.refetch()} />}
      {inventoryQuery.error && <ErrorState title="Daftar bahan gagal dimuat" message={inventoryQuery.error.message}
        onRetry={() => void inventoryQuery.refetch()} />}

      {/* 5-Day Selector Cards */}
      <section aria-label="Pilih Hari Rencana Menu">
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-5">
          {selectedRun.days.map((day) => (
            <MenuDayCard
              key={day.day_index}
              day={day}
              budgetPerServing={budgetPerServing}
              selected={day.day_index === activeDay.day_index}
              onSelect={() => {
                setActiveDayIndex(day.day_index);
                setExpandedRecipeId(null);
              }}
            />
          ))}
        </div>
      </section>

      {/* Active Day Detailed View */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Recipe Slots + Expandable Ingredients */}
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] lg:col-span-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EEF3EE] pb-4">
            <div>
              <h2 className="text-lg font-bold text-[#16354A]">
                Menu {formatDayLabel(activeDay.day_index)} — {mealTypeLabel}
              </h2>
              <p className="mt-0.5 text-xs text-[#647A87]">
                Klik resep untuk melihat komposisi bahan mentah per porsi dan faktor retensi memasak.
              </p>
            </div>
            <div className="text-right tabular-nums">
              <span className="block text-[11px] text-[#647A87]">Biaya per Porsi</span>
              <span className="text-lg font-bold text-[#0F766E]">
                {formatIDR(activeDay.daily_cost_idr_per_serving)}
              </span>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {SLOT_ORDER.map((slot) => {
              const rid = activeDay.recipes_by_slot[slot];
              const rname = activeDay.recipe_names_by_slot[slot];
              const recipeDetail = rid ? recipesById.get(rid) : undefined;
              const isExpanded = expandedRecipeId === rid;

              return (
                <div
                  key={slot}
                  className="overflow-hidden rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/50"
                >
                  <button
                    type="button"
                    onClick={() => setExpandedRecipeId(isExpanded ? null : rid)}
                    aria-expanded={isExpanded}
                    className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left hover:bg-[#EBF6F5]/50"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-[#0F766E] border border-[#DCE6DE]">
                        <Utensils className="h-4 w-4" aria-hidden="true" />
                      </div>
                      <div>
                        <span className="block text-[11px] font-semibold uppercase tracking-wide text-[#647A87]">
                          {formatSlotLabel(slot)}
                        </span>
                        <span className="block text-sm font-bold text-[#16354A]">{rname}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {recipeDetail && recipeDetail.allergen_tags.length > 0 && (
                        <span className="rounded-full border border-[#F5D59B] bg-[#FEF6E7] px-2 py-0.5 text-[11px] font-medium text-[#8A5300]">
                          Alergen: {recipeDetail.allergen_tags.join(", ")}
                        </span>
                      )}
                      {isExpanded ? (
                        <ChevronUp className="h-4 w-4 text-[#647A87]" />
                      ) : (
                        <ChevronDown className="h-4 w-4 text-[#647A87]" />
                      )}
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="border-t border-[#DCE6DE] bg-white px-4 py-3.5 text-xs">
                      {recipeDetail ? (
                        <>
                          <p className="font-semibold text-[#4A6170]">
                            Komposisi Bahan per 1 Porsi (Berat Mentah):
                          </p>
                          <ul className="mt-2 divide-y divide-[#EEF3EE]">
                            {recipeDetail.ingredients.map((item) => (
                              <li
                                key={item.ingredient_code}
                                className="flex items-center justify-between py-1.5"
                              >
                                <span className="font-medium text-[#16354A]">
                                  {ingredientNameByCode.get(item.ingredient_code) ??
                                    item.ingredient_code}
                                </span>
                                <span className="text-[#4A6170] tabular-nums">
                                  <strong>{formatDecimal(item.raw_g_per_serving, 0)} g</strong>{" "}
                                  <span className="text-[#647A87]">
                                    (retensi {formatPercent(item.retention_factor * 100, 0)})
                                  </span>
                                </span>
                              </li>
                            ))}
                          </ul>
                        </>
                      ) : (
                        <p className="text-[#647A87]">Komposisi resep sedang dimuat...</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* Nutrition Target Compliance Panel */}
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] lg:col-span-2">
          <h2 className="text-base font-bold text-[#16354A]">
            Ringkasan Gizi Harian vs Batas Simulasi
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-[#647A87]">
            Nilai dihitung oleh backend berdasarkan berat mentah, bagian dapat dimakan (BDD), dan
            faktor retensi.{" "}
            <strong className="text-[#8A5300]">
              Memenuhi batasan simulasi saja; bukan klaim kepatuhan gizi resmi tanpa ahli gizi.
            </strong>
          </p>

          <div className="mt-4 space-y-3">
            {Object.entries(activeDay.nutrients_per_serving).map(([key, val]) => {
              const meta = formatNutrientLabel(key);
              const lim = targetLimits.find((l) => l.nutrient_key === key);
              const minV = lim?.min_per_serving ?? null;
              const maxV = lim?.max_per_serving ?? null;
              const passMin = minV === null || val >= minV - 1e-3;
              const passMax = maxV === null || val <= maxV + 1e-3;
              const ok = passMin && passMax;

              return (
                <div
                  key={key}
                  className="rounded-xl border border-[#EEF3EE] bg-[#F5F8F5] p-3 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-[#16354A]">{meta.label}</span>
                    <span className="inline-flex items-center gap-1 font-bold text-[#16354A] tabular-nums">
                      {ok && <CheckCircle2 className="h-3.5 w-3.5 text-[#15803D]" aria-hidden="true" />}
                      {formatDecimal(val, 1)} {lim?.unit || meta.unit}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-[#647A87] tabular-nums">
                    <span>
                      Batas simulasi: Min {minV !== null ? formatDecimal(minV, 1) : "—"}
                      {maxV !== null ? ` • Maks ${formatDecimal(maxV, 1)}` : ""} {lim?.unit || meta.unit}
                    </span>
                    <span className={ok ? "font-semibold text-[#166534]" : "font-semibold text-[#991B1B]"}>
                      {ok ? "Sesuai Batas Simulasi" : "Di Luar Batas"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
