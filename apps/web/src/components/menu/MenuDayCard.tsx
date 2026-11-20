import React from "react";
import { Utensils } from "lucide-react";

import {
  formatDayLabel,
  formatDecimal,
  formatIDR,
  formatSlotLabel,
} from "@/lib/formatters/indonesian";
import type { DayPlan, SlotEnum } from "@/types/api";

const SLOT_ORDER: SlotEnum[] = ["staple", "protein", "vegetable", "fruit"];

interface MenuDayCardProps {
  day: DayPlan;
  budgetPerServing?: number;
  selected?: boolean;
  onSelect?: () => void;
  compact?: boolean;
}

export function MenuDayCard({
  day,
  budgetPerServing,
  selected = false,
  onSelect,
  compact = false,
}: MenuDayCardProps) {
  const withinBudget =
    budgetPerServing !== undefined ? day.daily_cost_idr_per_serving <= budgetPerServing : true;

  const Wrapper = onSelect ? "button" : "div";

  return (
    <Wrapper
      type={onSelect ? "button" : undefined}
      onClick={onSelect}
      className={`flex w-full flex-col justify-between rounded-2xl border bg-white p-4 text-left transition-colors ${
        selected
          ? "border-[#0F766E] ring-2 ring-[#0F766E]/20"
          : "border-[#DCE6DE] hover:border-[#B5DFDA]"
      }`}
    >
      <div>
        <div className="flex items-start justify-between gap-2 border-b border-[#EEF3EE] pb-3">
          <div>
            <p className="text-sm font-bold text-[#16354A]">{formatDayLabel(day.day_index)}</p>
            <p className="mt-0.5 text-xs text-[#647A87]">4 Komponen Menu</p>
          </div>
          <span
            className={`rounded-lg px-2 py-1 text-xs font-bold tabular-nums ${
              withinBudget
                ? "bg-[#EBF6F5] text-[#0F766E]"
                : "bg-[#FEF0F0] text-[#991B1B]"
            }`}
          >
            {formatIDR(day.daily_cost_idr_per_serving)}
          </span>
        </div>

        <ul className="mt-3 space-y-2">
          {SLOT_ORDER.map((slot) => {
            const name = day.recipe_names_by_slot[slot];
            if (!name) return null;
            return (
              <li key={slot} className="flex items-start gap-2 text-xs">
                <Utensils className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#647A87]" aria-hidden="true" />
                <div className="min-w-0">
                  <span className="block text-[11px] font-medium text-[#647A87]">
                    {formatSlotLabel(slot)}
                  </span>
                  <span className="block truncate font-semibold text-[#16354A]" title={name}>
                    {name}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {!compact && (
        <div className="mt-4 flex flex-wrap gap-2 border-t border-[#EEF3EE] pt-3 text-[11px] text-[#4A6170] tabular-nums">
          {day.nutrients_per_serving.energy_kcal !== undefined && (
            <span className="rounded-md bg-[#F5F8F5] px-2 py-0.5">
              Energi: <strong>{formatDecimal(day.nutrients_per_serving.energy_kcal, 0)} kkal</strong>
            </span>
          )}
          {day.nutrients_per_serving.protein_g !== undefined && (
            <span className="rounded-md bg-[#F5F8F5] px-2 py-0.5">
              Protein: <strong>{formatDecimal(day.nutrients_per_serving.protein_g, 1)} g</strong>
            </span>
          )}
        </div>
      )}
    </Wrapper>
  );
}
