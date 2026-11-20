"use client";

import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Camera, CalendarDays, ClipboardList, History, ShieldAlert } from "lucide-react";

import { ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { IncidentPanel } from "@/components/incidents/IncidentPanel";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { KPIStatCard } from "@/components/ui/KPIStatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiClient } from "@/lib/api/client";
import {
  formatDateTimeID,
  formatDayLabel,
  formatMenuReviewStatus,
  formatOperationalStatus,
  formatQCOutcome,
  formatQCStatus,
} from "@/lib/formatters/indonesian";

export function QCOfficerDashboardView() {
  const qcQuery = useQuery({
    queryKey: ["qc-summary"],
    queryFn: apiClient.getQCSummary,
  });

  if (qcQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Beranda Petugas QC" subtitle="Memuat tugas pemeriksaan menu hari ini..." />
        <LoadingSkeleton rows={3} />
      </div>
    );
  }

  if (qcQuery.error || !qcQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Beranda Petugas QC" />
        <ErrorState
          message={qcQuery.error?.message ?? "Gagal memuat ringkasan Petugas QC."}
          onRetry={() => qcQuery.refetch()}
        />
      </div>
    );
  }

  const data = qcQuery.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Beranda Petugas QC"
        subtitle={`Ambil foto sampel nampan, periksa kesesuaian komponen visual terhadap rencana menu, dan kirim laporan untuk ${data.kitchen_name}.`}
        badges={<DatasetSimulationNotice compact simulationOnly={data.simulation_only} />}
        actions={
          <Link
            href="/kitchen-qc"
            className="inline-flex min-h-[46px] w-full items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-[#0B5F58] sm:w-auto"
          >
            <Camera className="h-4 w-4" aria-hidden="true" />
            <span>Ambil Foto & Pemeriksaan Baru</span>
          </Link>
        }
      />

      {/* Explicit Food Safety Boundary Banner */}
      <div className="flex items-start gap-2.5 rounded-2xl border border-[#DCE6DE] bg-white p-4 text-xs leading-relaxed text-[#4A6170]">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
        <p>
          <strong className="text-[#16354A]">Batasan Pemeriksaan Visual AI:</strong> Pemeriksaan
          foto hanya membantu mencocokkan komponen menu secara visual. Hasil AI wajib ditinjau
          Petugas QC dan <strong>tidak</strong> menyatakan keamanan mikrobiologis, berat gramasi,
          suhu, atau kelayakan konsumsi.
        </p>
      </div>

      {(data.held_operational_plans?.length ?? 0) > 0 && (
        <div
          role="alert"
          className="rounded-2xl border border-[#F5C2C2] bg-[#FEF0F0] p-4 text-xs text-[#991B1B]"
        >
          <p className="text-sm font-bold">
            Rencana Operasional Sedang DITAHAN (ON HOLD) — Pemeriksaan Rutin Diblokir
          </p>
          <ul className="mt-1 space-y-1">
            {data.held_operational_plans!.map((hp) => (
              <li key={hp.id}>
                <strong>{hp.plan_title}</strong>: {hp.hold_reason ?? "Menunggu rencana pengganti aktif dari Kepala Dapur."}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Mobile-Friendly KPI Summary */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KPIStatCard
          label="Perlu Tindakan QC"
          value={`${data.action_required_inspections.length}`}
          helper="Belum difoto, belum ditinjau, atau belum dikirim"
          accent={data.action_required_inspections.length > 0 ? "warning" : "default"}
          icon={<ClipboardList className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Rencana Menu Tersedia"
          value={`${data.available_menu_plans.length}`}
          helper="Rencana yang disetujui untuk dapur Anda"
          icon={<CalendarDays className="h-5 w-5" aria-hidden="true" />}
        />
        <KPIStatCard
          label="Riwayat Terkirim & Ditinjau"
          value={`${data.submitted_or_reviewed_inspections.length}`}
          helper={`Total ${data.total_inspections_count} pemeriksaan tercatat`}
          icon={<History className="h-5 w-5" aria-hidden="true" />}
        />
      </div>

      {/* Action Required Inspections */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
        <div className="flex items-center justify-between border-b border-[#EEF3EE] pb-3">
          <h2 className="text-base font-bold text-[#16354A]">Pemeriksaan Memerlukan Tindakan</h2>
          <Link href="/kitchen-qc" className="text-xs font-semibold text-[#0F766E] hover:underline">
            Buka Halaman QC →
          </Link>
        </div>

        {data.action_required_inspections.length === 0 ? (
          <div className="py-8 text-center">
            <p className="text-sm text-[#647A87]">
              Tidak ada pemeriksaan yang tertunda. Mulai pemeriksaan baru dengan mengambil foto sampel.
            </p>
            <Link
              href="/kitchen-qc"
              className="mt-4 inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58]"
            >
              <Camera className="h-4 w-4" aria-hidden="true" />
              <span>Mulai Pemeriksaan Menu AI</span>
            </Link>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {data.action_required_inspections.map((insp) => {
              const st = formatQCStatus(insp.status);
              return (
                <div
                  key={insp.id}
                  className="flex flex-col justify-between gap-3 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/70 p-4 sm:flex-row sm:items-center"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-bold text-[#16354A]">
                        {insp.scenario_name} — {formatDayLabel(insp.day_index)}
                      </span>
                      <StatusBadge tone={st.tone} label={st.label} />
                    </div>
                    <p className="mt-1 text-xs text-[#647A87]">
                      {insp.images.length} foto terunggah • Diperbarui {formatDateTimeID(insp.updated_at)}
                    </p>
                  </div>
                  <Link
                    href={`/kitchen-qc?inspection=${insp.id}`}
                    className="inline-flex min-h-[42px] shrink-0 items-center justify-center rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
                  >
                    Lanjutkan Pemeriksaan
                  </Link>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Relevant Approved / Submitted Menu Plans */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
        <div className="border-b border-[#EEF3EE] pb-3">
          <h2 className="text-base font-bold text-[#16354A]">Rencana Menu Acuan Dapur</h2>
          <p className="text-xs text-[#647A87]">
            Gunakan rencana yang telah disetujui Kepala Dapur sebagai acuan pemeriksaan sampel.
          </p>
        </div>

        {data.available_menu_plans.length === 0 ? (
          <p className="py-6 text-sm text-[#647A87]">
            Petugas QC dapat memulai pemeriksaan setelah Kepala Dapur menyetujui rencana.
          </p>
        ) : (
          <div className="mt-4 space-y-2.5">
            {data.available_menu_plans.map((plan) => {
              const st = formatMenuReviewStatus(plan.status);
              const op = plan.operational_status ? formatOperationalStatus(plan.operational_status) : null;
              const isHeld = plan.operational_status === "ON_HOLD";
              return (
                <div
                  key={plan.id}
                  className="flex flex-col justify-between gap-2 rounded-xl border border-[#EEF3EE] p-3.5 sm:flex-row sm:items-center"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-[#16354A]">{plan.title}</span>
                      <StatusBadge tone={st.tone} label={st.label} />
                      {op && <StatusBadge tone={op.tone} label={op.label} />}
                    </div>
                    <p className="mt-0.5 text-xs text-[#647A87]">
                      {plan.days_count} hari
                      {plan.total_servings ? ` (${plan.total_servings.toLocaleString("id-ID")} porsi)` : ""} • Versi{" "}
                      {plan.version_number}
                    </p>
                    {isHeld && plan.hold_reason && (
                      <p className="mt-1 text-xs font-semibold text-[#991B1B]">{plan.hold_reason}</p>
                    )}
                  </div>
                  {plan.status === "APPROVED" && !isHeld ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Link href={`/menu-planning?run=${plan.run_id}`}
                        className="inline-flex min-h-[44px] items-center text-xs font-semibold text-[#0F766E] underline">
                        Lihat Menu
                      </Link>
                      <Link href={`/kitchen-qc?run=${plan.run_id}&review=${plan.id}`}
                        className="inline-flex min-h-[44px] items-center justify-center rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] px-3.5 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#DDF0EE]">
                        Periksa Rencana Ini
                      </Link>
                    </div>
                  ) : isHeld ? (
                    <span className="text-xs font-bold text-[#991B1B]">Diblokir sementara (ON HOLD)</span>
                  ) : (
                    <span className="text-xs text-[#647A87]">Menunggu persetujuan Kepala Dapur</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Submitted & Reviewed History */}
      {data.submitted_or_reviewed_inspections.length > 0 && (
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <h2 className="border-b border-[#EEF3EE] pb-3 text-base font-bold text-[#16354A]">
            Riwayat Pemeriksaan Terkirim
          </h2>
          <div className="mt-4 space-y-2.5">
            {data.submitted_or_reviewed_inspections.map((insp) => {
              const st = formatQCStatus(insp.status);
              const out = formatQCOutcome(insp.review_outcome);
              return (
                <div
                  key={insp.id}
                  className="flex flex-col justify-between gap-2 rounded-xl border border-[#EEF3EE] p-3.5 sm:flex-row sm:items-center"
                >
                  <div>
                    <p className="text-sm font-semibold text-[#16354A]">
                      {insp.scenario_name} — {formatDayLabel(insp.day_index)}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <StatusBadge tone={st.tone} label={st.label} />
                      {insp.review_outcome && <StatusBadge tone={out.tone} label={out.label} />}
                    </div>
                    {insp.manager_notes && (
                      <p className="mt-1 text-xs text-[#4A6170]">
                        Catatan Kepala Dapur: &ldquo;{insp.manager_notes}&rdquo;
                      </p>
                    )}
                  </div>
                  <Link
                    href={`/kitchen-qc?inspection=${insp.id}`}
                    className="text-xs font-semibold text-[#0F766E] hover:underline"
                  >
                    Lihat Detail →
                  </Link>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <IncidentPanel compact />
    </div>
  );
}
