import React from "react";

interface KPIStatCardProps {
  label: string;
  value: string;
  helper?: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  accent?: "default" | "teal" | "warning" | "critical";
}

export function KPIStatCard({
  label,
  value,
  helper,
  icon,
  badge,
  accent = "default",
}: KPIStatCardProps) {
  const borderClass =
    accent === "teal"
      ? "border-[#B5DFDA]"
      : accent === "warning"
      ? "border-[#F5D59B]"
      : accent === "critical"
      ? "border-[#F5C2C2]"
      : "border-[#DCE6DE]";

  return (
    <div
      className={`flex flex-col justify-between rounded-2xl border bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)] ${borderClass}`}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] font-semibold text-[#4A6170]">{label}</p>
        {icon && (
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#F5F8F5] text-[#0F766E]">
            {icon}
          </div>
        )}
      </div>

      <div className="mt-3">
        <p className="text-2xl font-bold tracking-tight text-[#16354A] tabular-nums sm:text-[26px]">
          {value}
        </p>
        {badge && <div className="mt-2">{badge}</div>}
        {helper && <p className="mt-2 text-xs leading-relaxed text-[#647A87]">{helper}</p>}
      </div>
    </div>
  );
}
