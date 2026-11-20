"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Coins,
  Plus,
  Scale,
  ShieldCheck,
  ShoppingBasket,
  Wallet,
} from "lucide-react";

import { DailyCostChart } from "@/components/charts/DailyCostChart";
import { BudgetProgress } from "@/components/dashboard/BudgetProgress";
import { ManagerDashboardView } from "@/components/dashboard/ManagerDashboardView";
import { QCOfficerDashboardView } from "@/components/dashboard/QCOfficerDashboardView";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { MenuDayCard } from "@/components/menu/MenuDayCard";
import { MenuReviewActionBar } from "@/components/menu/MenuReviewActionBar";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { KPIStatCard } from "@/components/ui/KPIStatCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import {
  formatDateTimeID,
  formatIDR,
  formatMealTypeLabel,
  formatPercent,
  formatRunStatus,
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
        <EmptyState title="Tinjau rencana menu" description="Akun Ahli Gizi memiliki akses baca pada rencana dapur."
          action={<Link href="/menu-planning" className="inline-flex min-h-[44px] items-center rounded-xl bg-[#0F766E] px-4 text-sm font-semibold text-white">Buka Rencana Menu</Link>} />
      </div>
    );
  }
  return <PlannerDashboardView />;
}

function PlannerDashboardView() {
  const {
    datasets,
    selectedRun,
    selectedScenario,
    isLoadingList,
    isLoadingRun,
    listError,
    runError,
    refreshAll,
  } = useWorkspace();

  const [showTechDetails, setShowTechDetails] = useState(false);

  if (isLoadingList || isLoadingRun) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Ringkasan Dapur"
          subtitle="Memuat kondisi rencana menu, anggaran, dan kebutuhan bahan dari server..."
        />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (listError || runError) {
    return (
      <div className="space-y-6">
        <PageHeader title="Ringkasan Dapur" />
        <ErrorState
          title="Koneksi ke Server GiziOptima Bermasalah"
          message={(listError || runError)?.message ?? "Gagal mengambil data."}
          onRetry={refreshAll}
        />
      </div>
    );
  }

  if (!selectedRun) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Ringkasan Dapur"
          subtitle="Mulai dengan memilih dataset untuk dapur ini dan menentukan anggaran, jumlah hari, serta porsi."
          badges={<DatasetSimulationNotice compact />}
        />
        <EmptyState
          title="Belum Ada Rencana Menu Tersimpan"
          description="Buat rencana pertama untuk melihat pilihan menu, kebutuhan bahan, dan perkiraan biaya."
          action={
            <Link
              href="/menu-planning?new=1"
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58]"
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Buat Rencana Menu
            </Link>
          }
        />
      </div>
    );
  }

  const runDataset = datasets.find((d) => d.id === selectedRun.dataset_version_id);
  const params = selectedRun.input_snapshot?.scenario_params;
  const budgetPerServing =
    selectedScenario?.budget_idr_per_serving ?? params?.budget_idr_per_serving ?? 0;
  const daysCount = selectedScenario?.days ?? params?.days ?? selectedRun.days.length;
  const servingsPerDay = selectedScenario?.servings_per_day ?? params?.servings_per_day ?? 0;
  const mealTypeLabel = formatMealTypeLabel(selectedScenario?.meal_type ?? params?.meal_type);
  const statusInfo = formatRunStatus(selectedRun.solver_status, selectedRun.validation_passed);

  // Identify ingredients with high stock utilization (>= 75%)
  const highUsageMaterials = selectedRun.material_usage
    .map((m) => ({
      ...m,
      utilPct: m.available_raw_g > 0 ? (m.used_raw_g / m.available_raw_g) * 100 : 0,
    }))
    .sort((a, b) => b.utilPct - a.utilPct);

  const tightStockMaterials = highUsageMaterials.filter((m) => m.utilPct >= 75);
  const topShoppingMaterials = [...selectedRun.material_usage]
    .sort((a, b) => b.used_raw_g - a.used_raw_g)
    .slice(0, 6);

  // Build contextual attention items (honest, non-alarmist)
  const attentionItems: Array<{
    tone: "critical" | "warning" | "neutral";
    title: string;
    detail: string;
    href?: string;
    cta?: string;
  }> = [];

  if (!selectedRun.validation_passed || selectedRun.solver_status === "INFEASIBLE") {
    attentionItems.push({
      tone: "critical",
      title: "Belum Ditemukan Kombinasi Menu yang Memenuhi Semua Batasan",
      detail:
        selectedRun.constraint_diagnostics[0]?.message ??
        "Periksa batas anggaran, stok bahan, atau pembatasan alergen pada skenario ini.",
      href: "/simulator",
      cta: "Uji Penyesuaian di Simulator",
    });
  }

  if (tightStockMaterials.length > 0) {
    const names = tightStockMaterials
      .slice(0, 3)
      .map((m) => `${m.ingredient_name} (${formatPercent(m.utilPct, 0)})`)
      .join(", ");
    attentionItems.push({
      tone: "warning",
      title: `${tightStockMaterials.length} Bahan Mendekati Batas Stok Tersedia`,
      detail: `Pemakaian tinggi terdeteksi pada: ${names}. Pertimbangkan simulasi pengurangan stok atau pengecekan pasokan.`,
      href: "/inventory",
      cta: "Periksa Bahan & Stok",
    });
  }

  if (selectedRun.simulation_only) {
    attentionItems.push({
      tone: "neutral",
      title: "Data Masih Bersifat Simulasi (DEMO_ONLY)",
      detail:
        "Target gizi, harga, dan stok belum divalidasi oleh ahli gizi atau kontrak pemasok resmi. Gunakan hasil ini untuk evaluasi alur keputusan.",
      href: "/settings",
      cta: "Kelola Dataset",
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ringkasan Dapur"
        subtitle={`${selectedScenario?.name ?? "Skenario Tersimpan"} • ${daysCount} hari (${mealTypeLabel}, ${servingsPerDay} porsi/hari) • Dataset: ${
          runDataset?.name ?? selectedRun.dataset_version_id.slice(0, 8)
        }`}
        badges={
          <>
            <StatusBadge tone={statusInfo.tone} label={statusInfo.shortLabel} size="md" />
            <DatasetSimulationNotice compact simulationOnly={selectedRun.simulation_only} />
          </>
        }
        actions={
          <Link
            href="/menu-planning?new=1"
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58]"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            <span>Buat Rencana Menu</span>
          </Link>
        }
      />

      <DatasetSimulationNotice
        simulationOnly={selectedRun.simulation_only}
        datasetName={runDataset?.name}
      />

      <MenuReviewActionBar
        key={selectedRun.run_id}
        runId={selectedRun.run_id}
        scenarioName={selectedScenario?.name ?? "Rencana Menu"}
        validationPassed={selectedRun.validation_passed}
      />

      {/* 4 Core KPI Cards */}
      <section aria-label="Indikator Utama Rencana Menu" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPIStatCard
          label="Rata-rata Biaya per Porsi"
          value={
            selectedRun.validation_passed
              ? formatIDR(selectedRun.cost_per_serving_average_idr)
              : "Tidak tersedia"
          }
          helper={
            selectedRun.validation_passed
              ? `Rata-rata dari ${daysCount} hari × ${servingsPerDay} porsi/hari`
              : "Tidak ada menu valid untuk dihitung biayanya."
          }
          icon={<Coins className="h-5 w-5" aria-hidden="true" />}
          accent="teal"
        />

        <KPIStatCard
          label={`Total Biaya Rencana (${daysCount} Hari)`}
          value={
            selectedRun.validation_passed
              ? formatIDR(selectedRun.objective_total_idr)
              : "Tidak tersedia"
          }
          helper={
            selectedRun.validation_passed
              ? `Untuk total ${(daysCount * servingsPerDay).toLocaleString("id-ID")} porsi`
              : "Perlu penyesuaian batasan agar rencana layak."
          }
          icon={<Wallet className="h-5 w-5" aria-hidden="true" />}
        />

        <KPIStatCard
          label="Batas Anggaran per Porsi"
          value={formatIDR(budgetPerServing)}
          helper="Batas maksimum harian yang ditetapkan pada skenario ini."
          icon={<Scale className="h-5 w-5" aria-hidden="true" />}
        />

        <KPIStatCard
          label="Status Kelayakan Rencana"
          value={statusInfo.shortLabel}
          badge={<StatusBadge tone={statusInfo.tone} label={statusInfo.label} />}
          helper={statusInfo.description}
          icon={<ShieldCheck className="h-5 w-5" aria-hidden="true" />}
          accent={
            statusInfo.tone === "critical"
              ? "critical"
              : statusInfo.tone === "warning"
              ? "warning"
              : "default"
          }
        />
      </section>

      {/* Budget Progress + Perlu Perhatian */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          <BudgetProgress
            averageCostPerServing={
              selectedRun.validation_passed ? selectedRun.cost_per_serving_average_idr : null
            }
            budgetPerServing={budgetPerServing}
          />
          <DailyCostChart days={selectedRun.days} budgetPerServing={budgetPerServing} />
        </div>

        <section
          aria-label="Perlu Perhatian"
          className="flex flex-col justify-between rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] lg:col-span-2"
        >
          <div>
            <h2 className="text-base font-semibold text-[#16354A]">Perlu Perhatian</h2>
            <p className="mt-0.5 text-xs text-[#647A87]">
              Catatan operasional penting berdasarkan hasil pemeriksaan batasan terakhir.
            </p>

            <div className="mt-4 space-y-3">
              {attentionItems.map((item, idx) => (
                <div
                  key={idx}
                  className={`rounded-xl border p-3.5 text-sm ${
                    item.tone === "critical"
                      ? "border-[#F5C2C2] bg-[#FEF0F0] text-[#991B1B]"
                      : item.tone === "warning"
                      ? "border-[#F5D59B] bg-[#FEF6E7] text-[#8A5300]"
                      : "border-[#DCE6DE] bg-[#F5F8F5] text-[#16354A]"
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    {item.tone === "critical" || item.tone === "warning" ? (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    ) : (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold">{item.title}</p>
                      <p className="mt-1 text-xs leading-relaxed opacity-90">{item.detail}</p>
                      {item.href && item.cta && (
                        <Link
                          href={item.href}
                          className="mt-2 inline-flex items-center gap-1 text-xs font-bold underline underline-offset-2"
                        >
                          <span>{item.cta}</span>
                          <ArrowRight className="h-3 w-3" aria-hidden="true" />
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-5 border-t border-[#EEF3EE] pt-4 text-xs text-[#647A87]">
            Terakhir dihitung: <strong className="text-[#16354A]">{formatDateTimeID(selectedRun.created_at)}</strong>
          </div>
        </section>
      </div>

      {/* 5-Day Menu Preview */}
      <section aria-label="Pratinjau Menu Mingguan" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-[#16354A]">
              Pratinjau Rencana Menu ({daysCount} Hari)
            </h2>
            <p className="text-xs text-[#647A87]">
              Resep terverifikasi yang terpilih untuk setiap slot menu harian.
            </p>
          </div>
          <Link
            href="/menu-planning"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#0F766E] hover:text-[#0B5F58]"
          >
            <span>Lihat Detail Menu & Gizi</span>
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>

        {selectedRun.days.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
            {selectedRun.days.map((day) => (
              <MenuDayCard key={day.day_index} day={day} budgetPerServing={budgetPerServing} />
            ))}
          </div>
        ) : (
          <EmptyState
            title="Tidak Ada Jadwal Menu untuk Ditampilkan"
            description="Karena rencana ini tidak memenuhi seluruh batasan, sistem tidak menampilkan kombinasi menu sebagai rekomendasi."
            action={
              <Link
                href="/simulator"
                className="inline-flex min-h-[40px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58]"
              >
                <span>Buka Simulator Harga & Stok</span>
              </Link>
            }
          />
        )}
      </section>

      {/* Ingredient Utilization + Shopping List Preview */}
      {selectedRun.material_usage.length > 0 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold text-[#16354A]">
                  Pemakaian Stok Bahan Utama
                </h2>
                <p className="mt-0.5 text-xs text-[#647A87]">
                  Bahan dengan tingkat pemakaian stok tertinggi pada rencana ini.
                </p>
              </div>
              <Link
                href="/inventory"
                className="text-xs font-semibold text-[#0F766E] hover:underline"
              >
                Semua Bahan →
              </Link>
            </div>
            <div className="mt-4 space-y-3">
              {highUsageMaterials.slice(0, 6).map((mat) => (
                <div key={mat.ingredient_code} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-[#16354A]">{mat.ingredient_name}</span>
                    <span className="text-[#4A6170] tabular-nums">
                      {formatWeightFromGrams(mat.used_raw_g)} /{" "}
                      {formatWeightFromGrams(mat.available_raw_g)} ({formatPercent(mat.utilPct, 0)})
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-[#EEF3EE]">
                    <div
                      className={`h-full rounded-full ${
                        mat.utilPct >= 90
                          ? "bg-[#C43D3D]"
                          : mat.utilPct >= 75
                          ? "bg-[#E9A23B]"
                          : "bg-[#0F766E]"
                      }`}
                      style={{ width: `${Math.min(mat.utilPct, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-semibold text-[#16354A]">
                  Pratinjau Kebutuhan Belanja
                </h2>
                <p className="mt-0.5 text-xs text-[#647A87]">
                  Total kebutuhan berat mentah bahan utama selama {daysCount} hari.
                </p>
              </div>
              <Link
                href="/shopping-list"
                className="inline-flex items-center gap-1.5 rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] px-3 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#DDF0EE]"
              >
                <ShoppingBasket className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Buka Daftar Belanja</span>
              </Link>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#DCE6DE] text-[#647A87]">
                    <th className="pb-2 font-semibold">Bahan Pangan</th>
                    <th className="pb-2 text-right font-semibold">Total Kebutuhan</th>
                    <th className="pb-2 text-right font-semibold">Stok Tersedia</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EEF3EE]">
                  {topShoppingMaterials.map((m) => (
                    <tr key={m.ingredient_code}>
                      <td className="py-2.5 font-semibold text-[#16354A]">{m.ingredient_name}</td>
                      <td className="py-2.5 text-right font-medium text-[#16354A] tabular-nums">
                        {formatWeightFromGrams(m.used_raw_g)}
                      </td>
                      <td className="py-2.5 text-right text-[#4A6170] tabular-nums">
                        {formatWeightFromGrams(m.available_raw_g)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {/* Optional Progressive Disclosure: Technical Audit Details */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white">
        <button
          type="button"
          onClick={() => setShowTechDetails((v) => !v)}
          aria-expanded={showTechDetails}
          className="flex w-full items-center justify-between px-5 py-3.5 text-left text-xs font-semibold text-[#4A6170] hover:text-[#16354A]"
        >
          <span>Detail Teknis & Jejak Audit Perhitungan (Opsional)</span>
          {showTechDetails ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {showTechDetails && (
          <div className="grid grid-cols-1 gap-3 border-t border-[#EEF3EE] px-5 py-4 text-xs text-[#4A6170] sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <span className="block text-[#647A87]">Run ID</span>
              <code className="font-mono text-[#16354A]">{selectedRun.run_id}</code>
            </div>
            <div>
              <span className="block text-[#647A87]">Model & Solver</span>
              <span className="font-semibold text-[#16354A]">
                {selectedRun.model_version} / {selectedRun.solver_name ?? "CBC"} ({selectedRun.solver_seconds}s)
              </span>
            </div>
            <div>
              <span className="block text-[#647A87]">Status Solver & Verifier</span>
              <span className="font-semibold text-[#16354A]">
                {selectedRun.solver_status} • Verifier:{" "}
                {selectedRun.constraint_audit.all_hard_constraints_pass ? "Lulus" : "Gagal"}
              </span>
            </div>
            <div>
              <span className="block text-[#647A87]">SHA-256 Input Snapshot</span>
              <code className="block truncate font-mono text-[#16354A]" title={selectedRun.input_sha256}>
                {selectedRun.input_sha256}
              </code>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
