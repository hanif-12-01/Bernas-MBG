import React from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";

export type BadgeTone = "success" | "warning" | "critical" | "neutral" | "teal";

interface StatusBadgeProps {
  tone: BadgeTone;
  label: string;
  size?: "sm" | "md";
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  success: "bg-[#ECFDF3] text-[#166534] border-[#BBE9CC] dark:bg-[#0D291A] dark:text-[#4ADE80] dark:border-[#1D5E3A]",
  warning: "bg-[#FEF6E7] text-[#8A5300] border-[#F5D59B] dark:bg-[#2B1F0A] dark:text-[#FBBF24] dark:border-[#6E4A12]",
  critical: "bg-[#FEF0F0] text-[#991B1B] border-[#F5C2C2] dark:bg-[#2D1216] dark:text-[#FB7185] dark:border-[#6E242C]",
  neutral: "bg-[#EEF3EE] text-[#4A6170] border-[#DCE6DE] dark:bg-[#182630] dark:text-[#A3B7C4] dark:border-[#263845]",
  teal: "bg-[#EBF6F5] text-[#0F766E] border-[#B5DFDA] dark:bg-[#102D2B] dark:text-[#5EEAD4] dark:border-[#1F5752]",
};

export function StatusBadge({ tone, label, size = "sm" }: StatusBadgeProps) {
  const Icon =
    tone === "success"
      ? CheckCircle2
      : tone === "warning"
      ? AlertTriangle
      : tone === "critical"
      ? AlertCircle
      : Info;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${
        size === "md" ? "px-3 py-1 text-xs" : "px-2.5 py-0.5 text-xs"
      } ${TONE_CLASSES[tone]}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}
