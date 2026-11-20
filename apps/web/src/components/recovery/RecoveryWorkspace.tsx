"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  ShieldAlert,
  Trash2,
} from "lucide-react";

import { ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { NumericInput } from "@/components/ui/NumericInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatDecimal,
  formatDisruptionTypeLabel,
  formatIDR,
  formatRecoveryStatus,
  formatSignedIDR,
  formatSlotLabel,
} from "@/lib/formatters/indonesian";
import { formatNumericDisplay, parseNumericInput } from "@/lib/formatters/numericInput";
import type {
  CandidatePlanSummary,
  DisruptionTypeEnum,
  RecoveryEventResponse,
  RecoveryModeEnum,
  StockDisruptionInput,
} from "@/types/api";

interface DisruptionRowDraft {
  ingredientCode: string;
  deliveryMode: "NORMAL" | "PARTIAL" | "DELAYED" | "UNAVAILABLE";
  usableKgRaw: string;
  priceKgRaw: string;
  reason: string;
}

interface RecoveryWorkspaceProps {
  initialBaselineRunId?: string | null;
  initialReviewId?: string | null;
  initialIngredientCode?: string | null;
  initialEventId?: string | null;
}

const DISRUPTION_TYPE_OPTIONS: { value: DisruptionTypeEnum; label: string }[] = [
  { value: "PARTIAL_DELIVERY", label: "Pengiriman Parsial" },
  { value: "SUPPLIER_DELAY", label: "Pengiriman Tertunda" },
  { value: "STOCK_SHORTAGE", label: "Stok Berkurang" },
  { value: "INGREDIENT_UNAVAILABLE", label: "Bahan Habis / Tidak Tersedia" },
  { value: "PRICE_CHANGE", label: "Harga Bahan Berubah" },
  { value: "SERVING_COUNT_CHANGE", label: "Jumlah Porsi Berubah" },
];

