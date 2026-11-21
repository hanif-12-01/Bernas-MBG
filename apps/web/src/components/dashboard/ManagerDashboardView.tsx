"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  FileText,
  Package,
  ShieldAlert,
  XCircle,
} from "lucide-react";

import { CustodianDelegationCard } from "@/components/custodian/CustodianDelegationCard";
import { ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { ManagerIncidentReviewList } from "@/components/incidents/ManagerIncidentReviewList";
import { PageHeader } from "@/components/layout/AppShell";
import { RecoveryReviewSummaryCard } from "@/components/recovery/RecoveryReviewSummaryCard";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { KPIStatCard } from "@/components/ui/KPIStatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatAuditAction,
  formatDateTimeID,
  formatDayLabel,
  formatIDR,
  formatMenuReviewStatus,
  formatOperationalStatus,
  formatPeriodPhase,
  formatQCStatus,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";
import { formatJakartaDate } from "@/lib/formatters/jakartaDate";
import type { MenuReviewDecisionEnum } from "@/types/api";

export function ManagerDashboardView() {
  const qc = useQueryClient();
  const [notesByReview, setNotesByReview] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["manager-summary"],
    queryFn: apiClient.getManagerSummary,
  });

  const reviewMutation = useMutation({
    mutationFn: ({
      reviewId,
      decision,
      notes,
    }: {
      reviewId: string;
      decision: MenuReviewDecisionEnum;
      notes?: string;
    }) => apiClient.reviewMenuPlan(reviewId, decision, notes),
    onSuccess: (updated) => {
      setActionError(null);
      setActionSuccess(
        updated.status === "APPROVED"
          ? `Rencana "${updated.title}" disetujui secara operasional.`
          : `Permintaan revisi untuk "${updated.title}" telah dikirim ke Perencana Menu.`
      );
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["menu-reviews"] });
    },
    onError: (err) => {
      setActionSuccess(null);
      setActionError(err instanceof ApiError ? err.message : "Gagal memproses keputusan tinjauan.");
    },
  });

  const activateMutation = useMutation({
    mutationFn: (reviewId: string) =>
      apiClient.activateOperationalPlan({
        menu_review_id: reviewId,
        notes: "Diaktifkan menjadi rencana operasional efektif dari Ringkasan Kepala Dapur.",
      }),
    onSuccess: (assigned) => {
      setActionError(null);
      setActionSuccess(
        `Rencana "${assigned.plan_title}" kini AKTIF menggantikan rencana sebelumnya untuk ${assigned.scope_label}.`
      );
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["menu-reviews"] });
      qc.invalidateQueries({ queryKey: ["qc-summary"] });
      qc.invalidateQueries({ queryKey: ["operational-plans"] });
      qc.invalidateQueries({ queryKey: ["operational-plan-effective"] });
    },
    onError: (err) => {
      setActionSuccess(null);
      setActionError(err instanceof ApiError ? err.message : "Gagal mengaktifkan rencana pengganti.");
    },
  });

  const reviewPurchaseMutation = useMutation({
    mutationFn: ({
      docId,
      decision,
    }: {
      docId: string;
      decision: "VERIFIED_MATCH" | "DISCREPANCY_FLAGGED";
    }) => apiClient.reviewPurchaseDocument(docId, { decision }),
    onSuccess: (doc) => {
      setActionError(null);
      setActionSuccess(`Bukti pembelian "${doc.supplier_name}" ditandai ${doc.evidence_status}.`);
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["purchase-documents"] });
    },
    onError: (err) => {
      setActionError(err instanceof ApiError ? err.message : "Gagal meninjau bukti pembelian.");
    },
  });

  const reviewQCMutation = useMutation({
    mutationFn: (inspectionId: string) =>
      apiClient.reviewQCInspection(
        inspectionId,
        "ACCEPTED_FOR_RECORD",
        "Ditinjau dan diterima Kepala Dapur dari Ringkasan Tugas."
      ),
    onSuccess: () => {
      setActionError(null);
      setActionSuccess("Laporan Pemeriksaan Sajian ditandai Selesai Ditinjau.");
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["qc-inspections"] });
    },
    onError: (err) => {
      setActionError(err instanceof ApiError ? err.message : "Gagal meninjau pemeriksaan sajian.");
    },
  });

  if (summaryQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Beranda Kepala Dapur" subtitle="Memuat antrean tinjauan, penugasan stok, dan persetujuan operasional..." />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (summaryQuery.error || !summaryQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Beranda Kepala Dapur" />
        <ErrorState
          message={summaryQuery.error?.message ?? "Gagal memuat ringkasan Kepala Dapur."}
          onRetry={() => summaryQuery.refetch()}
        />
      </div>
    );
  }

  const data = summaryQuery.data;
  const pendingDocs = data.pending_purchase_documents ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ringkasan Kepala Dapur"
        subtitle={`Kelola penugasan Pengelola Stok, tinjau rencana menu, otorisasi pemusnahan bahan, bukti pembelian, dan hasil Pemeriksaan Sajian untuk ${data.kitchen_name}.`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/shopping-list?tab=purchases"
              className="inline-flex min-h-[42px] items-center gap-2 rounded-xl border border-[#DCE6DE] bg-white px-4 py-2 text-sm font-semibold text-[#16354A] hover:bg-[#F5F8F5]"
            >
              <FileText className="h-4 w-4" aria-hidden="true" />
              <span>Bukti Belanja</span>
            </Link>
            <Link
              href="/menu-planning"
              className="inline-flex min-h-[42px] items-center gap-2 rounded-xl border border-[#DCE6DE] bg-white px-4 py-2 text-sm font-semibold text-[#16354A] hover:bg-[#F5F8F5]"
            >
              <ClipboardCheck className="h-4 w-4" aria-hidden="true" />
              <span>Lihat Rencana Menu</span>
            </Link>
          </div>
        }
      />

      <DatasetSimulationNotice simulationOnly={data.simulation_only} />

      {/* Top KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPIStatCard
          label="Biaya Rata-rata Rencana"
          value={formatIDR(data.latest_cost_per_serving_idr)}
          helper={
            data.latest_total_cost_idr
              ? `Total: ${formatIDR(data.latest_total_cost_idr)}`
              : "Belum ada rencana layak"
          }
          icon={<ClipboardCheck className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Rencana Menunggu Tinjauan"
          value={`${data.pending_menu_reviews.length}`}
          helper={`${data.approved_menu_reviews_count} rencana telah disetujui`}
          accent={data.pending_menu_reviews.length > 0 ? "warning" : "default"}
          icon={<Clock className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Bukti Belanja & Pemusnahan"
          value={`${(data.pending_purchase_evidence_count ?? 0) + (data.pending_disposal_authorizations_count ?? 0)}`}
          helper={`${data.pending_purchase_evidence_count ?? 0} bukti belanja · ${data.pending_disposal_authorizations_count ?? 0} insiden`}
          accent={
            (data.pending_purchase_evidence_count ?? 0) +
              (data.pending_disposal_authorizations_count ?? 0) >
            0
              ? "warning"
              : "default"
          }
          icon={<ShieldAlert className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Pemeriksaan Sajian Baru"
          value={`${data.pending_qc_inspections.length}`}
          helper="Foto sajian menunggu tinjauan"
          accent={data.pending_qc_inspections.length > 0 ? "warning" : "default"}
          icon={<Camera className="h-5 w-5" aria-hidden="true" />}
        />
      </div>

      {actionSuccess && (
        <div className="flex items-center gap-2 rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] p-3.5 text-sm font-medium text-[#0F766E]">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{actionSuccess}</span>
        </div>
      )}
      {actionError && <ErrorState title="Tinjauan Gagal" message={actionError} />}

      {/* 1. Single Authoritative Stock Custodian Delegation */}
      <CustodianDelegationCard />

      {/* 2. Effective Operational Plans */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EEF3EE] pb-3">
          <div>
            <h2 className="text-base font-bold text-[#16354A]">Status Rencana Operasional Dapur</h2>
            <p className="text-xs text-[#647A87]">
              Rencana aktif atau tertahan saat ini.
            </p>
          </div>
          {(data.active_incidents_count ?? 0) > 0 && (
            <StatusBadge tone="critical" label={`${data.active_incidents_count} insiden bahan aktif`} />
          )}
        </div>

        {(data.effective_operational_plans?.length ?? 0) === 0 ? (
          <p className="text-xs text-[#647A87]">
            Belum ada rencana yang ditetapkan sebagai rencana operasional aktif.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {data.effective_operational_plans!.map((op) => {
              const st = formatOperationalStatus(op.operational_status);
              return (
                <div
                  key={op.id}
                  className={`rounded-xl border p-4 space-y-2 ${
                    op.operational_status === "ON_HOLD"
                      ? "border-[#F5C2C2] bg-[#FEF0F0]/70"
                      : "border-[#B5DFDA] bg-[#F4FAF9]"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-bold text-[#16354A] break-words">{op.plan_title}</span>
                    <div className="flex flex-wrap gap-1.5">
                      {op.derived_period_phase && formatPeriodPhase(op.derived_period_phase) && (
                        <StatusBadge
                          tone={formatPeriodPhase(op.derived_period_phase)!.tone}
                          label={formatPeriodPhase(op.derived_period_phase)!.label}
                        />
                      )}
                      <StatusBadge tone={st.tone} label={st.label} />
                    </div>
                  </div>
                  <p className="text-xs text-[#4A6170]">{op.scope_label}</p>
                  <p className="text-xs text-[#16354A] tabular-nums">
                    <strong>{op.horizon_days} hari</strong> × <strong>{op.servings_per_day} porsi/hari</strong>{" "}
                    = <strong>{op.total_servings.toLocaleString("id-ID")} total porsi</strong> •{" "}
                    <strong>{formatIDR(op.total_cost_idr)}</strong> ({formatIDR(op.cost_per_serving_idr)}/porsi)
                  </p>
                  {op.operational_status === "ON_HOLD" && op.hold_reason && (
                    <p className="rounded-lg border border-[#F5C2C2] bg-white px-2.5 py-1.5 text-xs font-semibold text-[#991B1B]">
                      Ditahan: {op.hold_reason}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {(data.approved_awaiting_activation?.length ?? 0) > 0 && (
          <div className="space-y-2.5 rounded-xl border border-[#F3D19B] bg-[#FFFBEB] p-4">
            <h3 className="text-xs font-bold uppercase tracking-wide text-[#92400E]">
              Rencana Disetujui — Menunggu Aktivasi ({data.approved_awaiting_activation!.length})
            </h3>
            {data.approved_awaiting_activation!.map((mr) => (
              <div
                key={mr.id}
                className="flex flex-col justify-between gap-3 rounded-xl border border-[#F3D19B] bg-white p-3.5 sm:flex-row sm:items-center"
              >
                <div className="min-w-0 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-[#16354A]">{mr.title}</span>
                    <StatusBadge tone="warning" label="Disetujui (Belum Aktif)" />
                    {mr.derived_period_phase && formatPeriodPhase(mr.derived_period_phase) && (
                      <StatusBadge
                        tone={formatPeriodPhase(mr.derived_period_phase)!.tone}
                        label={formatPeriodPhase(mr.derived_period_phase)!.label}
                      />
                    )}
                  </div>
                  <p className="text-xs text-[#4A6170]">
                    {mr.period_start_date
                      ? `${formatJakartaDate(mr.period_start_date)}${mr.period_end_date && mr.period_end_date !== mr.period_start_date ? ` s.d. ${formatJakartaDate(mr.period_end_date)}` : ""} · `
                      : ""}
                    Total {formatIDR(mr.objective_total_idr)} ({formatIDR(mr.cost_per_serving_average_idr)}/porsi)
                  </p>
                  {mr.stock_confirmation_required && (
                    <p className="text-[11px] font-semibold text-[#92400E]">
                      Perlu Konfirmasi Stok — backend akan memeriksa stok &amp; kedaluwarsa terbaru saat aktivasi.
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  disabled={activateMutation.isPending}
                  onClick={() => activateMutation.mutate(mr.id)}
                  className="inline-flex min-h-[40px] shrink-0 items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-bold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                >
                  <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                  <span>{mr.recovery_event_id ? "Aktifkan Rencana Pengganti" : "Aktifkan Rencana"}</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 3. Manager Incident Review & Disposal Authorization (NO incident report form!) */}
      <ManagerIncidentReviewList />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {/* 4. Pending Menu Reviews */}
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex items-center justify-between gap-2 border-b border-[#EEF3EE] pb-3">
            <div>
              <h2 className="text-base font-bold text-[#16354A]">Rencana Menu Menunggu Persetujuan</h2>
              <p className="text-xs text-[#647A87]">
                Persetujuan operasional internal — bukan validasi klinis/BGN.
              </p>
            </div>
            <Link href="/menu-planning" className="text-xs font-semibold text-[#0F766E] hover:underline">
              Buka Rencana →
            </Link>
          </div>

          {data.pending_menu_reviews.length === 0 ? (
            <p className="py-6 text-center text-sm text-[#647A87]">
              Tidak ada rencana menu yang menunggu persetujuan.
            </p>
          ) : (
            <div className="mt-4 space-y-4">
              {data.pending_menu_reviews.map((rev) => {
                const st = formatMenuReviewStatus(rev.status);
                return (
                  <div key={rev.id} className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-4 space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <span className="text-sm font-bold text-[#16354A]">{rev.title}</span>
                        <p className="text-xs text-[#4A6170]">
                          Oleh {rev.created_by_name} • {formatIDR(rev.cost_per_serving_average_idr)}/porsi
                        </p>
                      </div>
                      <StatusBadge tone={st.tone} label={st.label} />
                    </div>
                    {rev.recovery_event_id && (
                      <RecoveryReviewSummaryCard
                        recoveryEventId={rev.recovery_event_id}
                        isStaleInventoryHint={Boolean(rev.is_stale_inventory)}
                      />
                    )}
                    <input
                      type="text"
                      value={notesByReview[rev.id] ?? ""}
                      onChange={(e) => setNotesByReview((p) => ({ ...p, [rev.id]: e.target.value }))}
                      placeholder="Catatan tinjauan (opsional untuk setujui, wajib untuk revisi)..."
                      className="min-h-[38px] w-full rounded-xl border border-[#DCE6DE] bg-white px-3 py-1.5 text-xs"
                    />
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={reviewMutation.isPending || Boolean(rev.is_stale_inventory)}
                        onClick={() =>
                          reviewMutation.mutate({
                            reviewId: rev.id,
                            decision: "APPROVED",
                            notes: notesByReview[rev.id],
                          })
                        }
                        className="inline-flex min-h-[38px] items-center rounded-xl bg-[#0F766E] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-50"
                      >
                        Setujui Rencana
                      </button>
                      <button
                        type="button"
                        disabled={reviewMutation.isPending || !(notesByReview[rev.id] ?? "").trim()}
                        onClick={() =>
                          reviewMutation.mutate({
                            reviewId: rev.id,
                            decision: "REVISION_REQUIRED",
                            notes: notesByReview[rev.id],
                          })
                        }
                        className="inline-flex min-h-[38px] items-center rounded-xl border border-[#F5D59B] bg-[#FEF6E7] px-3.5 py-1.5 text-xs font-semibold text-[#8A5300] disabled:opacity-50"
                      >
                        Minta Revisi
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* 5. Pending Pemeriksaan Sajian (with Inline Photo Preview) */}
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex items-center justify-between gap-2 border-b border-[#EEF3EE] pb-3">
            <div>
              <h2 className="text-base font-bold text-[#16354A]">Foto Pemeriksaan Sajian Masuk</h2>
              <p className="text-xs text-[#647A87]">Lihat foto nampan sajian & tandai selesai ditinjau.</p>
            </div>
            <Link href="/kitchen-qc" className="text-xs font-semibold text-[#0F766E] hover:underline">
              Buka Pemeriksaan →
            </Link>
          </div>

          {data.pending_qc_inspections.length === 0 ? (
            <p className="py-6 text-center text-sm text-[#647A87]">
              Belum ada foto Pemeriksaan Sajian baru yang menunggu tinjauan.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              {data.pending_qc_inspections.map((insp) => {
                const st = formatQCStatus(insp.status);
                const latestImg = insp.images.at(-1);
                return (
                  <div
                    key={insp.id}
                    className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-3.5 space-y-2.5"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <span className="text-sm font-bold text-[#16354A]">
                          {insp.scenario_name} — {formatDayLabel(insp.day_index)}
                        </span>
                        <p className="text-xs text-[#4A6170]">
                          Petugas: {insp.submitted_by_name ?? insp.created_by_name} ·{" "}
                          {formatDateTimeID(insp.submitted_at)}
                        </p>
                      </div>
                      <StatusBadge tone={st.tone} label={st.label} />
                    </div>
                    {latestImg && (
                      <img
                        src={apiClient.getProtectedImageUrl(latestImg.image_url)}
                        alt={`Sampel sajian ${insp.scenario_name}`}
                        className="h-36 w-full rounded-lg border border-slate-200 object-cover"
                      />
                    )}
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={reviewQCMutation.isPending}
                        onClick={() => reviewQCMutation.mutate(insp.id)}
                        className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg bg-[#0F766E] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#0B5F58]"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Tandai Selesai Ditinjau
                      </button>
                      <Link
                        href={`/kitchen-qc?inspection=${insp.id}`}
                        className="inline-flex min-h-[36px] items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                      >
                        Lihat Detail Lengkap
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* 6. Purchase Evidence Verification Queue & Recent Audit */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex items-center justify-between border-b border-[#EEF3EE] pb-3">
            <h2 className="text-base font-bold text-[#16354A]">
              Bukti Pembelian Menunggu Verifikasi ({pendingDocs.length})
            </h2>
            <Link href="/shopping-list?tab=purchases" className="text-xs font-semibold text-[#0F766E] hover:underline">
              Kelola Bukti →
            </Link>
          </div>
          {pendingDocs.length === 0 ? (
            <p className="py-6 text-sm text-[#647A87]">Semua catatan pembelian sudah diverifikasi.</p>
          ) : (
            <div className="mt-3 space-y-2.5 text-xs">
              {pendingDocs.map((doc) => (
                <div key={doc.id} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-bold text-slate-900">{doc.supplier_name}</span>
                    <StatusBadge label={doc.evidence_status} tone={doc.has_evidence_file ? "warning" : "neutral"} />
                  </div>
                  <p className="mt-0.5 text-slate-600">
                    {formatJakartaDate(doc.purchase_date)}
                    {doc.total_amount_idr != null ? ` · ${formatIDR(doc.total_amount_idr)}` : ""}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {doc.has_evidence_file && doc.evidence_url && (
                      <a
                        href={apiClient.getProtectedImageUrl(doc.evidence_url)}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded border border-slate-300 px-2.5 py-1 font-semibold text-[#0F766E]"
                      >
                        Buka Bukti
                      </a>
                    )}
                    <button
                      type="button"
                      disabled={!doc.has_evidence_file || reviewPurchaseMutation.isPending}
                      onClick={() =>
                        reviewPurchaseMutation.mutate({ docId: doc.id, decision: "VERIFIED_MATCH" })
                      }
                      className="rounded bg-emerald-700 px-2.5 py-1 font-semibold text-white disabled:opacity-40"
                    >
                      Tandai Cocok
                    </button>
                    <button
                      type="button"
                      disabled={reviewPurchaseMutation.isPending}
                      onClick={() =>
                        reviewPurchaseMutation.mutate({
                          docId: doc.id,
                          decision: "DISCREPANCY_FLAGGED",
                        })
                      }
                      className="inline-flex items-center gap-1 rounded border border-rose-300 bg-rose-50 px-2.5 py-1 font-semibold text-rose-800"
                    >
                      <XCircle className="h-3 w-3" /> Selisih
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex items-center justify-between border-b border-[#EEF3EE] pb-3">
            <h2 className="text-base font-bold text-[#16354A]">Peringatan Stok & Jejak Audit</h2>
            <Link href="/inventory" className="text-xs font-semibold text-[#0F766E] hover:underline">
              Stok Bahan →
            </Link>
          </div>
          {data.low_stock_alerts.length > 0 && (
            <ul className="mt-3 divide-y divide-[#EEF3EE] text-xs">
              {data.low_stock_alerts.slice(0, 4).map((al) => (
                <li key={al.ingredient_code} className="flex items-center justify-between py-2">
                  <span className="font-semibold text-[#16354A]">{al.ingredient_name}</span>
                  <span className="inline-flex items-center gap-1 font-semibold text-[#B45309]">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    {formatWeightFromGrams(al.stock_raw_g)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {data.recent_audit_events.length > 0 && (
            <ul className="mt-3 max-h-[180px] divide-y divide-[#EEF3EE] overflow-auto border-t border-slate-100 pt-2 text-xs">
              {data.recent_audit_events.slice(0, 6).map((ev) => (
                <li key={ev.id} className="flex items-center justify-between gap-2 py-2">
                  <span className="font-medium text-slate-800">{formatAuditAction(ev.action)}</span>
                  <span className="text-[11px] text-slate-500">{formatDateTimeID(ev.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
