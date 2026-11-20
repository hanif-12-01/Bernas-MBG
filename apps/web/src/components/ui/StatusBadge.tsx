import React from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";

export type BadgeTone = "success" | "warning" | "critical" | "neutral" | "teal";

interface StatusBadgeProps {
  tone: BadgeTone;
  label: string;
  size?: "sm" | "md";
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  success: "bg-[#ECFDF3] text-[#166534] border-[#BBE9CC]",
  warning: "bg-[#FEF6E7] text-[#8A5300] border-[#F5D59B]",
  critical: "bg-[#FEF0F0] text-[#991B1B] border-[#F5C2C2]",
  neutral: "bg-[#EEF3EE] text-[#4A6170] border-[#DCE6DE]",
  teal: "bg-[#EBF6F5] text-[#0F766E] border-[#B5DFDA]",
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
