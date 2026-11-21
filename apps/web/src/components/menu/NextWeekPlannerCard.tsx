"use client";

import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Info,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatIDR,
  formatMenuReviewStatus,
  formatOperationalStatus,
  formatPeriodPhase,
  formatSignedIDR,
} from "@/lib/formatters/indonesian";
import { formatJakartaDate } from "@/lib/formatters/jakartaDate";
import type { OptimizationRunResponse } from "@/types/api";

interface NextWeekPlannerCardProps {
  selectedRun?: OptimizationRunResponse | null;
}

function formatRange(dates?: string[] | null, start?: string | null, end?: string | null): string {
  const s = start ?? dates?.[0];
  const e = end ?? dates?.[dates.length - 1];
  if (!s) return "Tanggal belum ditetapkan";
  if (!e || s === e) return formatJakartaDate(s);
  return `${formatJakartaDate(s)} s.d. ${formatJakartaDate(e)}`;
}

export function NextWeekPlannerCard({ selectedRun }: NextWeekPlannerCardProps) {
  const { user } = useAuth();
  const { setSelectedRunId, refreshAll } = useWorkspace();
  const qc = useQueryClient();
  const kitchenId = user?.active_kitchen_id;
  const isPlanner = user?.active_role === "MENU_PLANNER";
  const canView =
    user?.active_role === "MENU_PLANNER" || user?.active_role === "KITCHEN_MANAGER";

  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState("");
  const [dates, setDates] = useState<string[]>([]);
  const [servingsPerDay, setServingsPerDay] = useState<string>("100");
  const [budgetPerServing, setBudgetPerServing] = useState<string>("12000");
  const [plannerNotes, setPlannerNotes] = useState("");
  const [formInitialized, setFormInitialized] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const opPlansQuery = useQuery({
    queryKey: ["operational-plans", kitchenId, "active-only"],
    queryFn: () => apiClient.listOperationalPlans(undefined, false),
    enabled: Boolean(canView && kitchenId),
  });

  const reviewsQuery = useQuery({
    queryKey: ["menu-reviews", kitchenId],
    queryFn: () => apiClient.listMenuReviews(),
    enabled: Boolean(canView && kitchenId),
  });

  const activePlans = opPlansQuery.data ?? [];
  const preferredAssignment = useMemo(() => {
    if (selectedRun?.dataset_version_id) {
      const dsMatch =
        activePlans.find(
          (p) =>
            p.dataset_version_id === selectedRun.dataset_version_id &&
            p.derived_period_phase === "IN_PROGRESS"
        ) ?? activePlans.find((p) => p.dataset_version_id === selectedRun.dataset_version_id);
      if (dsMatch) return dsMatch;
    }
    return null;
  }, [activePlans, selectedRun?.dataset_version_id]);

  const sourceAssignmentId = preferredAssignment?.id ?? (selectedRun?.validation_passed ? undefined : activePlans[0]?.id);
  const sourceRunId =
    sourceAssignmentId === undefined ? selectedRun?.run_id : preferredAssignment?.run_id;

  const defaultsQuery = useQuery({
    queryKey: ["next-week-defaults", kitchenId, sourceAssignmentId ?? sourceRunId],
    queryFn: () =>
      apiClient.getNextWeekDefaults({
        sourceAssignmentId,
        sourceRunId,
      }),
    enabled: Boolean(isPlanner && formOpen && kitchenId),
  });

  // Hydrate editable defaults once when form opens & defaults arrive
  React.useEffect(() => {
    if (!formOpen || formInitialized || !defaultsQuery.data) return;
    const d = defaultsQuery.data;
    setName(d.suggested_name);
    setDates(d.suggested_service_dates);
    setServingsPerDay(String(d.servings_per_day));
    setBudgetPerServing(String(Math.round(d.budget_idr_per_serving)));
    setFormInitialized(true);
  }, [defaultsQuery.data, formInitialized, formOpen]);

  const currentPeriodPlan = useMemo(() => {
    return (
      preferredAssignment ??
      activePlans.find((p) => p.derived_period_phase === "IN_PROGRESS") ??
      activePlans.find((p) => p.operational_status === "ACTIVE") ??
      activePlans[0] ??
      null
    );
  }, [activePlans, preferredAssignment]);

  const upcomingPlanOrReview = useMemo(() => {
    const activeUpcoming = activePlans.find(
      (p) => p.id !== currentPeriodPlan?.id && p.derived_period_phase === "UPCOMING"
    );
    if (activeUpcoming) {
      return {
        kind: "plan" as const,
        title: activeUpcoming.plan_title,
        runId: activeUpcoming.run_id,
        serviceDates: activeUpcoming.service_dates ?? [],
        periodStart: activeUpcoming.period_start_date,
        periodEnd: activeUpcoming.period_end_date,
        phase: activeUpcoming.derived_period_phase,
        opStatus: activeUpcoming.operational_status,
        reviewStatus: activeUpcoming.historical_review_status,
        stockConfirmationRequired: false,
      };
    }
    const nextReview = (reviewsQuery.data ?? []).find(
      (r) =>
        r.run_id !== currentPeriodPlan?.run_id &&
        (Boolean(r.continuation_of_run_id) || r.derived_period_phase === "UPCOMING") &&
        r.operational_status !== "SUPERSEDED"
    );
    if (nextReview) {
      return {
        kind: "review" as const,
        title: nextReview.title,
        runId: nextReview.run_id,
        serviceDates: nextReview.service_dates ?? [],
        periodStart: nextReview.period_start_date,
        periodEnd: nextReview.period_end_date,
        phase: nextReview.derived_period_phase,
        opStatus: nextReview.operational_status,
        reviewStatus: nextReview.status,
        stockConfirmationRequired: Boolean(nextReview.stock_confirmation_required),
      };
    }
    return null;
  }, [activePlans, currentPeriodPlan, reviewsQuery.data]);

  const prepareMutation = useMutation({
    mutationFn: () => {
      const cleanedDates = Array.from(new Set(dates.filter(Boolean))).sort();
      if (cleanedDates.length === 0) {
        throw new Error("Pilih minimal 1 tanggal pelayanan untuk periode berikutnya.");
      }
      const serv = Number(servingsPerDay);
      const bud = Number(budgetPerServing);
      if (!Number.isFinite(serv) || serv < 1) {
        throw new Error("Jumlah porsi per hari harus minimal 1.");
      }
      if (!Number.isFinite(bud) || bud <= 0) {
        throw new Error("Batas anggaran per porsi harus lebih dari 0.");
      }
      return apiClient.prepareNextWeek({
        source_assignment_id: defaultsQuery.data?.source_assignment_id ?? undefined,
        source_run_id: defaultsQuery.data?.source_run_id ?? sourceRunId ?? selectedRun?.run_id,
        name: name.trim() || undefined,
        service_dates: cleanedDates,
        servings_per_day: Math.round(serv),
        budget_idr_per_serving: bud,
        planner_notes: plannerNotes.trim() || undefined,
      });
    },
    onSuccess: async (res) => {
      setFeedback({
        type: "ok",
        text: res.validation_passed
          ? `Draf minggu berikutnya tersimpan (${res.service_dates.length} hari pelayanan). Rencana minggu berjalan tidak diubah.`
          : "Perhitungan selesai namun belum ditemukan kombinasi layak. Periksa stok/anggaran atau sesuaikan tanggal.",
      });
      setFormOpen(false);
      setFormInitialized(false);
      setPlannerNotes("");
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["runs"] }),
        qc.invalidateQueries({ queryKey: ["scenarios"] }),
        qc.invalidateQueries({ queryKey: ["menu-reviews"] }),
        qc.invalidateQueries({ queryKey: ["operational-plans"] }),
        qc.invalidateQueries({ queryKey: ["next-week-defaults"] }),
      ]);
      setSelectedRunId(res.run_id);
      refreshAll();
    },
    onError: (err) => {
      setFeedback({
        type: "err",
        text:
          err instanceof ApiError || err instanceof Error
            ? err.message
            : "Gagal menyiapkan menu minggu berikutnya.",
      });
    },
  });

  if (!canView) return null;

  const addOneDate = () => {
    if (dates.length >= 14) return;
    const baseStr = dates[dates.length - 1] ?? new Date().toISOString().slice(0, 10);
    const dt = new Date(`${baseStr}T08:00:00+07:00`);
    dt.setDate(dt.getDate() + 1);
    while (dt.getDay() === 0 || dt.getDay() === 6) {
      dt.setDate(dt.getDate() + 1);
    }
    const nextIso = dt.toISOString().slice(0, 10);
    setDates((prev) => [...prev, nextIso]);
  };

  const historyCtx = selectedRun?.history_context;
  const comparison = historyCtx?.comparison;

  return (
    <section
      aria-label="Perencanaan Menu Lintas Minggu"
      className="rounded-2xl border border-[#DCE6DE] bg-white p-4 shadow-[0_1px_2px_rgba(22,53,74,0.04)] space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <CalendarDays className="mt-0.5 h-5 w-5 shrink-0 text-[#0F766E]" aria-hidden="true" />
          <div>
            <h2 className="text-sm font-bold text-[#16354A]">
              Periode Pelayanan & Kelanjutan Mingguan
            </h2>
            <p className="text-xs text-[#647A87]">
              Pantau periode berjalan dan siapkan draf minggu berikutnya dengan histori menu &amp; stok terkini tanpa mengaktifkan otomatis.
            </p>
          </div>
        </div>
        {isPlanner && (
          <button
            type="button"
            onClick={() => {
              setFeedback(null);
              setFormOpen((prev) => {
                if (prev) setFormInitialized(false);
                return !prev;
              });
            }}
            className="inline-flex min-h-[42px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-bold text-white hover:bg-[#0B5F58]"
          >
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            <span>Siapkan Menu Minggu Berikutnya</span>
            {formOpen ? (
              <ChevronUp className="h-4 w-4" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-4 w-4" aria-hidden="true" />
            )}
          </button>
        )}
      </div>

      {/* Period Summary Grid: Current vs Next Period */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/70 p-3.5 space-y-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[#647A87]">
              Periode Berjalan
            </span>
            <div className="flex flex-wrap gap-1.5">
              {currentPeriodPlan?.derived_period_phase && formatPeriodPhase(currentPeriodPlan.derived_period_phase) && (
                <StatusBadge
                  tone={formatPeriodPhase(currentPeriodPlan.derived_period_phase)!.tone}
                  label={formatPeriodPhase(currentPeriodPlan.derived_period_phase)!.label}
                />
              )}
              {currentPeriodPlan && (
                <StatusBadge
                  tone={formatOperationalStatus(currentPeriodPlan.operational_status).tone}
                  label={formatOperationalStatus(currentPeriodPlan.operational_status).label}
                />
              )}
            </div>
          </div>
          {currentPeriodPlan ? (
            <>
              <button
                type="button"
                onClick={() => setSelectedRunId(currentPeriodPlan.run_id)}
                className="text-left text-sm font-bold text-[#16354A] hover:text-[#0F766E] hover:underline"
              >
                {currentPeriodPlan.plan_title}
              </button>
              <p className="text-xs text-[#4A6170]">
                {formatRange(
                  currentPeriodPlan.service_dates,
                  currentPeriodPlan.period_start_date,
                  currentPeriodPlan.period_end_date
                )}{" "}
                · {currentPeriodPlan.horizon_days} hari pelayanan
              </p>
            </>
          ) : (
            <p className="text-xs text-[#647A87]">
              Belum ada rencana operasional aktif untuk periode berjalan.
            </p>
          )}
        </div>

        <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/70 p-3.5 space-y-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[#647A87]">
              Periode Berikutnya
            </span>
            <div className="flex flex-wrap gap-1.5">
              {upcomingPlanOrReview?.phase && formatPeriodPhase(upcomingPlanOrReview.phase) && (
                <StatusBadge
                  tone={formatPeriodPhase(upcomingPlanOrReview.phase)!.tone}
                  label={formatPeriodPhase(upcomingPlanOrReview.phase)!.label}
                />
              )}
              {upcomingPlanOrReview && (
                <StatusBadge
                  tone={
                    upcomingPlanOrReview.opStatus
                      ? formatOperationalStatus(upcomingPlanOrReview.opStatus).tone
                      : formatMenuReviewStatus(
                          upcomingPlanOrReview.reviewStatus as
                            | "DRAFT"
                            | "SUBMITTED"
                            | "APPROVED"
                            | "REVISION_REQUIRED"
                        ).tone
                  }
                  label={
                    upcomingPlanOrReview.opStatus
                      ? formatOperationalStatus(upcomingPlanOrReview.opStatus).label
                      : formatMenuReviewStatus(
                          upcomingPlanOrReview.reviewStatus as
                            | "DRAFT"
                            | "SUBMITTED"
                            | "APPROVED"
                            | "REVISION_REQUIRED"
                        ).label
                  }
                />
              )}
            </div>
          </div>
          {upcomingPlanOrReview ? (
            <>
              <button
                type="button"
                onClick={() => setSelectedRunId(upcomingPlanOrReview.runId)}
                className="text-left text-sm font-bold text-[#16354A] hover:text-[#0F766E] hover:underline"
              >
                {upcomingPlanOrReview.title}
              </button>
              <p className="text-xs text-[#4A6170]">
                {formatRange(
                  upcomingPlanOrReview.serviceDates,
                  upcomingPlanOrReview.periodStart,
                  upcomingPlanOrReview.periodEnd
                )}
              </p>
              {upcomingPlanOrReview.stockConfirmationRequired && (
                <p className="text-[11px] font-semibold text-[#92400E]">
                  Perlu Konfirmasi Stok sebelum diaktifkan Kepala Dapur.
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-[#647A87]">
              Belum ada draf atau rencana untuk minggu berikutnya.
            </p>
          )}
        </div>
      </div>

      {/* Inline "Siapkan Menu Minggu Berikutnya" Form (Planner only) */}
      {isPlanner && formOpen && (
        <div className="rounded-xl border border-[#B5DFDA] bg-[#F4FAF9] p-4 space-y-4">
          {defaultsQuery.isLoading ? (
            <p className="flex items-center gap-2 text-xs text-[#4A6170]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Menyiapkan usulan tanggal, konfigurasi, histori menu, dan stok terkini...
            </p>
          ) : defaultsQuery.error ? (
            <p className="text-xs font-medium text-[#991B1B]">
              {defaultsQuery.error.message}
            </p>
          ) : (
            <>
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-[#16354A]">
                  Konfigurasi Draf Minggu Berikutnya
                </h3>
                <p className="text-xs text-[#4A6170]">
                  Mengambil konfigurasi dari{" "}
                  <strong>{defaultsQuery.data?.source_plan_title ?? "dataset aktif"}</strong> tanpa
                  mewariskan override harga/stok simulasi lama. Hasil tersimpan sebagai{" "}
                  <strong>DRAF BARU</strong> dan tidak mengubah minggu berjalan.
                </p>
              </div>

              {defaultsQuery.data?.history_source_notice && (
                <div className="flex items-start gap-2 rounded-lg border border-[#DCE6DE] bg-white p-2.5 text-xs text-[#4A6170]">
                  <Info className="mt-0.5 h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
                  <span>{defaultsQuery.data.history_source_notice}</span>
                </div>
              )}

              {defaultsQuery.data?.stock_confirmation_required &&
                defaultsQuery.data.stock_confirmation_reason && (
                  <div
                    role="status"
                    className="flex items-start gap-2 rounded-lg border border-[#F3D19B] bg-[#FFFBEB] p-3 text-xs text-[#92400E]"
                  >
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <div>
                      <strong className="block">Perlu Konfirmasi Stok</strong>
                      <span>{defaultsQuery.data.stock_confirmation_reason}</span>
                    </div>
                  </div>
                )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="sm:col-span-3">
                  <label htmlFor="nw-name" className="block text-xs font-semibold text-[#16354A]">
                    Nama Rencana Minggu Berikutnya
                  </label>
                  <input
                    id="nw-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="mt-1 min-h-[40px] w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                  />
                </div>
                <div>
                  <label htmlFor="nw-servings" className="block text-xs font-semibold text-[#16354A]">
                    Porsi per Hari
                  </label>
                  <input
                    id="nw-servings"
                    type="number"
                    min={1}
                    max={10000}
                    value={servingsPerDay}
                    onChange={(e) => setServingsPerDay(e.target.value)}
                    className="mt-1 min-h-[40px] w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                  />
                </div>
                <div>
                  <label htmlFor="nw-budget" className="block text-xs font-semibold text-[#16354A]">
                    Batas Anggaran/Porsi (Rp)
                  </label>
                  <input
                    id="nw-budget"
                    type="number"
                    min={1000}
                    step={500}
                    value={budgetPerServing}
                    onChange={(e) => setBudgetPerServing(e.target.value)}
                    className="mt-1 min-h-[40px] w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                  />
                </div>
                <div>
                  <label htmlFor="nw-notes" className="block text-xs font-semibold text-[#16354A]">
                    Catatan Perencana (Opsional)
                  </label>
                  <input
                    id="nw-notes"
                    type="text"
                    value={plannerNotes}
                    onChange={(e) => setPlannerNotes(e.target.value)}
                    placeholder="Mis. penyesuaian hari libur"
                    className="mt-1 min-h-[40px] w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                  />
                </div>
              </div>

              {/* Simple editable service date list (supports holiday adjustments without complex calendar) */}
              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-[#16354A]">
                    Tanggal Pelayanan ({dates.length} hari — sesuaikan bila ada hari libur)
                  </span>
                  {dates.length < 14 && (
                    <button
                      type="button"
                      onClick={addOneDate}
                      className="inline-flex items-center gap-1 rounded-lg border border-[#B5DFDA] bg-white px-2.5 py-1 text-xs font-semibold text-[#0F766E] hover:bg-[#EBF6F5]"
                    >
                      <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                      Tambah Hari
                    </button>
                  )}
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
                  {dates.map((d, idx) => (
                    <div
                      key={`${idx}-${d}`}
                      className="flex items-center gap-1.5 rounded-xl border border-[#DCE6DE] bg-white px-2.5 py-1.5"
                    >
                      <span className="shrink-0 text-[11px] font-bold text-[#0F766E]">
                        H{idx + 1}
                      </span>
                      <input
                        type="date"
                        aria-label={`Tanggal pelayanan Hari ${idx + 1}`}
                        value={d}
                        onChange={(e) => {
                          const val = e.target.value;
                          setDates((prev) => prev.map((x, i) => (i === idx ? val : x)));
                        }}
                        className="min-w-0 flex-1 bg-transparent text-xs font-medium text-[#16354A] focus:outline-none"
                      />
                      {dates.length > 1 && (
                        <button
                          type="button"
                          aria-label={`Hapus Hari ${idx + 1}`}
                          onClick={() => setDates((prev) => prev.filter((_, i) => i !== idx))}
                          className="rounded p-1 text-[#647A87] hover:text-[#991B1B]"
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 pt-1">
                <button
                  type="button"
                  disabled={prepareMutation.isPending}
                  onClick={() => prepareMutation.mutate()}
                  className="inline-flex min-h-[42px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-bold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                >
                  {prepareMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                  )}
                  <span>
                    {prepareMutation.isPending
                      ? "Menghitung Draf Minggu Berikutnya..."
                      : "Hitung & Simpan Draf Minggu Berikutnya"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setFormOpen(false);
                    setFormInitialized(false);
                  }}
                  className="min-h-[42px] rounded-xl border border-[#DCE6DE] bg-white px-3.5 py-2 text-xs font-semibold text-[#4A6170]"
                >
                  Batal
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Selected Run Cross-Week Warnings & Simple Comparison */}
      {selectedRun?.stock_confirmation_required && selectedRun.stock_confirmation_reason && (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-xl border border-[#F3D19B] bg-[#FFFBEB] p-3.5 text-xs text-[#92400E]"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <strong className="block">Perlu Konfirmasi Stok Sebelum Aktivasi</strong>
            <p className="mt-0.5 leading-relaxed">{selectedRun.stock_confirmation_reason}</p>
          </div>
        </div>
      )}

      {historyCtx && historyCtx.history_days_count > 0 && comparison && (
        <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-3.5 space-y-2 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-bold text-[#16354A]">
              Perbandingan Ringkas vs Periode Sebelumnya ({historyCtx.previous_plan_title ?? "Minggu Lalu"})
            </span>
            <StatusBadge
              tone={historyCtx.primary_source_type === "VERIFIED_EXECUTION" ? "success" : "neutral"}
              label={
                historyCtx.primary_source_type === "VERIFIED_EXECUTION"
                  ? "Histori Pelaksanaan Terverifikasi"
                  : historyCtx.primary_source_type === "MIXED"
                  ? "Histori Gabungan (QC + Rencana)"
                  : "Histori Rencana Operasional"
              }
            />
          </div>
          <p className="text-[#4A6170]">{historyCtx.source_notice}</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 pt-1 tabular-nums">
            <div className="rounded-lg border border-[#DCE6DE] bg-white px-3 py-2">
              <span className="block text-[11px] text-[#647A87]">Pengulangan Hari 5 → Hari 1</span>
              <strong className="text-sm text-[#16354A]">
                {comparison.boundary_day5_to_day1_repeat_count} resep
              </strong>
            </div>
            <div className="rounded-lg border border-[#DCE6DE] bg-white px-3 py-2">
              <span className="block text-[11px] text-[#647A87]">Resep Baru vs Minggu Lalu</span>
              <strong className="text-sm text-[#16354A]">
                {comparison.fresh_recipes_count} dari {comparison.new_unique_recipes_count} resep unik
              </strong>
            </div>
            <div className="rounded-lg border border-[#DCE6DE] bg-white px-3 py-2">
              <span className="block text-[11px] text-[#647A87]">Selisih Biaya/Porsi</span>
              <strong className="text-sm text-[#16354A]">
                {comparison.cost_delta_per_serving_idr !== null
                  ? `${formatSignedIDR(comparison.cost_delta_per_serving_idr)} (lalu: ${formatIDR(comparison.previous_cost_per_serving_idr)})`
                  : formatIDR(comparison.new_cost_per_serving_idr)}
              </strong>
            </div>
          </div>
        </div>
      )}

      {feedback && (
        <div
          role={feedback.type === "err" ? "alert" : "status"}
          className={`rounded-xl border px-3.5 py-2.5 text-xs font-medium ${
            feedback.type === "ok"
              ? "border-[#B5DFDA] bg-[#EBF6F5] text-[#0F766E]"
              : "border-[#F5C2C2] bg-[#FEF0F0] text-[#991B1B]"
          }`}
        >
          {feedback.text}
        </div>
      )}
    </section>
  );
}
