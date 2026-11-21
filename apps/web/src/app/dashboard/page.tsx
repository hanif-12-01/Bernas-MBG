"use client";

import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Package,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";

import { ManagerDashboardView } from "@/components/dashboard/ManagerDashboardView";
import { QCOfficerDashboardView } from "@/components/dashboard/QCOfficerDashboardView";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { KPIStatCard } from "@/components/ui/KPIStatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { apiClient } from "@/lib/api/client";
import {
  formatMenuReviewStatus,
  formatOperationalStatus,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";

export default function DashboardPage() {
  const { user } = useAuth();
  if (user?.active_role === "KITCHEN_MANAGER") {
    return <ManagerDashboardView />;
  }
  if (user?.active_role === "QC_OFFICER") {
    return <QCOfficerDashboardView />;
  }
  if (user?.active_role === "NUTRITIONIST") {
    return (
      <div className="space-y-5">
        <PageHeader title="Ringkasan Dapur" subtitle={user.active_kitchen_name} />
        <EmptyState
          title="Tinjau rencana menu"
          description="Akun Ahli Gizi memiliki akses baca pada rencana dan stok bahan dapur."
          action={
            <Link
              href="/menu-planning"
              className="inline-flex min-h-[44px] items-center rounded-xl bg-[#0F766E] px-4 text-sm font-semibold text-white"
            >
              Buka Rencana Menu
            </Link>
          }
        />
      </div>
    );
  }
  return <PlannerDashboardView />;
}

function PlannerDashboardView() {
  const { user } = useAuth();
  const plannerQuery = useQuery({
    queryKey: ["planner-summary", user?.active_kitchen_id],
    queryFn: apiClient.getPlannerSummary,
    enabled: Boolean(user),
  });

  if (plannerQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Ringkasan Tugas Perencana Menu"
          subtitle="Memuat tugas prioritas perencanaan, gangguan bahan, dan persetujuan menu..."
        />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (plannerQuery.error || !plannerQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Ringkasan Tugas Perencana Menu" />
        <ErrorState
          title="Ringkasan Perencana Belum Dapat Dimuat"
          message={plannerQuery.error?.message ?? "Gagal memuat ringkasan tugas."}
          onRetry={() => plannerQuery.refetch()}
        />
      </div>
    );
  }

  const data = plannerQuery.data;
  const urgentIncidents = data.open_incidents_requiring_recovery;
  const urgentPlans = data.held_operational_plans;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ringkasan Tugas Perencana Menu"
        subtitle={`Fokuskan langkah hari ini untuk menyusun menu gizi seimbang dan menangani perubahan stok di ${data.kitchen_name}.`}
        badges={<DatasetSimulationNotice compact simulationOnly={data.simulation_only} />}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/simulator"
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-[#DCE6DE] bg-white px-4 py-2 text-xs font-semibold text-[#16354A] hover:bg-[#F5F8F5]"
            >
              <SlidersHorizontal className="h-4 w-4" />
              <span>Pemulihan & Simulasi</span>
            </Link>
            <Link
              href="/menu-planning"
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
            >
              <CalendarDays className="h-4 w-4" />
              <span>Susun Rencana Menu</span>
            </Link>
          </div>
        }
      />

      {/* Immediate Priority Banner if Active Plan is ON HOLD or Incident Requires Recovery */}
      {(urgentIncidents.length > 0 || urgentPlans.length > 0) && (
        <section
          role="alert"
          className="rounded-2xl border border-rose-300 bg-rose-50 p-5 text-xs text-rose-950"
          data-testid="planner-urgent-recovery-card"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-bold text-rose-950">
              <ShieldAlert className="h-5 w-5 text-rose-700" />
              Tindakan Segera: Rencana Operasional Terdampak Insiden Bahan
            </div>
            <Link
              href="/simulator"
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-xl bg-rose-700 px-4 py-2 text-xs font-bold text-white hover:bg-rose-800"
            >
              Hitung Menu Pengganti <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {urgentIncidents.map((inc) => (
              <li key={inc.id}>
                <strong>{inc.title}</strong> ({inc.affected_ingredient_names.join(", ")},{" "}
                {inc.total_held_kg.toFixed(2)} kg ditahan) — segera susun opsi pemulihan minim gangguan.
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Priority KPI Summary */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPIStatCard
          label="Rencana Aktif Berjalan"
          value={String(data.effective_operational_plans.length)}
          helper={`${data.approved_reviews_count} rencana telah disetujui`}
          accent="teal"
          icon={<CheckCircle2 className="h-5 w-5" />}
        />
        <KPIStatCard
          label="Insiden Butuh Pemulihan"
          value={String(urgentIncidents.length)}
          helper={urgentIncidents.length > 0 ? "Rencana perlu penyesuaian menu" : "Tidak ada gangguan terbuka"}
          accent={urgentIncidents.length > 0 ? "warning" : "default"}
          icon={<ShieldAlert className="h-5 w-5" />}
        />
        <KPIStatCard
          label="Draft / Perlu Revisi"
          value={String(data.draft_or_revision_reviews.length)}
          helper={`${data.submitted_reviews_count} menunggu persetujuan Kepala Dapur`}
          accent={data.draft_or_revision_reviews.length > 0 ? "warning" : "default"}
          icon={<CalendarDays className="h-5 w-5" />}
        />
        <KPIStatCard
          label="Bahan Stok Menipis / Ditahan"
          value={String(data.low_stock_alerts.length)}
          helper="Lihat perkiraan kecukupan FEFO di Stok Bahan"
          accent={data.low_stock_alerts.length > 0 ? "warning" : "default"}
          icon={<Package className="h-5 w-5" />}
        />
      </div>

      {/* Role Action Tasks Grid */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 space-y-3">
          <div className="flex items-center justify-between border-b border-[#EEF3EE] pb-3">
            <h2 className="text-base font-bold text-[#16354A]">
              Rencana Menu Berjalan & Perlu Tindak Lanjut
            </h2>
            <Link href="/menu-planning" className="text-xs font-semibold text-[#0F766E] hover:underline">
              Buka Semua →
            </Link>
          </div>
          {data.effective_operational_plans.length === 0 &&
          data.draft_or_revision_reviews.length === 0 ? (
            <p className="py-4 text-xs text-slate-600">
              Belum ada rencana menu aktif atau draft revisi. Buat skenario baru di Rencana Menu.
            </p>
          ) : (
            <div className="space-y-2.5 text-xs">
              {data.effective_operational_plans.map((op) => {
                const st = formatOperationalStatus(op.operational_status);
                return (
                  <div key={op.id} className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900">{op.plan_title}</span>
                      <StatusBadge label={st.label} tone={st.tone} />
                    </div>
                    <p className="mt-1 text-slate-600">{op.scope_label}</p>
                  </div>
                );
              })}
              {data.draft_or_revision_reviews.map((rev) => {
                const st = formatMenuReviewStatus(rev.status);
                return (
                  <div key={rev.id} className="rounded-xl border border-amber-200 bg-amber-50/50 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900">{rev.title}</span>
                      <StatusBadge label={st.label} tone={st.tone} />
                    </div>
                    <Link
                      href={`/menu-planning?run=${rev.run_id}`}
                      className="mt-1 inline-block font-semibold text-[#0F766E] underline"
                    >
                      Lanjutkan & Ajukan Persetujuan →
                    </Link>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 space-y-3">
          <div className="flex items-center justify-between border-b border-[#EEF3EE] pb-3">
            <h2 className="text-base font-bold text-[#16354A]">Stok Menipis & Peringatan Rencana</h2>
            <Link href="/inventory" className="text-xs font-semibold text-[#0F766E] hover:underline">
              Cek Kecukupan Stok →
            </Link>
          </div>
          {data.approved_plan_inventory_alerts.map((al) => (
            <div
              key={al.menu_review_id}
              className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950"
            >
              <strong>{al.title}:</strong> {al.summary_message}
            </div>
          ))}
          {data.low_stock_alerts.length === 0 ? (
            <p className="py-4 text-xs text-slate-600">Tidak ada bahan dengan stok di bawah 10 kg.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-xs">
              {data.low_stock_alerts.map((al) => (
                <li key={al.ingredient_code} className="flex items-center justify-between py-2">
                  <span className="font-semibold text-slate-900">
                    {al.ingredient_name} <span className="text-slate-500">({al.ingredient_code})</span>
                  </span>
                  <span className="inline-flex items-center gap-1 font-semibold text-amber-700">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    {formatWeightFromGrams(al.stock_raw_g)}
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
