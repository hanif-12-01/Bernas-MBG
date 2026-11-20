"use client";

import React from "react";
import { formatIDR, formatPercent } from "@/lib/formatters/indonesian";

interface BudgetProgressProps {
  averageCostPerServing: number | null;
  budgetPerServing: number | null;
}

export function BudgetProgress({
  averageCostPerServing,
  budgetPerServing,
}: BudgetProgressProps) {
  if (
    averageCostPerServing === null ||
    budgetPerServing === null ||
    budgetPerServing <= 0
  ) {
    return (
      <div className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
        <h2 className="text-base font-semibold text-[#16354A]">
          Pemanfaatan Batas Anggaran per Porsi
        </h2>
        <p className="mt-2 text-sm text-[#647A87]">
          Belum ada hasil perhitungan layak untuk dibandingkan dengan batas anggaran.
        </p>
      </div>
    );
  }

  const ratio = (averageCostPerServing / budgetPerServing) * 100;
  const clamped = Math.min(Math.max(ratio, 0), 100);
  const remaining = budgetPerServing - averageCostPerServing;
  const isOver = remaining < 0;
  const isNearCap = !isOver && ratio >= 90;

  const barColor = isOver
    ? "bg-[#C43D3D]"
    : isNearCap
    ? "bg-[#E9A23B]"
    : "bg-[#0F766E]";

  return (
    <div className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[#16354A]">
            Pemanfaatan Batas Anggaran per Porsi
          </h2>
          <p className="mt-0.5 text-xs text-[#647A87]">
            Rata-rata biaya rencana dibandingkan batas anggaran yang dikonfigurasi pada skenario.
          </p>
        </div>
        <div className="text-right tabular-nums">
          <span className="text-lg font-bold text-[#16354A]">
            {formatPercent(ratio, 1)}
          </span>
          <span className="ml-1.5 text-xs text-[#647A87]">dari batas anggaran</span>
        </div>
      </div>

      <div
        className="mt-4 h-3 w-full overflow-hidden rounded-full bg-[#EEF3EE]"
        role="progressbar"
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Persentase penggunaan anggaran per porsi"
      >
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${clamped}%` }}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-[#4A6170] tabular-nums">
        <span>
          Rata-rata rencana: <strong className="text-[#16354A]">{formatIDR(averageCostPerServing)}</strong> / porsi
        </span>
        <span>
          Batas anggaran: <strong className="text-[#16354A]">{formatIDR(budgetPerServing)}</strong> / porsi
        </span>
        <span>
          {isOver ? (
            <strong className="text-[#991B1B]">
              Melebihi batas {formatIDR(Math.abs(remaining))} / porsi
            </strong>
          ) : (
            <>
              Sisa ruang anggaran:{" "}
              <strong className="text-[#16354A]">{formatIDR(remaining)}</strong> / porsi{" "}
              <span className="text-[#647A87]">(bukan klaim penghematan)</span>
            </>
          )}
        </span>
      </div>
    </div>
  );
}
