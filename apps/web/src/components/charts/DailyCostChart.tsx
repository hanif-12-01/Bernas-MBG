"use client";

import React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useTheme } from "@/hooks/useTheme";
import { formatDayLabel, formatIDR } from "@/lib/formatters/indonesian";
import type { DayPlan } from "@/types/api";

interface DailyCostChartProps {
  days: DayPlan[];
  budgetPerServing: number;
}

export function DailyCostChart({ days, budgetPerServing }: DailyCostChartProps) {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const gridStroke = isDark ? "#263845" : "#E6EEE8";
  const axisTickFill = isDark ? "#93AAB8" : "#4A6170";
  const axisLineStroke = isDark ? "#263845" : "#DCE6DE";
  const cursorFill = isDark ? "#182630" : "#F5F8F5";
  const tooltipBg = isDark ? "#111C24" : "#FFFFFF";
  const tooltipBorder = isDark ? "#263845" : "#DCE6DE";
  const tooltipColor = isDark ? "#EBF2F6" : "#16354A";
  const barFill = isDark ? "#14B8A6" : "#0F766E";

  if (days.length === 0) {
    return (
      <div className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
        <h2 className="text-base font-semibold text-[#16354A]">Biaya Harian per Porsi</h2>
        <p className="mt-2 text-sm text-[#647A87]">
          Grafik biaya harian hanya ditampilkan untuk rencana yang lolos verifikasi kelayakan.
        </p>
      </div>
    );
  }

  const data = days.map((d) => ({
    name: formatDayLabel(d.day_index).replace(" (", "\n("),
    shortName: `Hari ${d.day_index}`,
    cost: d.daily_cost_idr_per_serving,
    budget: budgetPerServing,
  }));

  const maxVal = Math.max(budgetPerServing, ...data.map((d) => d.cost)) * 1.15;

  return (
    <div className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[#16354A]">
            Biaya Harian vs Batas Anggaran
          </h2>
          <p className="mt-0.5 text-xs text-[#647A87]">
            Biaya per porsi tiap hari dibandingkan garis batas {formatIDR(budgetPerServing)}.
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs text-[#4A6170]">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-[#0F766E]" />
            Biaya Harian
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 bg-[#E9A23B]" />
            Batas Anggaran
          </span>
        </div>
      </div>

      <div className="mt-4 h-64 w-full" role="img" aria-label="Grafik perbandingan biaya harian per porsi terhadap batas anggaran">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 12, right: 16, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
            <XAxis
              dataKey="shortName"
              tick={{ fill: axisTickFill, fontSize: 12 }}
              axisLine={{ stroke: axisLineStroke }}
              tickLine={false}
            />
            <YAxis
              domain={[0, Math.ceil(maxVal / 1000) * 1000]}
              tick={{ fill: axisTickFill, fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => `Rp${Math.round(v / 1000)}rb`}
            />
            <Tooltip
              cursor={{ fill: cursorFill }}
              contentStyle={{
                backgroundColor: tooltipBg,
                borderRadius: "12px",
                borderColor: tooltipBorder,
                fontSize: "12px",
                color: tooltipColor,
              }}
              formatter={(value: number) => [formatIDR(value), "Biaya per Porsi"]}
            />
            <ReferenceLine
              y={budgetPerServing}
              stroke="#E9A23B"
              strokeDasharray="6 4"
              strokeWidth={2}
            />
            <Bar dataKey="cost" fill={barFill} radius={[8, 8, 0, 0]} maxBarSize={48} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
