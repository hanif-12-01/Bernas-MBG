"use client";

import React from "react";
import {
  AlertTriangle,
  ArrowRight,
  ArrowRightLeft,
  CheckCircle2,
  Info,
} from "lucide-react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  formatDayLabel,
  formatDecimal,
  formatIDR,
  formatNutrientLabel,
  formatPercent,
  formatRunStatus,
  formatSignedIDR,
  formatSlotLabel,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";
import type {
  OptimizationRunResponse,
  ScenarioComparisonResponse,
} from "@/types/api";

interface ScenarioComparisonProps {
  comparison: ScenarioComparisonResponse;
  baseName: string;
  candidateName: string;
  candidateRun?: OptimizationRunResponse;
  onAdoptCandidate?: () => void;
}

export function ScenarioComparison({
  comparison,
  baseName,
  candidateName,
  candidateRun,
  onAdoptCandidate,
}: ScenarioComparisonProps) {
  const baseStatus = formatRunStatus(
    comparison.base.solver_status,
    comparison.base.validation_passed
  );
  const candStatus = formatRunStatus(
    comparison.candidate.solver_status,
    comparison.candidate.validation_passed
  );
  const isCandidateInfeasible =
    !comparison.candidate.validation_passed ||
    comparison.candidate.solver_status === "INFEASIBLE";

  const swappedSlots = comparison.recipe_changes.filter((r) => r.changed);
  const changedMaterials = comparison.ingredient_usage_comparison.filter(
    (m) => Math.abs(m.delta_raw_g) > 0.01
  );

  return (
    <div className="space-y-6">
      {/* Executive Summary: Apa yang Berubah? */}
      <section className="rounded-2xl border border-[#B5DFDA] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-[#16354A]">Apa yang Berubah?</h2>
            <p className="mt-0.5 text-xs text-[#647A87]">
              Perbandingan langsung hasil backend antara rencana awal dan rencana setelah perubahan kondisi.
            </p>
          </div>
          {!isCandidateInfeasible && onAdoptCandidate && (
            <button
              type="button"
              onClick={onAdoptCandidate}
              className="inline-flex min-h-[40px] items-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
            >
              <span>Gunakan Hasil Ini di Beranda</span>
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          )}
        </div>

        {/* Infeasible Banner */}
        {isCandidateInfeasible ? (
          <div
            role="alert"
            className="mt-4 rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-4 text-sm text-[#991B1B]"
          >
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[#C43D3D]" aria-hidden="true" />
              <div className="space-y-2">
                <p className="font-bold">
                  Belum ditemukan kombinasi menu yang memenuhi seluruh batasan.
                </p>
                <p className="text-xs leading-relaxed text-[#7F1D1D]">
                  Sistem tidak menampilkan menu alternatif paksaan karena tidak ada kombinasi resep
                  terverifikasi yang lolos seluruh aturan anggaran, gizi, stok, dan pengulangan.
                </p>
                {candidateRun && candidateRun.constraint_diagnostics.length > 0 && (
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-[#7F1D1D]">
                    {candidateRun.constraint_diagnostics.map((d, idx) => (
                      <li key={idx}>{d.message}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            {/* Rencana Awal */}
            <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-[#647A87]">
                  Rencana Awal
                </span>
                <StatusBadge tone={baseStatus.tone} label={baseStatus.shortLabel} />
              </div>
              <p className="mt-1 truncate text-sm font-bold text-[#16354A]">{baseName}</p>
              <div className="mt-3 grid grid-cols-2 gap-3 tabular-nums">
                <div>
                  <span className="block text-[11px] text-[#647A87]">Biaya per Porsi</span>
                  <span className="text-lg font-bold text-[#16354A]">
                    {formatIDR(comparison.cost_comparison.base_cost_per_serving_idr)}
                  </span>
                </div>
                <div>
                  <span className="block text-[11px] text-[#647A87]">Total Biaya</span>
                  <span className="text-lg font-bold text-[#16354A]">
                    {formatIDR(comparison.cost_comparison.base_total_idr)}
                  </span>
                </div>
              </div>
            </div>

            {/* Rencana Setelah Perubahan */}
            <div className="rounded-xl border border-[#B5DFDA] bg-[#EBF6F5]/60 p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-[#0F766E]">
                  Rencana Setelah Perubahan
                </span>
                <StatusBadge tone={candStatus.tone} label={candStatus.shortLabel} />
              </div>
              <p className="mt-1 truncate text-sm font-bold text-[#16354A]">{candidateName}</p>
              <div className="mt-3 grid grid-cols-2 gap-3 tabular-nums">
                <div>
                  <span className="block text-[11px] text-[#4A6170]">Biaya per Porsi</span>
                  <span className="text-lg font-bold text-[#16354A]">
                    {formatIDR(comparison.cost_comparison.candidate_cost_per_serving_idr)}
                  </span>
                  {comparison.cost_comparison.delta_cost_per_serving_idr !== null && (
                    <span className="block text-xs font-semibold text-[#4A6170]">
                      Selisih: {formatSignedIDR(comparison.cost_comparison.delta_cost_per_serving_idr)}
                    </span>
                  )}
                </div>
                <div>
                  <span className="block text-[11px] text-[#4A6170]">Total Biaya</span>
                  <span className="text-lg font-bold text-[#16354A]">
                    {formatIDR(comparison.cost_comparison.candidate_total_idr)}
                  </span>
                  {comparison.cost_comparison.delta_total_idr !== null && (
                    <span className="block text-xs font-semibold text-[#4A6170]">
                      Selisih: {formatSignedIDR(comparison.cost_comparison.delta_total_idr)} (
                      {comparison.cost_comparison.delta_cost_pct !== null
                        ? `${comparison.cost_comparison.delta_cost_pct > 0 ? "+" : ""}${formatPercent(
                            comparison.cost_comparison.delta_cost_pct,
                            2
                          )}`
                        : "—"}
                      )
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Mathematical Honesty Notice */}
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] px-4 py-3 text-xs text-[#4A6170]">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
          <div className="space-y-1">
            {comparison.compatibility.apples_to_apples_comparable ? (
              <p>
                <strong className="text-[#16354A]">Perbandingan Setara (Same-Input):</strong> Kedua
                rencana memakai harga, stok, dan batasan yang identik.
                {comparison.cost_comparison.cost_savings_achieved_idr !== null && (
                  <>
                    {" "}
                    Selisih efisiensi optimasi:{" "}
                    <strong>{formatIDR(comparison.cost_comparison.cost_savings_achieved_idr)}</strong>.
                  </>
                )}
              </p>
            ) : (
              <p>
                <strong className="text-[#16354A]">
                  Perbedaan Biaya Berasal dari Perubahan Kondisi Input:
                </strong>{" "}
                Karena harga atau batas stok berubah antar skenario, selisih biaya di atas merupakan
                dampak skenario (<em>what-if delta</em>), <strong>bukan</strong> klaim penghematan murni.
              </p>
            )}

            {comparison.compatibility.changed_prices.length > 0 && (
              <p>
                Perubahan harga input:{" "}
                {comparison.compatibility.changed_prices
                  .map(
                    (p) =>
                      `${p.ingredient_code} (${formatIDR((p.base_price_idr_per_g ?? 0) * 1000)}/kg → ${formatIDR(
                        (p.candidate_price_idr_per_g ?? 0) * 1000
                      )}/kg${p.delta_pct !== null ? `, ${p.delta_pct > 0 ? "+" : ""}${formatPercent(p.delta_pct, 1)}` : ""})`
                  )
                  .join("; ")}
              </p>
            )}
            {comparison.compatibility.changed_stock.length > 0 && (
              <p>
                Perubahan stok input:{" "}
                {comparison.compatibility.changed_stock
                  .map(
                    (s) =>
                      `${s.ingredient_code} (${formatWeightFromGrams(
                        s.base_stock_raw_g
                      )} → ${formatWeightFromGrams(s.candidate_stock_raw_g)})`
                  )
                  .join("; ")}
              </p>
            )}
          </div>
        </div>
      </section>

      {/* Recipe Swaps Section */}
      {!isCandidateInfeasible && (
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-base font-semibold text-[#16354A]">
                Perubahan Pilihan Resep ({comparison.total_slot_swaps} Slot Berubah)
              </h3>
              <p className="mt-0.5 text-xs text-[#647A87]">
                {swappedSlots.length > 0
                  ? "Sistem mengganti resep berikut agar rencana tetap layak dan ekonomis."
                  : "Susunan menu tetap sama karena masih menjadi pilihan terbaik pada kondisi baru."}
              </p>
            </div>
            <StatusBadge
              tone={swappedSlots.length > 0 ? "teal" : "neutral"}
              label={`${swappedSlots.length} Pergantian Resep`}
            />
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#DCE6DE] text-[#647A87]">
                  <th className="pb-2.5 pr-3 font-semibold">Hari</th>
                  <th className="pb-2.5 pr-3 font-semibold">Kategori Slot</th>
                  <th className="pb-2.5 pr-3 font-semibold">Rencana Awal</th>
                  <th className="pb-2.5 pr-3 font-semibold">Setelah Perubahan</th>
                  <th className="pb-2.5 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EEF3EE]">
                {(swappedSlots.length > 0 ? swappedSlots : comparison.recipe_changes.slice(0, 8)).map(
                  (row) => (
                    <tr
                      key={`${row.day_index}-${row.slot}`}
                      className={row.changed ? "bg-[#EBF6F5]/40" : ""}
                    >
                      <td className="py-2.5 pr-3 font-semibold text-[#16354A]">
                        {formatDayLabel(row.day_index)}
                      </td>
                      <td className="py-2.5 pr-3 text-[#4A6170]">{formatSlotLabel(row.slot)}</td>
                      <td className="py-2.5 pr-3 text-[#4A6170]">{row.base_recipe_name ?? "—"}</td>
                      <td className="py-2.5 pr-3 font-semibold text-[#16354A]">
                        {row.candidate_recipe_name ?? "—"}
                      </td>
                      <td className="py-2.5">
                        {row.changed ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-[#EBF6F5] px-2 py-0.5 text-[11px] font-semibold text-[#0F766E]">
                            <ArrowRightLeft className="h-3 w-3" aria-hidden="true" />
                            Diganti
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] text-[#647A87]">
                            <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                            Tetap
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Ingredient & Nutrition Side-by-Side */}
      {!isCandidateInfeasible && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Ingredient usage diff */}
          <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
            <h3 className="text-base font-semibold text-[#16354A]">
              Perubahan Pemakaian Bahan & Stok
            </h3>
            <p className="mt-0.5 text-xs text-[#647A87]">
              Perbandingan berat mentah yang digunakan dan rasio pemakaian stok tersedia.
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#DCE6DE] text-[#647A87]">
                    <th className="pb-2 pr-2 font-semibold">Bahan</th>
                    <th className="pb-2 pr-2 text-right font-semibold">Awal</th>
                    <th className="pb-2 pr-2 text-right font-semibold">Baru</th>
                    <th className="pb-2 text-right font-semibold">Pakai Stok</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EEF3EE] tabular-nums">
                  {(changedMaterials.length > 0
                    ? changedMaterials
                    : comparison.ingredient_usage_comparison.slice(0, 8)
                  ).map((m) => (
                    <tr key={m.ingredient_code}>
                      <td className="py-2 pr-2 font-semibold text-[#16354A]">{m.ingredient_name}</td>
                      <td className="py-2 pr-2 text-right text-[#4A6170]">
                        {formatWeightFromGrams(m.base_used_raw_g)}
                      </td>
                      <td className="py-2 pr-2 text-right font-semibold text-[#16354A]">
                        {formatWeightFromGrams(m.candidate_used_raw_g)}
                      </td>
                      <td className="py-2 text-right text-[#4A6170]">
                        {formatPercent(m.candidate_utilization_pct, 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Nutrition margins */}
          <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
            <h3 className="text-base font-semibold text-[#16354A]">
              Rata-rata Gizi & Batas Target Simulasi
            </h3>
            <p className="mt-0.5 text-xs text-[#647A87]">
              Margin positif berarti seluruh hari memenuhi target minimum/maksimum simulasi.
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#DCE6DE] text-[#647A87]">
                    <th className="pb-2 pr-2 font-semibold">Zat Gizi</th>
                    <th className="pb-2 pr-2 text-right font-semibold">Awal</th>
                    <th className="pb-2 pr-2 text-right font-semibold">Baru</th>
                    <th className="pb-2 text-right font-semibold">Margin Min</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EEF3EE] tabular-nums">
                  {comparison.nutrient_comparison.map((n) => {
                    const meta = formatNutrientLabel(n.nutrient_key);
                    return (
                      <tr key={n.nutrient_key}>
                        <td className="py-2 pr-2 font-semibold text-[#16354A]">
                          {meta.label}{" "}
                          <span className="font-normal text-[#647A87]">({n.unit || meta.unit})</span>
                        </td>
                        <td className="py-2 pr-2 text-right text-[#4A6170]">
                          {formatDecimal(n.base_avg_per_serving, 1)}
                        </td>
                        <td className="py-2 pr-2 text-right font-semibold text-[#16354A]">
                          {formatDecimal(n.candidate_avg_per_serving, 1)}
                        </td>
                        <td className="py-2 text-right text-[#166534]">
                          {n.candidate_min_margin_above_floor !== null
                            ? `+${formatDecimal(n.candidate_min_margin_above_floor, 1)}`
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
