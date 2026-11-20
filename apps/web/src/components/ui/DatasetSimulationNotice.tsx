import React from "react";
import { FlaskConical } from "lucide-react";

interface DatasetSimulationNoticeProps {
  simulationOnly?: boolean;
  datasetName?: string;
  compact?: boolean;
}

export function DatasetSimulationNotice({
  simulationOnly = true,
  datasetName,
  compact = false,
}: DatasetSimulationNoticeProps) {
  if (!simulationOnly) return null;

  if (compact) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-[#F5D59B] bg-[#FEF6E7] px-2.5 py-1 text-xs font-semibold text-[#8A5300]"
        title="Data simulasi DEMO_ONLY; bukan standar resmi BGN dan belum divalidasi ahli gizi."
      >
        <FlaskConical className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>Data Simulasi (DEMO_ONLY)</span>
      </span>
    );
  }

  return (
    <div
      role="note"
      className="flex items-start gap-3 rounded-xl border border-[#F5D59B] bg-[#FEF6E7] px-4 py-3 text-sm text-[#8A5300]"
    >
      <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-[#B4690E]" aria-hidden="true" />
      <div className="leading-relaxed">
        <span className="font-semibold">Mode Data Simulasi (DEMO_ONLY): </span>
        {datasetName ? `Dataset "${datasetName}" ` : "Data bahan, harga, stok, dan target gizi "}
        bersifat simulasi teknis untuk evaluasi sistem, bukan standar resmi BGN dan belum melalui
        validasi ahli gizi.
      </div>
    </div>
  );
}
