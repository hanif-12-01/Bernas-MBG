"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiClient } from "@/lib/api/client";
import {
  formatDisruptionTypeLabel,
  formatIDR,
  formatRecoveryModeLabel,
  formatSlotLabel,
} from "@/lib/formatters/indonesian";
import type { RecoveryEventResponse } from "@/types/api";

interface RecoveryReviewSummaryCardProps {
  recoveryEventId: string;
  isStaleInventoryHint?: boolean;
  onRecomputeHref?: string;
}

export function RecoveryReviewSummaryCard({
  recoveryEventId,
  isStaleInventoryHint = false,
  onRecomputeHref,
}: RecoveryReviewSummaryCardProps) {
  const [expanded, setExpanded] = useState(false);

  const eventQuery = useQuery<RecoveryEventResponse>({
    queryKey: ["recovery-event", recoveryEventId],
    queryFn: () => apiClient.getRecoveryEvent(recoveryEventId),
    staleTime: 10_000,
  });

  const ev = eventQuery.data;
  const stale = ev ? ev.is_stale_inventory : isStaleInventoryHint;

  if (eventQuery.isLoading) {
    return (
      <div className="rounded-xl border border-[#B5DFDA] bg-[#EBF6F5]/60 p-3 text-xs text-[#4A6170]">
        Memuat ringkasan usulan pemulihan gangguan...
      </div>
    );
  }

  if (eventQuery.isError || !ev) {
    return stale ? (
      <div
        role="alert"
        className="rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-3 text-xs text-[#991B1B]"
      >
        Stok gudang berubah sejak usulan pemulihan diajukan. Hitung ulang sebelum menyetujui.
      </div>
    ) : null;
  }

  const chosen =
    ev.selected_mode === "MIN_COST" ? ev.min_cost : ev.min_disruption;

  return (
    <div
      data-testid={`recovery-summary-${ev.id}`}
      className="rounded-xl border border-[#B5DFDA] bg-[#F4FAF9] p-3.5 text-xs text-[#16354A] space-y-2.5"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge tone="warning" label="Usulan Pemulihan Gangguan" />
            {ev.disruption_types.map((dt) => (
              <span
                key={dt}
                className="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-[#4A6170] border border-[#DCE6DE]"
              >
                {formatDisruptionTypeLabel(dt)}
              </span>
            ))}
          </div>
          <p className="font-semibold text-[#16354A]">{ev.disruption_summary}</p>
        </div>

        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-[#DCE6DE] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#0F766E] hover:bg-[#EBF6F5]"
        >
          <span>{expanded ? "Tutup Rincian" : `Lihat ${chosen.changed_slots_count} Perubahan Slot`}</span>
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {stale && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#F5C2C2] bg-[#FEF0F0] px-3 py-2 text-[#991B1B]"
        >
          <div className="flex items-start gap-2">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>
              <strong>Snapshot Stok Berubah:</strong> Ketersediaan gudang berubah sejak usulan ini
              diajukan. Persetujuan diblokir otomatis sampai Perencana Menu menghitung ulang.
            </span>
          </div>
          {onRecomputeHref && (
            <Link
              href={onRecomputeHref}
              className="inline-flex min-h-[36px] items-center gap-1 rounded-lg bg-white px-2.5 py-1 text-[11px] font-bold text-[#991B1B] border border-[#F5C2C2]"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Hitung Ulang</span>
            </Link>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="rounded-lg border border-[#DCE6DE] bg-white p-2.5">
          <span className="block text-[11px] text-[#647A87]">Mode Dipilih</span>
          <strong className="mt-0.5 block text-xs text-[#16354A]">
            {formatRecoveryModeLabel(ev.selected_mode)}
          </strong>
        </div>
        <div className="rounded-lg border border-[#DCE6DE] bg-white p-2.5">
          <span className="block text-[11px] text-[#647A87]">Stabilitas Jadwal</span>
          <strong className="mt-0.5 block text-xs text-[#0F766E] tabular-nums">
            {chosen.changed_slots_count} dari {chosen.total_slots_count} slot diubah
          </strong>
        </div>
        <div className="rounded-lg border border-[#DCE6DE] bg-white p-2.5">
          <span className="block text-[11px] text-[#647A87]">Estimasi Biaya Pengganti</span>
          <strong className="mt-0.5 block text-xs text-[#16354A] tabular-nums">
            {formatIDR(chosen.total_cost_idr)} ({formatIDR(chosen.cost_per_serving_idr)}/porsi)
          </strong>
        </div>
      </div>

      <p className="text-[11px] leading-relaxed text-[#4A6170]">
        {ev.comparison.comparison_notice}
      </p>

      {expanded && (
        <div className="space-y-2 border-t border-[#DCE6DE] pt-2.5">
          {chosen.changed_slots.length === 0 ? (
            <p className="text-[#4A6170]">
              Tidak ada resep yang diganti — jadwal asli tetap layak dijalankan.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {chosen.changed_slots.map((swap) => (
                <li
                  key={`${swap.day_index}-${swap.slot}`}
                  className="rounded-lg border border-[#DCE6DE] bg-white px-3 py-2"
                >
                  <div className="flex flex-wrap items-center gap-1.5 font-semibold text-[#16354A]">
                    <span>Hari {swap.day_index}</span>
                    <span>•</span>
                    <span>{formatSlotLabel(swap.slot)}:</span>
                    <span className="line-through text-[#991B1B]">{swap.original_recipe_name}</span>
                    <ArrowRight className="h-3.5 w-3.5 text-[#0F766E]" aria-hidden="true" />
                    <span className="text-[#0F766E]">{swap.new_recipe_name}</span>
                  </div>
                  <p className="mt-0.5 text-[11px] text-[#526675]">{swap.reason}</p>
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="inline-flex items-center gap-1 text-[11px] text-[#8A5300]">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              Rencana baseline sebelumnya tetap tersimpan terpisah di riwayat.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
