"use client";

import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Camera,
  CalendarDays,
  Package,
  ShieldAlert,
  ShoppingBasket,
  Trash2,
  UserCheck,
} from "lucide-react";

import { ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { KPIStatCard } from "@/components/ui/KPIStatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiClient } from "@/lib/api/client";
import {
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
        <PageHeader title="Ringkasan Tugas QC" subtitle="Memuat tugas harian dapur..." />
        <LoadingSkeleton rows={3} />
      </div>
    );
  }

  if (qcQuery.error || !qcQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Ringkasan Tugas QC" />
        <ErrorState
          message={qcQuery.error?.message ?? "Gagal memuat ringkasan Petugas QC."}
          onRetry={() => qcQuery.refetch()}
        />
      </div>
    );
  }

  const data = qcQuery.data;
  const isCustodian = Boolean(data.is_active_stock_custodian);
  const pendingDisposal = data.pending_disposal_incidents ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Ringkasan Tugas Petugas QC"
        subtitle={`Tugas pemeriksaan sajian harian dan pengelolaan stok untuk ${data.kitchen_name}.`}
        badges={<DatasetSimulationNotice compact simulationOnly={data.simulation_only} />}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/kitchen-qc"
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
            >
              <Camera className="h-4 w-4" aria-hidden="true" />
              <span>Pemeriksaan Sajian</span>
            </Link>
            {isCustodian && (
              <Link
                href="/inventory?action=report-incident"
                className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-rose-300 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-800 hover:bg-rose-100"
              >
                <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                <span>Laporkan Bahan Bermasalah</span>
              </Link>
            )}
          </div>
        }
      />

      {/* Active Stock Custodian Authority Cue */}
      <div
        className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-xs ${
          isCustodian
            ? "border-emerald-200 bg-emerald-50 text-emerald-950"
            : "border-slate-200 bg-white text-slate-700"
        }`}
        data-testid="qc-custodian-status-banner"
      >
        <div className="flex items-center gap-2">
          <UserCheck className={`h-4 w-4 shrink-0 ${isCustodian ? "text-emerald-700" : "text-slate-500"}`} />
          {isCustodian ? (
            <span>
              Anda adalah <strong>Petugas QC Pengelola Stok Aktif</strong> (berwenang menerima barang, memperbarui stok, dan menahan bahan bermasalah).
            </span>
          ) : data.stock_custodian?.is_assigned ? (
            <span>
              <strong>Bukan Pengelola Stok Aktif:</strong> Pengelola Stok dipegang oleh{" "}
              <strong>{data.stock_custodian.custodian_full_name}</strong>. Anda tetap bertugas pada Pemeriksaan Sajian harian.
            </span>
          ) : (
            <span>
              <strong>Belum Ada Pengelola Stok Aktif:</strong> Hubungi Kepala Dapur jika membutuhkan akses pencatatan stok.
            </span>
          )}
        </div>
        {isCustodian && (
          <div className="flex flex-wrap gap-3">
            <Link href="/inventory" className="font-semibold text-emerald-800 underline">
              Buka Stok Bahan
            </Link>
            <Link href="/shopping-list?tab=receipts" className="font-semibold text-emerald-800 underline">
              Catat Penerimaan Barang
            </Link>
          </div>
        )}
      </div>

      {/* Physical Disposal Tasks Authorized by Manager */}
      {isCustodian && pendingDisposal.length > 0 && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-xs text-amber-950">
          <div className="flex items-center gap-2 font-bold">
            <Trash2 className="h-4 w-4 text-amber-700" />
            {pendingDisposal.length} Pemusnahan Lot Sudah Disetujui Kepala Dapur
          </div>
          <p className="mt-1">
            Silakan catat pelaksanaan pemusnahan fisik agar status buku besar stok selesai diperbarui.
          </p>
          <Link
            href="/inventory?action=report-incident"
            className="mt-2 inline-block font-semibold text-amber-900 underline"
          >
            Catat Pemusnahan Fisik di Stok Bahan →
          </Link>
        </div>
      )}

      {(data.held_operational_plans?.length ?? 0) > 0 && (
        <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs text-rose-900">
          <p className="text-sm font-bold">
            Rencana Menu Sedang DITAHAN — Pemeriksaan Sajian Rencana Lama Diblokir
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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KPIStatCard
          label="Rencana Siap Operasi"
          value={String(data.effective_operational_plans?.length ?? 0)}
          helper="Acuan Pemeriksaan Sajian hari ini"
          icon={<CalendarDays className="h-5 w-5" aria-hidden="true" />}
          accent="teal"
        />
        <KPIStatCard
          label="Pemeriksaan Sajian Tertunda"
          value={String(data.action_required_inspections.length)}
          helper="Foto & daftar periksa perlu dikirim"
          icon={<Camera className="h-5 w-5" aria-hidden="true" />}
          accent={data.action_required_inspections.length > 0 ? "warning" : "default"}
        />
        <KPIStatCard
          label={isCustodian ? "Stok Bermasalah / Pemusnahan" : "Total Laporan Terkirim"}
          value={
            isCustodian
              ? String((data.active_incidents_count ?? 0) + pendingDisposal.length)
              : String(data.submitted_or_reviewed_inspections.length)
          }
          helper={isCustodian ? "Tahan keamanan / tunggu musnahkan" : "Pemeriksaan sajian tersimpan"}
          icon={
            isCustodian ? (
              <Package className="h-5 w-5" aria-hidden="true" />
            ) : (
              <ShoppingBasket className="h-5 w-5" aria-hidden="true" />
            )
          }
        />
      </div>

      {/* Pemeriksaan Sajian Queue */}
      {data.action_required_inspections.length > 0 && (
        <section className="rounded-2xl border border-[#F3D19B] bg-[#FFFBEB]/60 p-5">
          <h2 className="text-base font-bold text-[#16354A]">
            Lanjutkan Pemeriksaan Sajian ({data.action_required_inspections.length})
          </h2>
          <div className="mt-3 space-y-2.5">
            {data.action_required_inspections.map((insp) => {
              const st = formatQCStatus(insp.status);
              return (
                <div
                  key={insp.id}
                  className="flex flex-col justify-between gap-3 rounded-xl border border-[#DCE6DE] bg-white p-4 sm:flex-row sm:items-center"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-bold text-[#16354A]">
                        {insp.scenario_name} — {formatDayLabel(insp.day_index)}
                      </span>
                      <StatusBadge tone={st.tone} label={st.label} />
                    </div>
                    <p className="mt-0.5 text-xs text-[#647A87]">
                      {insp.images.length} foto · Target {insp.expected_menu.length} komponen
                    </p>
                  </div>
                  <Link
                    href={`/kitchen-qc?inspection=${insp.id}`}
                    className="inline-flex min-h-[40px] items-center justify-center rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
                  >
                    Lanjutkan Pemeriksaan →
                  </Link>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Operational Plans */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
        <h2 className="border-b border-[#EEF3EE] pb-3 text-base font-bold text-[#16354A]">
          Rencana Menu Aktif untuk Pemeriksaan Sajian
        </h2>
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
                    {plan.total_servings ? ` (${plan.total_servings.toLocaleString("id-ID")} porsi)` : ""}
                  </p>
                </div>
                {plan.status === "APPROVED" && !isHeld ? (
                  <Link
                    href={`/kitchen-qc?run=${plan.run_id}&review=${plan.id}`}
                    className="inline-flex min-h-[40px] items-center justify-center rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] px-3.5 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#DDF0EE]"
                  >
                    Periksa Sajian Rencana Ini
                  </Link>
                ) : (
                  <span className="text-xs font-semibold text-rose-700">Diblokir sementara</span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {data.submitted_or_reviewed_inspections.length > 0 && (
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
          <h2 className="border-b border-[#EEF3EE] pb-3 text-base font-bold text-[#16354A]">
            Riwayat Pemeriksaan Sajian
          </h2>
          <div className="mt-3 space-y-2">
            {data.submitted_or_reviewed_inspections.slice(0, 5).map((insp) => {
              const st = formatQCStatus(insp.status);
              const out = formatQCOutcome(insp.review_outcome);
              return (
                <div
                  key={insp.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 p-3 text-xs"
                >
                  <div>
                    <span className="font-semibold text-slate-900">
                      {insp.scenario_name} — {formatDayLabel(insp.day_index)}
                    </span>
                    <div className="mt-1 flex gap-1.5">
                      <StatusBadge tone={st.tone} label={st.label} />
                      {insp.review_outcome && <StatusBadge tone={out.tone} label={out.label} />}
                    </div>
                  </div>
                  <Link href={`/kitchen-qc?inspection=${insp.id}`} className="font-semibold text-[#0F766E] underline">
                    Lihat Detail
                  </Link>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
