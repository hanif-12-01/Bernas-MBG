"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardCheck, Loader2, Send } from "lucide-react";

import { ErrorState } from "@/components/feedback/FeedbackStates";
import { RecoveryReviewSummaryCard } from "@/components/recovery/RecoveryReviewSummaryCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatDateTimeID,
  formatMenuReviewStatus,
  formatOperationalStatus,
} from "@/lib/formatters/indonesian";
import type { MenuReviewDecisionEnum } from "@/types/api";

interface MenuReviewActionBarProps {
  runId: string;
  scenarioName: string;
  validationPassed: boolean;
}

export function MenuReviewActionBar({
  runId,
  scenarioName,
  validationPassed,
}: MenuReviewActionBarProps) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const reviewsQuery = useQuery({
    queryKey: ["menu-reviews", user?.active_kitchen_id],
    queryFn: () => apiClient.listMenuReviews(),
    enabled: Boolean(user),
  });

  const latestReview = useMemo(() => {
    const matching = (reviewsQuery.data ?? []).filter((r) => r.run_id === runId);
    if (matching.length === 0) return null;
    return matching.sort((a, b) => b.version_number - a.version_number)[0];
  }, [reviewsQuery.data, runId]);

  const submitNewMutation = useMutation({
    mutationFn: async () => {
      const records = await apiClient.listMenuReviews();
      const latest = records.filter((record) => record.run_id === runId)
        .sort((a, b) => b.version_number - a.version_number)[0];
      if (latest && latest.status !== "DRAFT" && latest.status !== "REVISION_REQUIRED") {
        return latest;
      }
      const draft = latest?.status === "DRAFT" ? latest : await apiClient.createMenuReview({
        run_id: runId,
        title: scenarioName,
        planner_notes: notes.trim() || undefined,
      });
      return apiClient.submitMenuReview(draft.id, notes.trim() || undefined);
    },
    onSuccess: (submitted) => {
      setNotes("");
      setFeedback({
        type: "ok",
        text: `Rencana "${submitted.title}" (v${submitted.version_number}) telah diajukan ke Kepala Dapur.`,
      });
      qc.invalidateQueries({ queryKey: ["menu-reviews"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
    },
    onError: (err) => {
      qc.invalidateQueries({ queryKey: ["menu-reviews"] });
      setFeedback({
        type: "err",
        text: err instanceof ApiError ? err.message : "Gagal mengajukan peninjauan rencana menu.",
      });
    },
  });

  const managerDecisionMutation = useMutation({
    mutationFn: ({
      reviewId,
      decision,
    }: {
      reviewId: string;
      decision: MenuReviewDecisionEnum;
    }) => apiClient.reviewMenuPlan(reviewId, decision, notes.trim() || undefined),
    onSuccess: (updated) => {
      setNotes("");
      setFeedback({
        type: "ok",
        text:
          updated.status === "APPROVED"
            ? "Rencana menu disetujui secara operasional."
            : "Permintaan revisi telah dikirim kembali ke Perencana Menu.",
      });
      qc.invalidateQueries({ queryKey: ["menu-reviews"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
    },
    onError: (err) => {
      setFeedback({
        type: "err",
        text: err instanceof ApiError ? err.message : "Gagal memproses keputusan tinjauan.",
      });
    },
  });

  const activatePlanMutation = useMutation({
    mutationFn: (reviewId: string) =>
      apiClient.activateOperationalPlan({
        menu_review_id: reviewId,
        notes: "Diaktifkan menjadi rencana operasional efektif dari halaman Rencana Menu.",
      }),
    onSuccess: (assigned) => {
      setFeedback({
        type: "ok",
        text: `Rencana "${assigned.plan_title}" telah AKTIF untuk cakupan ${assigned.scope_label}.`,
      });
      qc.invalidateQueries({ queryKey: ["menu-reviews"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["qc-summary"] });
      qc.invalidateQueries({ queryKey: ["operational-plans"] });
      qc.invalidateQueries({ queryKey: ["operational-plan-effective"] });
    },
    onError: (err) => {
      setFeedback({
        type: "err",
        text: err instanceof ApiError ? err.message : "Gagal mengaktifkan rencana pengganti.",
      });
    },
  });

  if (!user || !validationPassed || !["MENU_PLANNER", "KITCHEN_MANAGER"].includes(user.active_role)) return null;
  if (reviewsQuery.error) return <ErrorState title="Status peninjauan gagal dimuat" message={reviewsQuery.error.message}
    onRetry={() => void reviewsQuery.refetch()} />;
  if (reviewsQuery.isLoading) return <p role="status" className="text-sm text-[#647A87]">Memuat status peninjauan…</p>;

  const statusInfo = latestReview ? formatMenuReviewStatus(latestReview.status) : null;
  const opStatusInfo = latestReview?.operational_status
    ? formatOperationalStatus(latestReview.operational_status)
    : null;
  const canPlannerSubmit =
    user.active_role === "MENU_PLANNER" &&
    (!latestReview || latestReview.status === "REVISION_REQUIRED" || latestReview.status === "DRAFT");
  const canManagerReview =
    user.active_role === "KITCHEN_MANAGER" && latestReview?.status === "SUBMITTED";
  const canManagerActivate =
    user.active_role === "KITCHEN_MANAGER" &&
    latestReview?.status === "APPROVED" &&
    latestReview.operational_status === "APPROVED_NOT_ACTIVE";

  return (
    <section className="rounded-2xl border border-[#DCE6DE] bg-white p-4 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
      <div className="space-y-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <ClipboardCheck className="h-4 w-4 text-[#0F766E]" aria-hidden="true" />
            <h2 className="text-sm font-bold text-[#16354A]">
              Status Peninjauan Operasional Rencana Menu
            </h2>
            {statusInfo ? (
              <StatusBadge tone={statusInfo.tone} label={statusInfo.label} />
            ) : (
              <StatusBadge tone="neutral" label="Belum Diajukan" />
            )}
            {opStatusInfo && <StatusBadge tone={opStatusInfo.tone} label={opStatusInfo.label} />}
          </div>
          {latestReview?.hold_reason && latestReview.operational_status === "ON_HOLD" && (
            <p className="rounded-lg border border-[#F5C2C2] bg-[#FEF0F0] px-3 py-2 text-xs font-semibold text-[#991B1B]">
              DITAHAN (ON HOLD): {latestReview.hold_reason}
            </p>
          )}
          {canManagerActivate && latestReview && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#F3D19B] bg-[#FFFBEB] p-3">
              <p className="text-xs font-medium text-[#92400E]">
                Rencana pengganti ini sudah disetujui Kepala Dapur tetapi belum menggantikan rencana aktif saat ini.
              </p>
              <button
                type="button"
                disabled={activatePlanMutation.isPending || Boolean(latestReview.is_stale_inventory)}
                onClick={() => activatePlanMutation.mutate(latestReview.id)}
                className="inline-flex min-h-[42px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-bold text-white hover:bg-[#0B5F58] disabled:opacity-60"
              >
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                <span>Aktifkan Rencana Pengganti</span>
              </button>
            </div>
          )}
          <p className="text-xs text-[#647A87]">
            Persetujuan Kepala Dapur bersifat operasional internal — tidak menggantikan validasi
            ahli gizi atau standar resmi BGN.
          </p>
          {latestReview?.reviewer_notes && (
            <p className="break-words text-sm font-medium text-[#16354A]">
              Catatan Kepala Dapur ({formatDateTimeID(latestReview.reviewed_at)}): &ldquo;
              {latestReview.reviewer_notes}&rdquo;
            </p>
          )}
          {latestReview?.status === "REVISION_REQUIRED" && canPlannerSubmit && (
            <p className="text-xs leading-relaxed text-[#647A87]">
              Untuk perubahan catatan, jelaskan revisi lalu ajukan ulang. Untuk perubahan susunan menu, hitung rencana yang diperbarui dan ajukan hasilnya.
            </p>
          )}
          {latestReview?.recovery_event_id && (
            <RecoveryReviewSummaryCard
              recoveryEventId={latestReview.recovery_event_id}
              isStaleInventoryHint={latestReview.is_stale_inventory}
              onRecomputeHref={
                user?.active_role === "MENU_PLANNER"
                  ? `/simulator?eventId=${latestReview.recovery_event_id}`
                  : undefined
              }
            />
          )}
        </div>

        {(canPlannerSubmit || canManagerReview) && (
          <div className="flex flex-col gap-2">
            <label htmlFor={`review-note-${runId}`} className="text-sm font-semibold">Catatan peninjauan</label>
            <input
              id={`review-note-${runId}`}
              type="text"
              value={notes}
              maxLength={2000}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={
                canPlannerSubmit
                  ? "Catatan pengajuan (opsional)..."
                  : "Catatan tinjauan (wajib untuk revisi)..."
              }
              className="min-h-[44px] w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-base text-[#16354A] sm:text-sm"
            />
            {canPlannerSubmit && (
              <button
                type="button"
                disabled={submitNewMutation.isPending || (latestReview?.status === "REVISION_REQUIRED" && !notes.trim())}
                onClick={() => submitNewMutation.mutate()}
                className="inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60 sm:self-start"
              >
                {submitNewMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                <span>{latestReview?.status === "REVISION_REQUIRED" ? "Ajukan Ulang" : "Ajukan Peninjauan"}</span>
              </button>
            )}
            {canManagerReview && latestReview && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={managerDecisionMutation.isPending || Boolean(latestReview.is_stale_inventory)}
                  onClick={() =>
                    managerDecisionMutation.mutate({
                      reviewId: latestReview.id,
                      decision: "APPROVED",
                    })
                  }
                  className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-3.5 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                >
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Setujui Operasional</span>
                </button>
                <button
                  type="button"
                  disabled={managerDecisionMutation.isPending || !notes.trim()}
                  onClick={() =>
                    managerDecisionMutation.mutate({
                      reviewId: latestReview.id,
                      decision: "REVISION_REQUIRED",
                    })
                  }
                  className="inline-flex min-h-[44px] items-center rounded-xl border border-[#F5C2C2] bg-white px-3.5 py-2 text-sm font-semibold text-[#991B1B] hover:bg-[#FEF0F0] disabled:opacity-60"
                >
                  <span>Minta Revisi</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {feedback && (
        <div
          role={feedback.type === "err" ? "alert" : "status"}
          className={`mt-3 rounded-xl border px-3 py-2 text-xs font-medium ${
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