export function RecoveryWorkspace({
  initialBaselineRunId,
  initialReviewId,
  initialIngredientCode,
  initialEventId,
}: RecoveryWorkspaceProps) {
  const qc = useQueryClient();
  const { runs, selectedRunId, refreshAll } = useWorkspace();

  const reviewsQuery = useQuery({
    queryKey: ["menu-reviews"],
    queryFn: () => apiClient.listMenuReviews(),
  });

  const historyQuery = useQuery({
    queryKey: ["recovery-events"],
    queryFn: () => apiClient.listRecoveryEvents(),
  });

  const initialEventQuery = useQuery({
    queryKey: ["recovery-event", initialEventId],
    queryFn: () => apiClient.getRecoveryEvent(initialEventId!),
    enabled: Boolean(initialEventId),
  });

  const effectiveReviewId =
    initialReviewId || initialEventQuery.data?.baseline_menu_review_id || null;

  const validRuns = useMemo(
    () => runs.filter((r) => r.validation_passed && r.solver_status !== "INFEASIBLE"),
    [runs]
  );

  // Pick approved plan first unless caller supplied explicit baselineRun / reviewId / event baseline
  const approvedReview = useMemo(() => {
    const list = reviewsQuery.data ?? [];
    if (effectiveReviewId) {
      return list.find((r) => r.id === effectiveReviewId) ?? list.find((r) => r.status === "APPROVED");
    }
    return list.find((r) => r.status === "APPROVED");
  }, [reviewsQuery.data, effectiveReviewId]);

  const effectiveBaselineRunId =
    initialBaselineRunId ||
    initialEventQuery.data?.baseline_run_id ||
    approvedReview?.run_id ||
    validRuns.find((r) => r.run_id === selectedRunId)?.run_id ||
    validRuns[0]?.run_id ||
    "";

  const baselineRunQuery = useQuery({
    queryKey: ["run", effectiveBaselineRunId],
    queryFn: () => apiClient.getRun(effectiveBaselineRunId),
    enabled: Boolean(effectiveBaselineRunId),
  });

  const baselineScenarioQuery = useQuery({
    queryKey: ["scenario", baselineRunQuery.data?.scenario_id],
    queryFn: () => apiClient.getScenario(baselineRunQuery.data!.scenario_id),
    enabled: Boolean(baselineRunQuery.data?.scenario_id),
  });

  const invQuery = useQuery({
    queryKey: ["inventory", baselineRunQuery.data?.dataset_version_id],
    queryFn: () =>
      apiClient.getInventory(baselineRunQuery.data!.dataset_version_id),
    enabled: Boolean(baselineRunQuery.data?.dataset_version_id),
  });

  // Live impact preview using verified inventory
  const [useLatestVerifiedInventory, setUseLatestVerifiedInventory] = useState(true);
  const [selectedDisruptionTypes, setSelectedDisruptionTypes] = useState<DisruptionTypeEnum[]>([
    "PARTIAL_DELIVERY",
    "STOCK_SHORTAGE",
  ]);
  const [servingsRaw, setServingsRaw] = useState<string>("");
  const [budgetRaw, setBudgetRaw] = useState<string>("");
  const [blurredMeta, setBlurredMeta] = useState<Record<string, boolean>>({});
  const [rowDrafts, setRowDrafts] = useState<DisruptionRowDraft[]>([]);
  const [addIngredientCode, setAddIngredientCode] = useState<string>("");

  const [activeEvent, setActiveEvent] = useState<RecoveryEventResponse | null>(null);
  const [selectedMode, setSelectedMode] = useState<RecoveryModeEnum>("MIN_DISRUPTION");
  const [showProcurement, setShowProcurement] = useState<boolean>(false);
  const [proposalTitle, setProposalTitle] = useState<string>("");
  const [plannerNotes, setPlannerNotes] = useState<string>("");
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (initialEventQuery.data && !activeEvent) {
      setActiveEvent(initialEventQuery.data);
      if (initialEventQuery.data.selected_mode) {
        setSelectedMode(initialEventQuery.data.selected_mode);
      }
      setProposalTitle(`Pengganti: ${initialEventQuery.data.title}`);
      setPlannerNotes((prev) => prev || initialEventQuery.data!.disruption_summary);
    }
  }, [initialEventQuery.data, activeEvent]);

  const impactPreviewQuery = useQuery({
    queryKey: ["recovery-impact-preview", effectiveBaselineRunId, useLatestVerifiedInventory],
    queryFn: () =>
      apiClient.previewRecoveryImpact({
        baseline_run_id: effectiveBaselineRunId || undefined,
        baseline_menu_review_id: approvedReview?.id ?? undefined,
        use_latest_verified_inventory: useLatestVerifiedInventory,
      }),
    enabled: Boolean(effectiveBaselineRunId),
  });

  // Initialize servings/budget/rowDrafts cleanly when baseline + impact load
  useEffect(() => {
    if (baselineScenarioQuery.data) {
      setServingsRaw((prev) =>
        prev === "" ? String(baselineScenarioQuery.data!.servings_per_day) : prev
      );
      setBudgetRaw((prev) =>
        prev === ""
          ? String(Math.round(baselineScenarioQuery.data!.budget_idr_per_serving))
          : prev
      );
    }
  }, [baselineScenarioQuery.data]);

  const inventoryItems = invQuery.data?.items ?? [];
  const inventoryByCode = useMemo(
    () => new Map(inventoryItems.map((i) => [i.code, i])),
    [inventoryItems]
  );

  useEffect(() => {
    if (rowDrafts.length > 0 || inventoryItems.length === 0) return;

    const seededCodes: string[] = [];
    if (initialIngredientCode && inventoryByCode.has(initialIngredientCode)) {
      seededCodes.push(initialIngredientCode);
    }
    for (const aff of impactPreviewQuery.data?.affected_ingredients ?? []) {
      if (!seededCodes.includes(aff.ingredient_code) && aff.shortfall_kg > 0) {
        seededCodes.push(aff.ingredient_code);
      }
    }
    if (seededCodes.length === 0) return;

    const drafts: DisruptionRowDraft[] = seededCodes.map((code) => {
      const item = inventoryByCode.get(code);
      const aff = impactPreviewQuery.data?.affected_ingredients.find(
        (a) => a.ingredient_code === code
      );
      const deliv = item?.delivery_status ?? aff?.delivery_status ?? "NONE";
      const usableKg =
        aff?.current_usable_kg ??
        (item?.usable_raw_g !== null && item?.usable_raw_g !== undefined
          ? item.usable_raw_g / 1000
          : item
            ? (item.stock_raw_g ?? 0) / 1000
            : 0);
      const priceKg = item?.price_idr_per_g ? Math.round(item.price_idr_per_g * 1000) : 0;
      const mode: DisruptionRowDraft["deliveryMode"] =
        usableKg <= 0
          ? "UNAVAILABLE"
          : deliv === "PARTIAL"
            ? "PARTIAL"
            : deliv === "DELAYED"
              ? "DELAYED"
              : "NORMAL";
      return {
        ingredientCode: code,
        deliveryMode: mode,
        usableKgRaw: formatNumericDisplay(usableKg, "decimal"),
        priceKgRaw: formatNumericDisplay(priceKg, "integer"),
        reason: "",
      };
    });
    setRowDrafts(drafts);
  }, [initialIngredientCode, impactPreviewQuery.data, inventoryItems, inventoryByCode, rowDrafts.length]);

  // Strict client-side numeric validation matching backend contract
  const servingsParsed = parseNumericInput(servingsRaw || "0", {
    mode: "integer",
    min: 1,
    minErrorMessage: "Jumlah porsi minimal 1.",
  });
  const budgetParsed = parseNumericInput(budgetRaw || "0", {
    mode: "integer",
    min: 1,
    minErrorMessage: "Anggaran minimal Rp1/porsi.",
  });

  const draftValidations = useMemo(() => {
    return rowDrafts.map((row) => {
      const priceRes = parseNumericInput(row.priceKgRaw, {
        mode: "integer",
        min: 1,
        minErrorMessage: "Harga minimal Rp1/kg.",
      });
      const stockRes =
        row.deliveryMode === "UNAVAILABLE"
          ? { valid: true as const, value: 0, normalizedText: "0", isIntermediate: false as const }
          : parseNumericInput(row.usableKgRaw, {
              mode: "decimal",
              min: 0,
              minErrorMessage: "Stok tidak boleh negatif.",
            });
      return { code: row.ingredientCode, priceRes, stockRes };
    });
  }, [rowDrafts]);

  const hasInvalidInputs =
    (servingsRaw !== "" && !servingsParsed.valid) ||
    (budgetRaw !== "" && !budgetParsed.valid) ||
    draftValidations.some((d) => !d.priceRes.valid || !d.stockRes.valid);

  const analyzeMutation = useMutation({
    mutationFn: () => {
      const stockChanges: StockDisruptionInput[] = [];
      const priceChanges: { ingredient_code: string; new_price_idr_per_kg: number }[] = [];

      rowDrafts.forEach((row, idx) => {
        const val = draftValidations[idx];
        const invItem = inventoryByCode.get(row.ingredientCode);
        const origPriceKg = invItem?.price_idr_per_g
          ? Math.round(invItem.price_idr_per_g * 1000)
          : 0;
        if (val.priceRes.valid && Math.abs(val.priceRes.value - origPriceKg) > 0.5) {
          priceChanges.push({
            ingredient_code: row.ingredientCode,
            new_price_idr_per_kg: val.priceRes.value,
          });
        }
        if (row.deliveryMode === "UNAVAILABLE") {
          stockChanges.push({
            ingredient_code: row.ingredientCode,
            unavailable: true,
            new_usable_kg: 0,
            reason: row.reason || "Bahan ditandai habis / tidak tersedia.",
          });
        } else if (val.stockRes.valid) {
          stockChanges.push({
            ingredient_code: row.ingredientCode,
            new_usable_kg: val.stockRes.value,
            delivery_status:
              row.deliveryMode === "PARTIAL" || row.deliveryMode === "DELAYED"
                ? row.deliveryMode
                : undefined,
            reason: row.reason || undefined,
          });
        }
      });

      const titleBase = approvedReview?.title ?? baselineScenarioQuery.data?.name ?? "Menu SPPG";
      return apiClient.createRecoveryEvent({
        baseline_run_id: effectiveBaselineRunId,
        baseline_menu_review_id: approvedReview?.id ?? null,
        title: `Pemulihan ${titleBase}`,
        disruption_types: selectedDisruptionTypes,
        use_latest_verified_inventory: useLatestVerifiedInventory,
        new_servings_per_day:
          servingsParsed.valid &&
          servingsParsed.value !== baselineScenarioQuery.data?.servings_per_day
            ? servingsParsed.value
            : undefined,
        new_budget_idr_per_serving:
          budgetParsed.valid &&
          baselineScenarioQuery.data &&
          Math.abs(budgetParsed.value - baselineScenarioQuery.data.budget_idr_per_serving) > 1
            ? budgetParsed.value
            : undefined,
        price_changes: priceChanges,
        stock_changes: stockChanges,
      });
    },
    onSuccess: (created) => {
      setActionError(null);
      setSubmitSuccess(null);
      setActiveEvent(created);
      if (created.min_disruption.validation_passed) {
        setSelectedMode("MIN_DISRUPTION");
      } else if (created.min_cost.validation_passed) {
        setSelectedMode("MIN_COST");
      }
      setProposalTitle(`Pengganti: ${created.title}`);
      setPlannerNotes(created.disruption_summary);
      qc.invalidateQueries({ queryKey: ["recovery-events"] });
      refreshAll();
    },
    onError: (err) => {
      setActionError(
        err instanceof ApiError ? err.message : "Gagal menghitung alternatif pemulihan."
      );
    },
  });

  const submitMutation = useMutation({
    mutationFn: () => {
      if (!activeEvent) throw new Error("Belum ada hasil analisis.");
      return apiClient.submitRecoveryEvent(activeEvent.id, {
        mode: selectedMode,
        title: proposalTitle.trim() || undefined,
        planner_notes: plannerNotes.trim() || undefined,
        submit_for_review: true,
      });
    },
    onSuccess: (res) => {
      setActionError(null);
      setActiveEvent(res.recovery_event);
      setSubmitSuccess(
        `Usulan rencana pengganti "${res.review.title}" berhasil diajukan ke Kepala Dapur untuk ditinjau.`
      );
      qc.invalidateQueries({ queryKey: ["menu-reviews"] });
      qc.invalidateQueries({ queryKey: ["recovery-events"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      refreshAll();
    },
    onError: (err) => {
      setActionError(
        err instanceof ApiError ? err.message : "Gagal mengajukan rencana pengganti."
      );
    },
  });

  const toggleDisruptionType = (dt: DisruptionTypeEnum) => {
    setSelectedDisruptionTypes((prev) =>
      prev.includes(dt) ? prev.filter((item) => item !== dt) : [...prev, dt]
    );
  };

  const handleAddIngredientRow = (codeToAdd: string) => {
    const code = codeToAdd || addIngredientCode;
    if (!code || rowDrafts.some((r) => r.ingredientCode === code)) return;
    const item = inventoryByCode.get(code);
    if (!item) return;
    const usableKg =
      item.usable_raw_g !== null && item.usable_raw_g !== undefined
        ? item.usable_raw_g / 1000
        : (item.stock_raw_g ?? 0) / 1000;
    const priceKg = item.price_idr_per_g ? Math.round(item.price_idr_per_g * 1000) : 0;
    setRowDrafts((prev) => [
      ...prev,
      {
        ingredientCode: code,
        deliveryMode: item.delivery_status === "PARTIAL" ? "PARTIAL" : "NORMAL",
        usableKgRaw: formatNumericDisplay(usableKg, "decimal"),
        priceKgRaw: formatNumericDisplay(priceKg, "integer"),
        reason: "",
      },
    ]);
    setAddIngredientCode("");
  };

  if (reviewsQuery.isLoading || (Boolean(effectiveBaselineRunId) && baselineRunQuery.isLoading)) {
    return <LoadingSkeleton rows={5} />;
  }

  if (!effectiveBaselineRunId) {
    return (
      <div className="rounded-2xl border border-[#DCE6DE] bg-white p-6 text-center space-y-3">
        <p className="text-sm font-semibold text-[#16354A]">
          Belum ada rencana menu baseline tervalidasi untuk dipulihkan.
        </p>
        <Link
          href="/menu-planning"
          className="inline-flex min-h-[44px] items-center rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white"
        >
          Buka Perencanaan Menu
        </Link>
      </div>
    );
  }

  const impact = impactPreviewQuery.data;
  const activeChosenCandidate: CandidatePlanSummary | null = activeEvent
    ? selectedMode === "MIN_COST"
      ? activeEvent.min_cost
      : activeEvent.min_disruption
    : null;
  const procurementItems = activeEvent
    ? activeEvent.procurement_delta_by_mode[selectedMode] ?? []
    : [];

  return (
    <div className="space-y-6">
      {/* LANGKAH 1: MASALAH TERDETEKSI */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#EEF3EE] pb-3">
          <div>
            <span className="inline-block rounded-full bg-[#EBF6F5] px-2.5 py-0.5 text-[11px] font-bold text-[#0F766E]">
              LANGKAH 1 — MASALAH TERDETEKSI
            </span>
            <h2 className="mt-1 text-base font-bold text-[#16354A]">
              Rencana Dasar: {impact?.baseline_title ?? approvedReview?.title ?? "Menu Baseline"}
            </h2>
            <p className="mt-0.5 text-xs text-[#647A87]">
              Rencana yang sudah disetujui tetap aman tersimpan terpisah dan tidak pernah diubah otomatis.
            </p>
          </div>
          {impact && (
            <StatusBadge
              tone={impact.baseline_still_feasible_at_new_conditions ? "success" : "critical"}
              label={
                impact.baseline_still_feasible_at_new_conditions
                  ? "Masih Memenuhi Syarat Saat Ini"
                  : `${impact.affected_slots.length} Slot Menu Terdampak`
              }
            />
          )}
        </div>

        {impactPreviewQuery.isLoading ? (
          <LoadingSkeleton rows={2} />
        ) : impactPreviewQuery.isError ? (
          <ErrorState
            message={(impactPreviewQuery.error as Error).message}
            onRetry={() => impactPreviewQuery.refetch()}
          />
        ) : impact ? (
          <div className="space-y-3">
            <div
              className={`rounded-xl border p-3.5 text-xs ${
                impact.baseline_still_feasible_at_new_conditions
                  ? "border-[#B5DFDA] bg-[#EBF6F5]/70 text-[#0F766E]"
                  : "border-[#F3D19B] bg-[#FFFBEB] text-[#92400E]"
              }`}
            >
              <p className="font-semibold text-sm">{impact.summary_message}</p>
            </div>

            {impact.affected_ingredients.length > 0 && (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {impact.affected_ingredients.map((ing) => (
                  <div
                    key={ing.ingredient_code}
                    className="rounded-xl border border-[#F3D19B] bg-[#FFFDF7] p-3 text-xs space-y-1"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-[#16354A]">
                        {ing.ingredient_name} ({ing.ingredient_code})
                      </span>
                      {ing.shortfall_kg > 0 && (
                        <StatusBadge
                          tone="critical"
                          label={`Kurang ${formatDecimal(ing.shortfall_kg, 2)} kg`}
                        />
                      )}
                    </div>
                    <p className="text-[#4A6170] tabular-nums">
                      Butuh rencana:{" "}
                      <strong>{formatDecimal(ing.baseline_required_kg, 2)} kg</strong> • Siap
                      pakai:{" "}
                      <strong>
                        {ing.current_usable_kg !== null
                          ? `${formatDecimal(ing.current_usable_kg, 2)} kg`
                          : "UNKNOWN"}
                      </strong>
                      {ing.incoming_kg > 0 && (
                        <>
                          {" "}
                          • Pengiriman {ing.delivery_status}: {formatDecimal(ing.incoming_kg, 2)}{" "}
                          kg (belum tersedia)
                        </>
                      )}
                    </p>
                    {ing.causes.length > 0 && (
                      <p className="text-[11px] text-[#8A5300]">{ing.causes.join(" ")}</p>
                    )}
                  </div>
                ))}
              </div>
            )}

            {impact.affected_slots.length > 0 && (
              <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3 text-xs">
                <p className="font-semibold text-[#16354A]">Slot Menu yang Terdampak:</p>
                <ul className="mt-1.5 space-y-1">
                  {impact.affected_slots.map((slot) => (
                    <li
                      key={`${slot.day_index}-${slot.slot}`}
                      className="flex flex-wrap items-center gap-1.5 text-[#334E5E]"
                    >
                      <span className="rounded bg-white px-1.5 py-0.5 font-semibold text-[#16354A] border border-[#DCE6DE]">
                        Hari {slot.day_index} • {formatSlotLabel(slot.slot)}
                      </span>
                      <span className="font-semibold text-[#991B1B]">
                        {slot.original_recipe_name}
                      </span>
                      <span className="text-[#647A87]">({slot.reasons.join("; ")})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null}
      </section>

      {/* LANGKAH 2: CATAT / SESUAIKAN GANGGUAN */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] space-y-4">
        <div className="border-b border-[#EEF3EE] pb-3">
          <span className="inline-block rounded-full bg-[#EBF6F5] px-2.5 py-0.5 text-[11px] font-bold text-[#0F766E]">
            LANGKAH 2 — SESUAIKAN KONDISI GANGGUAN
          </span>
          <h2 className="mt-1 text-base font-bold text-[#16354A]">
            Jenis Gangguan, Stok Siap Pakai, Harga & Porsi
          </h2>
          <p className="mt-0.5 text-xs text-[#647A87]">
            Bisa dikombinasikan sekaligus (misal pengiriman parsial + harga naik + perubahan porsi).
          </p>
        </div>

        {/* Disruption type chips */}
        <div className="flex flex-wrap gap-2">
          {DISRUPTION_TYPE_OPTIONS.map((opt) => {
            const active = selectedDisruptionTypes.includes(opt.value);
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => toggleDisruptionType(opt.value)}
                className={`min-h-[38px] rounded-xl border px-3 py-1.5 text-xs font-semibold transition ${
                  active
                    ? "border-[#0F766E] bg-[#EBF6F5] text-[#0F766E]"
                    : "border-[#DCE6DE] bg-white text-[#4A6170] hover:bg-[#F5F8F5]"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

        {/* Verified inventory toggle & servings/budget */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3 flex items-center justify-between gap-3">
            <label htmlFor="use-verified-inv" className="text-xs font-semibold text-[#16354A]">
              Gunakan stok terverifikasi terbaru gudang
            </label>
            <input
              id="use-verified-inv"
              type="checkbox"
              checked={useLatestVerifiedInventory}
              onChange={(e) => setUseLatestVerifiedInventory(e.target.checked)}
              className="h-5 w-5 accent-[#0F766E]"
            />
          </div>

          <div>
            <label htmlFor="rec-servings" className="block text-xs font-semibold text-[#4A6170]">
              Jumlah Porsi Baru / Hari
            </label>
            <NumericInput
              id="rec-servings"
              label="Jumlah porsi baru per hari"
              mode="integer"
              min={1}
              minErrorMessage="Minimal 1 porsi per hari."
              value={servingsRaw}
              error={
                !servingsParsed.valid && blurredMeta["rec-servings"] ? servingsParsed.error : null
              }
              isModified={
                servingsParsed.valid &&
                baselineScenarioQuery.data !== undefined &&
                servingsParsed.value !== baselineScenarioQuery.data.servings_per_day
              }
              onChange={(raw) => {
                setBlurredMeta((p) => ({ ...p, "rec-servings": false }));
                setServingsRaw(raw);
              }}
              onBlurNormalize={() => setBlurredMeta((p) => ({ ...p, "rec-servings": true }))}
              className="mt-1"
            />
          </div>

          <div>
            <label htmlFor="rec-budget" className="block text-xs font-semibold text-[#4A6170]">
              Batas Anggaran Baru (Rp / porsi)
            </label>
            <NumericInput
              id="rec-budget"
              label="Batas anggaran per porsi"
              mode="integer"
              min={1}
              minErrorMessage="Minimal Rp1 per porsi."
              value={budgetRaw}
              error={!budgetParsed.valid && blurredMeta["rec-budget"] ? budgetParsed.error : null}
              isModified={
                budgetParsed.valid &&
                baselineScenarioQuery.data !== undefined &&
                Math.abs(budgetParsed.value - baselineScenarioQuery.data.budget_idr_per_serving) > 1
              }
              onChange={(raw) => {
                setBlurredMeta((p) => ({ ...p, "rec-budget": false }));
                setBudgetRaw(raw);
              }}
              onBlurNormalize={() => setBlurredMeta((p) => ({ ...p, "rec-budget": true }))}
              className="mt-1"
            />
          </div>
        </div>

        {/* Add disrupted ingredient */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label htmlFor="add-disrupted-ing" className="block text-xs font-semibold text-[#4A6170]">
              Tambah Bahan yang Mengalami Perubahan Stok / Harga
            </label>
            <select
              id="add-disrupted-ing"
              value={addIngredientCode}
              onChange={(e) => {
                setAddIngredientCode(e.target.value);
                handleAddIngredientRow(e.target.value);
              }}
              className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
            >
              <option value="">-- Pilih bahan pangan untuk disesuaikan --</option>
              {inventoryItems.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name} ({item.code}) — Siap pakai:{" "}
                  {item.usable_raw_g !== null && item.usable_raw_g !== undefined
                    ? `${formatDecimal(item.usable_raw_g / 1000, 2)} kg`
                    : `${formatDecimal((item.stock_raw_g ?? 0) / 1000, 2)} kg`}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={() => handleAddIngredientRow(addIngredientCode)}
            disabled={!addIngredientCode}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] px-4 py-2 text-xs font-semibold text-[#16354A] hover:bg-[#EBF6F5] disabled:opacity-50"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            <span>Tambah Baris</span>
          </button>
        </div>

        {/* Disrupted ingredient editor rows */}
        {rowDrafts.length > 0 && (
          <div className="space-y-3">
            {rowDrafts.map((row, idx) => {
              const invItem = inventoryByCode.get(row.ingredientCode);
              const val = draftValidations[idx];
              const priceErr =
                !val.priceRes.valid &&
                (!val.priceRes.isIntermediate || blurredMeta[`row-price-${row.ingredientCode}`])
                  ? val.priceRes.error
                  : null;
              const stockErr =
                !val.stockRes.valid &&
                (!val.stockRes.isIntermediate || blurredMeta[`row-stock-${row.ingredientCode}`])
                  ? val.stockRes.error
                  : null;
              return (
                <div
                  key={row.ingredientCode}
                  className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/70 p-3.5 grid grid-cols-1 gap-3 md:grid-cols-12 items-start"
                >
                  <div className="md:col-span-3">
                    <p className="text-sm font-bold text-[#16354A]">
                      {invItem?.name ?? row.ingredientCode}
                    </p>
                    <p className="text-[11px] text-[#647A87]">{row.ingredientCode}</p>
                  </div>

                  <div className="md:col-span-3">
                    <label
                      htmlFor={`status-${row.ingredientCode}`}
                      className="block text-[11px] font-semibold text-[#4A6170]"
                    >
                      Status Pasokan
                    </label>
                    <select
                      id={`status-${row.ingredientCode}`}
                      value={row.deliveryMode}
                      onChange={(e) => {
                        const mode = e.target.value as DisruptionRowDraft["deliveryMode"];
                        setRowDrafts((prev) =>
                          prev.map((r, i) => (i === idx ? { ...r, deliveryMode: mode } : r))
                        );
                      }}
                      className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-2.5 text-xs text-[#16354A]"
                    >
                      <option value="NORMAL">Penyesuaian Stok / Harga</option>
                      <option value="PARTIAL">Pengiriman Parsial</option>
                      <option value="DELAYED">Pengiriman Tertunda</option>
                      <option value="UNAVAILABLE">Bahan Tidak Tersedia (0 kg)</option>
                    </select>
                  </div>

                  <div className="md:col-span-2">
                    <label
                      htmlFor={`rec-stock-${row.ingredientCode}`}
                      className="block text-[11px] font-semibold text-[#4A6170]"
                    >
                      Stok Siap Pakai (kg)
                    </label>
                    <NumericInput
                      id={`rec-stock-${row.ingredientCode}`}
                      label={`Stok siap pakai kg ${invItem?.name ?? row.ingredientCode}`}
                      mode="decimal"
                      min={0}
                      minErrorMessage="Stok tidak boleh negatif."
                      value={row.deliveryMode === "UNAVAILABLE" ? "0" : row.usableKgRaw}
                      disabled={row.deliveryMode === "UNAVAILABLE" || analyzeMutation.isPending}
                      error={stockErr}
                      onChange={(raw) => {
                        setBlurredMeta((p) => ({
                          ...p,
                          [`row-stock-${row.ingredientCode}`]: false,
                        }));
                        setRowDrafts((prev) =>
                          prev.map((r, i) => (i === idx ? { ...r, usableKgRaw: raw } : r))
                        );
                      }}
                      onBlurNormalize={() =>
                        setBlurredMeta((p) => ({
                          ...p,
                          [`row-stock-${row.ingredientCode}`]: true,
                        }))
                      }
                      className="mt-1"
                    />
                  </div>

                  <div className="md:col-span-3">
                    <label
                      htmlFor={`rec-price-${row.ingredientCode}`}
                      className="block text-[11px] font-semibold text-[#4A6170]"
                    >
                      Harga Terbaru (Rp/kg)
                    </label>
                    <NumericInput
                      id={`rec-price-${row.ingredientCode}`}
                      label={`Harga terbaru Rp per kg ${invItem?.name ?? row.ingredientCode}`}
                      mode="integer"
                      min={1}
                      minErrorMessage="Harga minimal Rp1/kg."
                      value={row.priceKgRaw}
                      disabled={analyzeMutation.isPending}
                      error={priceErr}
                      onChange={(raw) => {
                        setBlurredMeta((p) => ({
                          ...p,
                          [`row-price-${row.ingredientCode}`]: false,
                        }));
                        setRowDrafts((prev) =>
                          prev.map((r, i) => (i === idx ? { ...r, priceKgRaw: raw } : r))
                        );
                      }}
                      onBlurNormalize={() =>
                        setBlurredMeta((p) => ({
                          ...p,
                          [`row-price-${row.ingredientCode}`]: true,
                        }))
                      }
                      className="mt-1"
                    />
                  </div>

                  <div className="md:col-span-1 flex md:justify-end md:pt-5">
                    <button
                      type="button"
                      aria-label={`Hapus penyesuaian ${row.ingredientCode}`}
                      onClick={() =>
                        setRowDrafts((prev) => prev.filter((_, i) => i !== idx))
                      }
                      className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-[#DCE6DE] bg-white text-[#991B1B] hover:bg-[#FEF0F0]"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex flex-col gap-3 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-[#4A6170]">
            {hasInvalidInputs ? (
              <p className="font-semibold text-[#991B1B]" role="alert">
                Periksa kembali angka yang belum valid sebelum menjalankan optimasi pemulihan.
              </p>
            ) : (
              <p>
                Sistem akan menghitung <strong>Alternatif A (Minim Perubahan Menu)</strong> dan{" "}
                <strong>Alternatif B (Biaya Bahan Terendah)</strong> dengan aturan gizi penuh.
              </p>
            )}
          </div>
          <button
            type="button"
            data-testid="btn-compute-recovery"
            disabled={analyzeMutation.isPending || hasInvalidInputs}
            onClick={() => analyzeMutation.mutate()}
            className="inline-flex min-h-[44px] shrink-0 items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
          >
            {analyzeMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                <span>Menghitung Pemulihan...</span>
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                <span>Hitung Alternatif Pemulihan</span>
              </>
            )}
          </button>
        </div>

        {actionError && <ErrorState title="Pemulihan Gagal" message={actionError} />}
      </section>

      {/* LANGKAH 3: PILIH ALTERNATIF PENGGANTI */}
      {activeEvent && (
        <section className="space-y-4 rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex flex-wrap items-start justify-between gap-2 border-b border-[#EEF3EE] pb-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-block rounded-full bg-[#EBF6F5] px-2.5 py-0.5 text-[11px] font-bold text-[#0F766E]">
                  LANGKAH 3 — BANDINGKAN & PILIH ALTERNATIF
                </span>
                {activeEvent.incident_id && (
                  <StatusBadge
                    tone="critical"
                    label="Terkait Insiden Bahan (Lot SAFETY HOLD Dikecualikan)"
                  />
                )}
              </div>
              <h2 className="mt-1 text-base font-bold text-[#16354A]">{activeEvent.title}</h2>
            </div>
            <StatusBadge
              tone={formatRecoveryStatus(activeEvent.status).tone}
              label={formatRecoveryStatus(activeEvent.status).label}
            />
          </div>

          {activeEvent.is_stale_inventory && (
            <div
              role="alert"
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-3.5 text-xs text-[#991B1B]"
            >
              <div className="flex items-start gap-2">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>
                  <strong>Stok gudang berubah setelah hasil ini dihitung.</strong> Hitung ulang
                  alternatif sebelum mengajukan persetujuan agar tidak ditolak oleh snapshot guard.
                </span>
              </div>
              <button
                type="button"
                onClick={() => analyzeMutation.mutate()}
                className="inline-flex min-h-[38px] items-center gap-1 rounded-lg bg-[#991B1B] px-3 py-1.5 font-semibold text-white"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Hitung Ulang</span>
              </button>
            </div>
          )}

          {/* Fair 4-Way Counterfactual Disclosure */}
          <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-4 space-y-3 text-xs">
            <p className="font-semibold text-[#16354A]">
              Perbandingan Adil pada Kondisi Terbaru
            </p>
            <p className="leading-relaxed text-[#4A6170]">
              {activeEvent.comparison.comparison_notice}
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-[#DCE6DE] bg-white p-3">
                <span className="block text-[11px] font-medium text-[#647A87]">
                  Menu Asli pada Kondisi Lama (Konteks Historis)
                </span>
                <strong className="mt-1 block text-sm text-[#16354A] tabular-nums">
                  {formatIDR(activeEvent.comparison.original_historical.total_cost_idr)}
                </strong>
                <span className="block text-[11px] text-[#647A87]">
                  {formatIDR(activeEvent.comparison.original_historical.cost_per_serving_idr)}/porsi
                  {activeEvent.comparison.original_historical.cost_per_day_average_idr
                    ? ` • ${formatIDR(activeEvent.comparison.original_historical.cost_per_day_average_idr)}/hari`
                    : ""}
                </span>
                {activeEvent.comparison.original_historical.total_servings && (
                  <span className="block text-[11px] text-[#647A87]">
                    {activeEvent.comparison.original_historical.days_count} hari ×{" "}
                    {activeEvent.comparison.original_historical.servings_per_day} porsi ={" "}
                    {activeEvent.comparison.original_historical.total_servings.toLocaleString("id-ID")} total porsi
                  </span>
                )}
              </div>
              <div
                className={`rounded-lg border p-3 ${
                  activeEvent.comparison.original_under_new_conditions.feasible
                    ? "border-[#DCE6DE] bg-white"
                    : "border-[#F5C2C2] bg-[#FEF0F0]/60"
                }`}
              >
                <span className="block text-[11px] font-medium text-[#647A87]">
                  Menu Asli Dievaluasi pada Kondisi Baru (Kontrafaktual)
                </span>
                <strong className="mt-1 block text-sm text-[#16354A] tabular-nums">
                  {activeEvent.comparison.original_under_new_conditions.feasible
                    ? formatIDR(activeEvent.comparison.original_under_new_conditions.total_cost_idr)
                    : "TIDAK LAYAK (Melanggar Stok / Anggaran / Gizi)"}
                </strong>
                <span className="text-[11px] text-[#526675]">
                  {activeEvent.comparison.original_under_new_conditions.notes}
                </span>
              </div>
            </div>
          </div>

          {/* Deduplicated Candidate Cards */}
          {activeEvent.comparison.min_disruption_vs_min_cost_identical &&
          activeEvent.min_disruption.validation_passed ? (
            <CandidateCard
              title="Alternatif Optimal Tunggal (Minim Perubahan = Biaya Terendah)"
              subtitle="Alternatif minim perubahan sekaligus menghasilkan total biaya bahan terendah yang layak."
              candidate={activeEvent.min_disruption}
              selected={selectedMode === "MIN_DISRUPTION"}
              onSelect={() => setSelectedMode("MIN_DISRUPTION")}
              highlightNote="Tidak ada perbedaan jadwal antara kedua mode optimasi."
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <CandidateCard
                title="Alternatif A — Minim Perubahan Menu"
                subtitle="Mempertahankan sebanyak mungkin resep disetujui dan mengganti slot yang terdampak saja."
                candidate={activeEvent.min_disruption}
                selected={selectedMode === "MIN_DISRUPTION"}
                onSelect={() => setSelectedMode("MIN_DISRUPTION")}
                highlightNote="Direkomendasikan untuk menjaga stabilitas dapur & pengadaan."
              />
              <CandidateCard
                title="Alternatif B — Biaya Bahan Terendah"
                subtitle="Mencari total biaya pengadaan serendah mungkin pada stok dan harga terbaru."
                candidate={activeEvent.min_cost}
                selected={selectedMode === "MIN_COST"}
                onSelect={() => setSelectedMode("MIN_COST")}
                highlightNote={
                  activeEvent.comparison.savings_by_choosing_min_cost_over_min_disruption_idr !==
                    null &&
                  activeEvent.comparison.savings_by_choosing_min_cost_over_min_disruption_idr > 0
                    ? `Lebih hemat ${formatIDR(
                        activeEvent.comparison.savings_by_choosing_min_cost_over_min_disruption_idr
                      )} dibanding Alternatif A dengan ${
                        activeEvent.comparison.extra_slots_changed_for_min_cost ?? 0
                      } tambahan perubahan slot.`
                    : undefined
                }
              />
            </div>
          )}

          {/* Collapsible Procurement Delta */}
          <div className="rounded-xl border border-[#DCE6DE] bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <button
                type="button"
                onClick={() => setShowProcurement((p) => !p)}
                className="inline-flex min-h-[38px] items-center gap-2 text-xs font-bold text-[#16354A]"
              >
                <span>
                  Rincian Kebutuhan Pembelian ({procurementItems.length} bahan untuk{" "}
                  {selectedMode === "MIN_DISRUPTION" ? "Alternatif A" : "Alternatif B"})
                </span>
                {showProcurement ? (
                  <ChevronUp className="h-4 w-4 text-[#0F766E]" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-[#0F766E]" />
                )}
              </button>

              {activeChosenCandidate?.validation_passed && (
                <a
                  href={apiClient.getRecoveryProcurementCsvUrl(activeEvent.id, selectedMode)}
                  className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border border-[#B5DFDA] bg-[#EBF6F5] px-3 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#DDF0EE]"
                >
                  <Download className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Unduh CSV Delta Belanja</span>
                </a>
              )}
            </div>

            {showProcurement && (
              <div className="border-t border-[#DCE6DE] overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#F5F8F5] text-[#4A6170]">
                    <tr>
                      <th className="px-3.5 py-2 font-semibold">Bahan</th>
                      <th className="px-3.5 py-2 text-right font-semibold">Butuh Baru</th>
                      <th className="px-3.5 py-2 text-right font-semibold">Stok Siap Pakai</th>
                      <th className="px-3.5 py-2 text-right font-semibold">Tertunda</th>
                      <th className="px-3.5 py-2 text-right font-semibold">Perlu Beli Mendesak</th>
                      <th className="px-3.5 py-2 font-semibold">Keterangan</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#EEF3EE] tabular-nums">
                    {procurementItems.map((item) => (
                      <tr key={item.ingredient_code}>
                        <td className="px-3.5 py-2 font-semibold text-[#16354A]">
                          {item.ingredient_name}
                        </td>
                        <td className="px-3.5 py-2 text-right">
                          {formatDecimal(item.required_kg, 2)} kg
                        </td>
                        <td className="px-3.5 py-2 text-right">
                          {formatDecimal(item.usable_on_hand_kg, 2)} kg
                        </td>
                        <td className="px-3.5 py-2 text-right text-[#8A5300]">
                          {item.incoming_kg > 0
                            ? `${formatDecimal(item.incoming_kg, 2)} kg (${item.delivery_status})`
                            : "—"}
                        </td>
                        <td className="px-3.5 py-2 text-right font-bold text-[#0F766E]">
                          {item.net_to_buy_kg > 0
                            ? `${formatDecimal(item.net_to_buy_kg, 2)} kg`
                            : "0 kg"}
                        </td>
                        <td className="px-3.5 py-2 text-[11px] text-[#526675]">{item.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* LANGKAH 4: AJUKAN RENCANA PENGGANTI */}
          {activeChosenCandidate?.validation_passed &&
            activeEvent.status !== "SUBMITTED" &&
            activeEvent.status !== "APPROVED" && (
              <div className="rounded-xl border border-[#B5DFDA] bg-[#F4FAF9] p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="inline-block rounded-full bg-white px-2.5 py-0.5 text-[11px] font-bold text-[#0F766E] border border-[#B5DFDA]">
                      LANGKAH 4 — TINJAUAN & PENGAJUAN
                    </span>
                    <h3 className="mt-1 text-sm font-bold text-[#16354A]">
                      Ajukan{" "}
                      {selectedMode === "MIN_DISRUPTION"
                        ? "Alternatif A (Minim Perubahan)"
                        : "Alternatif B (Biaya Minimum)"}{" "}
                      ke Kepala Dapur
                    </h3>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div>
                    <label
                      htmlFor="rec-proposal-title"
                      className="block text-xs font-semibold text-[#4A6170]"
                    >
                      Judul Pengajuan Rencana Pengganti
                    </label>
                    <input
                      id="rec-proposal-title"
                      type="text"
                      value={proposalTitle}
                      onChange={(e) => setProposalTitle(e.target.value)}
                      className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="rec-proposal-notes"
                      className="block text-xs font-semibold text-[#4A6170]"
                    >
                      Catatan untuk Kepala Dapur
                    </label>
                    <input
                      id="rec-proposal-notes"
                      type="text"
                      value={plannerNotes}
                      onChange={(e) => setPlannerNotes(e.target.value)}
                      className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-[#4A6170]">
                    Persetujuan tetap menunggu keputusan Kepala Dapur (tidak mengubah menu lama secara sepihak).
                  </p>
                  <button
                    type="button"
                    data-testid="btn-submit-recovery"
                    disabled={submitMutation.isPending || activeEvent.is_stale_inventory}
                    onClick={() => submitMutation.mutate()}
                    className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                  >
                    {submitMutation.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                        <span>Mengajukan...</span>
                      </>
                    ) : (
                      <>
                        <Send className="h-4 w-4" aria-hidden="true" />
                        <span>Ajukan Rencana Pengganti</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

          {submitSuccess && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] p-4 text-sm text-[#0F766E]">
              <div className="flex items-center gap-2 font-semibold">
                <CheckCircle2 className="h-5 w-5 shrink-0" aria-hidden="true" />
                <span>{submitSuccess}</span>
              </div>
              <Link
                href={
                  activeChosenCandidate?.run_id
                    ? `/menu-planning?run=${activeChosenCandidate.run_id}`
                    : "/menu-planning"
                }
                className="inline-flex min-h-[40px] items-center rounded-xl bg-white px-3.5 py-1.5 text-xs font-bold text-[#0F766E] border border-[#B5DFDA]"
              >
                Lihat di Perencanaan Menu
              </Link>
            </div>
          )}
        </section>
      )}

      {/* Recent recovery history strip */}
      {(historyQuery.data?.length ?? 0) > 0 && (
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <h3 className="text-sm font-bold text-[#16354A]">Riwayat Pemulihan Gangguan Terbaru</h3>
          <div className="mt-3 space-y-2">
            {historyQuery.data!.slice(0, 5).map((ev) => {
              const st = formatRecoveryStatus(ev.status);
              return (
                <div
                  key={ev.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#EEF3EE] bg-[#F5F8F5] px-3.5 py-2.5 text-xs"
                >
                  <div>
                    <p className="font-bold text-[#16354A]">{ev.title}</p>
                    <p className="text-[#647A87]">
                      {ev.disruption_types.map(formatDisruptionTypeLabel).join(", ")} •{" "}
                      {ev.min_disruption.changed_slots_count} slot diubah (Minim Perubahan)
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={st.tone} label={st.label} />
                    <button
                      type="button"
                      onClick={() => {
                        setActiveEvent(ev);
                        setSelectedMode(ev.selected_mode ?? "MIN_DISRUPTION");
                      }}
                      className="min-h-[36px] rounded-lg border border-[#DCE6DE] bg-white px-3 py-1 font-semibold text-[#0F766E] hover:bg-[#EBF6F5]"
                    >
                      Buka
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function CandidateCard({
  title,
  subtitle,
  candidate,
  selected,
  onSelect,
  highlightNote,
}: {
  title: string;
  subtitle: string;
  candidate: CandidatePlanSummary;
  selected: boolean;
  onSelect: () => void;
  highlightNote?: string;
}) {
  if (!candidate.validation_passed) {
    return (
      <div className="rounded-xl border border-[#F5C2C2] bg-[#FEF0F0]/60 p-4 space-y-2.5 text-xs">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[#991B1B]">{title}</h3>
            <p className="mt-0.5 text-[#7F1D1D]">{subtitle}</p>
          </div>
          <StatusBadge tone="critical" label="Tidak Layak (INFEASIBLE)" />
        </div>
        <p className="font-semibold text-[#991B1B]">
          Tidak ada kombinasi resep aman & bergizi yang memenuhi seluruh batasan pada kondisi ini.
        </p>
        {candidate.constraint_diagnostics.length > 0 && (
          <ul className="list-disc pl-4 space-y-1 text-[#7F1D1D]">
            {candidate.constraint_diagnostics.map((d, idx) => (
              <li key={idx}>{d.message}</li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  return (
    <div
      className={`rounded-xl border p-4 space-y-3 transition ${
        selected
          ? "border-[#0F766E] bg-[#F4FAF9] ring-1 ring-[#0F766E]"
          : "border-[#DCE6DE] bg-white"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-[#16354A]">{title}</h3>
          <p className="mt-0.5 text-xs text-[#647A87]">{subtitle}</p>
        </div>
        <StatusBadge
          tone="success"
          label={`${candidate.changed_slots_count} dari ${candidate.total_slots_count} slot diubah`}
        />
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 text-xs">
        <div className="rounded-lg border border-[#DCE6DE] bg-white p-2.5">
          <span className="block text-[11px] text-[#647A87]">Total Biaya Kondisi Baru</span>
          <strong className="mt-0.5 block text-sm text-[#16354A] tabular-nums">
            {formatIDR(candidate.total_cost_idr)}
          </strong>
        </div>
        <div className="rounded-lg border border-[#DCE6DE] bg-white p-2.5">
          <span className="block text-[11px] text-[#647A87]">Biaya per Porsi</span>
          <strong className="mt-0.5 block text-sm text-[#0F766E] tabular-nums">
            {formatIDR(candidate.cost_per_serving_idr)}
          </strong>
        </div>
        <div className="rounded-lg border border-[#DCE6DE] bg-white p-2.5">
          <span className="block text-[11px] text-[#647A87]">Rata-rata per Hari</span>
          <strong className="mt-0.5 block text-sm text-[#16354A] tabular-nums">
            {candidate.cost_per_day_average_idr ? formatIDR(candidate.cost_per_day_average_idr) : "—"}
          </strong>
        </div>
      </div>

      {candidate.total_servings && (
        <p className="text-[11px] text-[#4A6170] tabular-nums">
          Rekonsiliasi kapasitas: <strong>{candidate.days_count} hari</strong> ×{" "}
          <strong>{candidate.servings_per_day} porsi/hari</strong> ={" "}
          <strong>{candidate.total_servings.toLocaleString("id-ID")} total porsi</strong> (
          {candidate.total_menu_slots ?? candidate.total_slots_count} slot hidangan).
        </p>
      )}

      {candidate.delta_vs_original_at_new_conditions_idr !== null && (
        <p className="text-[11px] font-medium text-[#4A6170] tabular-nums">
          Selisih terhadap rencana asli pada kondisi baru:{" "}
          <strong>{formatSignedIDR(candidate.delta_vs_original_at_new_conditions_idr)}</strong>
        </p>
      )}

      {highlightNote && (
        <p className="rounded-lg bg-white px-2.5 py-1.5 text-[11px] font-medium text-[#0F766E] border border-[#DCE6DE]">
          {highlightNote}
        </p>
      )}

      {candidate.changed_slots.length === 0 ? (
        <p className="text-xs font-medium text-[#0F766E]">
          0 slot perlu diganti — rencana asli tetap berlaku utuh.
        </p>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {candidate.changed_slots.map((swap) => (
            <li
              key={`${swap.day_index}-${swap.slot}`}
              className="rounded-lg border border-[#DCE6DE] bg-white px-3 py-2"
            >
              <div className="flex flex-wrap items-center gap-1.5 font-semibold text-[#16354A]">
                <span>Hari {swap.day_index}</span>
                <span>•</span>
                <span>{formatSlotLabel(swap.slot)}:</span>
                <span className="line-through text-[#991B1B]">{swap.original_recipe_name}</span>
                <ArrowRight className="h-3.5 w-3.5 text-[#0F766E]" aria-hidden="true" />
                <span className="text-[#0F766E]">{swap.new_recipe_name}</span>
              </div>
              <p className="mt-0.5 text-[11px] text-[#526675]">{swap.reason}</p>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        data-testid={`select-mode-${candidate.mode}`}
        onClick={onSelect}
        className={`min-h-[42px] w-full rounded-xl px-4 py-2 text-xs font-bold transition ${
          selected
            ? "bg-[#0F766E] text-white"
            : "border border-[#0F766E] bg-white text-[#0F766E] hover:bg-[#EBF6F5]"
        }`}
      >
        {selected ? "Terpilih untuk Diajukan" : `Pilih ${title.split("—")[0].trim()}`}
      </button>
    </div>
  );
}
