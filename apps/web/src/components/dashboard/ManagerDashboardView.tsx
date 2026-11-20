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
} from "lucide-react";

import { ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { IncidentPanel } from "@/components/incidents/IncidentPanel";
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
  formatQCStatus,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";
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

  if (summaryQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Ringkasan Kepala Dapur" subtitle="Memuat ringkasan operasional dapur..." />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (summaryQuery.error || !summaryQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Ringkasan Kepala Dapur" />
        <ErrorState
          message={summaryQuery.error?.message ?? "Gagal memuat ringkasan Kepala Dapur."}
          onRetry={() => summaryQuery.refetch()}
        />
      </div>
    );
  }

  const data = summaryQuery.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ringkasan Kepala Dapur"
        subtitle={`Pantau rencana menu menunggu persetujuan operasional, pemeriksaan visual QC, peringatan stok, dan riwayat audit untuk ${data.kitchen_name}.`}
        badges={<DatasetSimulationNotice compact simulationOnly={data.simulation_only} />}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/kitchen-qc"
              className="inline-flex min-h-[42px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58]"
            >
              <Camera className="h-4 w-4" aria-hidden="true" />
              <span>Tinjau Pemeriksaan</span>
            </Link>
            <Link
              href="/menu-planning"
              className="inline-flex min-h-[42px] items-center gap-2 rounded-xl border border-[#DCE6DE] bg-white px-4 py-2 text-sm font-semibold text-[#16354A] hover:bg-[#F5F8F5]"
            >
              <FileText className="h-4 w-4" aria-hidden="true" />
              <span>Lihat Rencana Menu</span>
            </Link>
          </div>
        }
      />

      <DatasetSimulationNotice simulationOnly={data.simulation_only} />

      {/* Top KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPIStatCard
          label="Biaya Rata-rata Rencana Terbaru"
          value={formatIDR(data.latest_cost_per_serving_idr)}
          helper={
            data.latest_total_cost_idr
              ? `Total rencana: ${formatIDR(data.latest_total_cost_idr)}`
              : "Belum ada rencana layak"
          }
          icon={<ClipboardCheck className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Rencana Menunggu Tinjauan"
          value={`${data.pending_menu_reviews.length}`}
          helper={`${data.approved_menu_reviews_count} rencana telah disetujui operasional`}
          accent={data.pending_menu_reviews.length > 0 ? "warning" : "default"}
          icon={<Clock className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Pemeriksaan QC Menunggu Tinjauan"
          value={`${data.pending_qc_inspections.length}`}
          helper="Laporan foto & koreksi dari Petugas QC"
          accent={data.pending_qc_inspections.length > 0 ? "warning" : "default"}
          icon={<Camera className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Temuan Visual Perlu Perhatian"
          value={`${data.qc_discrepancies_count}`}
          helper="Inspeksi dengan komponen belum terlihat/tidak pasti"
          accent={data.qc_discrepancies_count > 0 ? "warning" : "default"}
          icon={<ShieldAlert className="h-5 w-5" aria-hidden="true" />}
        />
      </div>

      {actionSuccess && (
        <div className="flex items-center gap-2 rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] p-3.5 text-sm font-medium text-[#0F766E]">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{actionSuccess}</span>
        </div>
      )}
      {actionError && <ErrorState title="Tinjauan Gagal" message={actionError} />}

      {(data.approved_plan_inventory_alerts?.length ?? 0) > 0 && (
        <div
          role="alert"
          className="rounded-2xl border border-[#F3D19B] bg-[#FFFBEB] p-4 text-xs text-[#92400E]"
        >
          <p className="text-sm font-bold">
            Rencana Disetujui Perlu Peninjauan Ulang ({data.approved_plan_inventory_alerts!.length})
          </p>
          <ul className="mt-1.5 space-y-1">
            {data.approved_plan_inventory_alerts!.map((al) => (
              <li key={al.menu_review_id}>
                {al.summary_message}{" "}
                <Link href={`/menu-planning?run=${al.run_id}`} className="font-bold underline">
                  Buka Rencana
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Effective Operational Plans + Pending Activation (Sprint 3B.1 / 3C) */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EEF3EE] pb-3">
          <div>
            <h2 className="text-base font-bold text-[#16354A]">
              Status Rencana Operasional Dapur
            </h2>
            <p className="text-xs text-[#647A87]">
              Membedakan rencana yang benar-benar AKTIF/DITAHAN untuk eksekusi dari arsip persetujuan historis.
            </p>
          </div>
          {(data.active_incidents_count ?? 0) > 0 && (
            <StatusBadge
              tone="critical"
              label={`${data.active_incidents_count} insiden bahan aktif`}
            />
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
                    <span className="text-sm font-bold text-[#16354A] break-words">
                      {op.plan_title}
                    </span>
                    <StatusBadge tone={st.tone} label={st.label} />
                  </div>
                  <p className="text-xs text-[#4A6170]">{op.scope_label}</p>
                  <p className="text-xs text-[#16354A] tabular-nums">
                    <strong>{op.horizon_days} hari</strong> × <strong>{op.servings_per_day} porsi/hari</strong>{" "}
                    = <strong>{op.total_servings.toLocaleString("id-ID")} total porsi</strong> •{" "}
                    {op.total_menu_slots} slot hidangan • Total{" "}
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
              Rencana Pengganti Disetujui — Menunggu Aktivasi Operasional ({data.approved_awaiting_activation!.length})
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
                  </div>
                  <p className="text-xs text-[#4A6170]">
                    {mr.production_scope_label ?? `${mr.days_count} hari`} •{" "}
                    {mr.total_servings ? `${mr.total_servings.toLocaleString("id-ID")} total porsi • ` : ""}
                    Total {formatIDR(mr.objective_total_idr)} ({formatIDR(mr.cost_per_serving_average_idr)}/porsi)
                  </p>
                </div>
                <button
                  type="button"
                  disabled={activateMutation.isPending}
                  onClick={() => activateMutation.mutate(mr.id)}
                  className="inline-flex min-h-[44px] shrink-0 items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-bold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                >
                  <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                  <span>Aktifkan Rencana Pengganti</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <IncidentPanel compact />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {/* Pending Menu Reviews */}
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex items-center justify-between gap-2 border-b border-[#EEF3EE] pb-3">
            <div>
              <h2 className="text-base font-bold text-[#16354A]">
                Rencana Menu Menunggu Peninjauan
              </h2>
              <p className="text-xs text-[#647A87]">
                Persetujuan operasional internal saja — bukan validasi gizi ahli gizi/BGN.
              </p>
            </div>
            <StatusBadge
              tone={data.pending_menu_reviews.length > 0 ? "warning" : "neutral"}
              label={`${data.pending_menu_reviews.length} pengajuan`}
            />
          </div>

          {data.pending_menu_reviews.length === 0 ? (
            <p className="py-8 text-center text-sm text-[#647A87]">
              Tidak ada rencana menu yang menunggu tinjauan saat ini.
            </p>
          ) : (
            <div className="mt-4 space-y-4">
              {data.pending_menu_reviews.map((mr) => {
                const st = formatMenuReviewStatus(mr.status);
                const noteVal = notesByReview[mr.id] ?? "";
                return (
                  <div
                    key={mr.id}
                    className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-4 space-y-3"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <h3 className="break-words text-sm font-bold text-[#16354A]">
                          {mr.title} <span className="text-xs font-normal text-[#647A87]">(v{mr.version_number})</span>
                        </h3>
                        <p className="mt-0.5 text-xs text-[#4A6170]">
                          Diajukan oleh {mr.submitted_by_name ?? mr.created_by_name} •{" "}
                          {formatIDR(mr.cost_per_serving_average_idr)}/porsi • {mr.days_count} hari
                        </p>
                        {mr.planner_notes && (
                          <p className="mt-1 break-words text-xs italic text-[#4A6170]">
                            Catatan Perencana: &ldquo;{mr.planner_notes}&rdquo;
                          </p>
                        )}
                        <Link href={`/menu-planning?run=${mr.run_id}`}
                          className="inline-flex min-h-[44px] items-center text-sm font-semibold text-[#0F766E] underline">
                          Buka Rencana yang Diajukan
                        </Link>
                      </div>
                      <StatusBadge tone={st.tone} label={st.label} />
                    </div>

                    {mr.recovery_event_id && (
                      <RecoveryReviewSummaryCard
                        recoveryEventId={mr.recovery_event_id}
                        isStaleInventoryHint={mr.is_stale_inventory}
                      />
                    )}

                    <div>
                      <label htmlFor={`mr-note-${mr.id}`} className="block text-xs font-semibold text-[#4A6170]">
                        Catatan Kepala Dapur (wajib diisi jika meminta revisi)
                      </label>
                      <input
                        id={`mr-note-${mr.id}`}
                        type="text"
                        value={noteVal}
                         maxLength={2000}
                        onChange={(e) =>
                          setNotesByReview((prev) => ({ ...prev, [mr.id]: e.target.value }))
                        }
                        placeholder="Contoh: Disetujui operasional untuk minggu berjalan"
                         className="mt-1 min-h-[44px] w-full rounded-lg border border-[#DCE6DE] bg-white px-3 text-base text-[#16354A] sm:text-sm"
                      />
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={reviewMutation.isPending || Boolean(mr.is_stale_inventory)}
                        onClick={() =>
                          reviewMutation.mutate({
                            reviewId: mr.id,
                            decision: "APPROVED",
                             notes: noteVal.trim() || undefined,
                          })
                        }
                         className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>Setujui Operasional</span>
                      </button>
                      <button
                        type="button"
                         disabled={reviewMutation.isPending || !noteVal.trim()}
                        onClick={() =>
                          reviewMutation.mutate({
                            reviewId: mr.id,
                            decision: "REVISION_REQUIRED",
                            notes: noteVal,
                          })
                        }
                         className="inline-flex min-h-[44px] items-center gap-1.5 rounded-xl border border-[#F5C2C2] bg-white px-3.5 py-1.5 text-xs font-semibold text-[#991B1B] hover:bg-[#FEF0F0] disabled:opacity-60"
                      >
                        <span>Minta Revisi</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Pending QC Inspections */}
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex items-center justify-between gap-2 border-b border-[#EEF3EE] pb-3">
            <div>
              <h2 className="text-base font-bold text-[#16354A]">
                Pemeriksaan QC Menunggu Peninjauan
              </h2>
              <p className="text-xs text-[#647A87]">
                Tinjau foto sampel, observasi AI asli, dan koreksi Petugas QC.
              </p>
            </div>
            <Link
              href="/kitchen-qc"
              className="text-xs font-semibold text-[#0F766E] hover:underline"
            >
              Buka Semua QC →
            </Link>
          </div>

          {data.pending_qc_inspections.length === 0 ? (
            <p className="py-8 text-center text-sm text-[#647A87]">
              Belum ada laporan QC baru yang menunggu tinjauan.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              {data.pending_qc_inspections.map((insp) => {
                const st = formatQCStatus(insp.status);
                return (
                  <div
                    key={insp.id}
                    className="flex flex-col justify-between gap-3 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-4 sm:flex-row sm:items-center"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-bold text-[#16354A]">
                          {insp.scenario_name} — {formatDayLabel(insp.day_index)}
                        </span>
                        <StatusBadge tone={st.tone} label={st.label} />
                      </div>
                      <p className="mt-1 text-xs text-[#4A6170]">
                        Petugas QC: {insp.submitted_by_name ?? insp.created_by_name} •{" "}
                        {insp.images.length} foto • Dikirim {formatDateTimeID(insp.submitted_at)}
                      </p>
                    </div>
                    <Link
                      href={`/kitchen-qc?inspection=${insp.id}`}
                      className="inline-flex min-h-[38px] shrink-0 items-center justify-center rounded-xl bg-[#0F766E] px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-[#0B5F58]"
                    >
                      Tinjau Pemeriksaan
                    </Link>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* Bottom Row: Inventory Alerts & Audit Trail */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex items-center justify-between border-b border-[#EEF3EE] pb-3">
            <div className="flex items-center gap-2">
              <Package className="h-4 w-4 text-[#0F766E]" aria-hidden="true" />
              <h2 className="text-base font-bold text-[#16354A]">Peringatan Stok Bahan (&lt; 10 kg)</h2>
            </div>
            <Link href="/inventory" className="text-xs font-semibold text-[#0F766E] hover:underline">
              Lihat Inventaris →
            </Link>
          </div>
          {data.inventory_dataset_name && (
            <p className="mt-3 break-words text-sm text-[#647A87]">
              Acuan rencana layak terbaru: {data.inventory_dataset_name}{data.inventory_dataset_is_synthetic ? " (Simulasi)" : ""}
            </p>
          )}
          {data.low_stock_alerts.length === 0 ? (
            <p className="py-6 text-sm text-[#647A87]">
              {data.inventory_dataset_name ? "Tidak ada bahan di bawah ambang pada dataset ini." : "Hitung rencana yang layak untuk melihat peringatan stok."}
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-[#EEF3EE] text-xs">
              {data.low_stock_alerts.map((al) => (
                <li key={al.ingredient_code} className="flex items-center justify-between py-2.5">
                  <span className="font-semibold text-[#16354A]">
                    {al.ingredient_name}{" "}
                    <span className="font-normal text-[#647A87]">({al.ingredient_code})</span>
                  </span>
                  <span className="inline-flex items-center gap-1 font-semibold text-[#B45309] tabular-nums">
                    <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                    {formatWeightFromGrams(al.stock_raw_g)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="border-b border-[#EEF3EE] pb-3">
            <h2 className="text-base font-bold text-[#16354A]">Aktivitas & Jejak Audit Terbaru</h2>
            <p className="text-xs text-[#647A87]">
              Catatan kronologis transisi rencana menu, simulasi, dan pemeriksaan QC.
            </p>
          </div>
          {data.recent_audit_events.length === 0 ? (
            <p className="py-6 text-sm text-[#647A87]">Belum ada catatan audit tercatat.</p>
          ) : (
            <ul className="mt-3 max-h-[260px] divide-y divide-[#EEF3EE] overflow-auto text-xs">
              {data.recent_audit_events.map((ev) => (
                <li key={ev.id} className="flex items-start justify-between gap-3 py-2.5">
                  <div>
                    <p className="font-semibold text-[#16354A]">{formatAuditAction(ev.action)}</p>
                    <p className="text-[11px] text-[#647A87]">
                      {ev.actor_full_name ?? ev.actor_username ?? "Sistem"} • {ev.entity_type}
                    </p>
                  </div>
                  <span className="shrink-0 text-[11px] text-[#647A87] tabular-nums">
                    {formatDateTimeID(ev.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
