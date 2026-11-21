"use client";

import React from "react";
import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/hooks/useTheme";

interface ThemeToggleProps {
  compact?: boolean;
  fullWidth?: boolean;
  className?: string;
}

export function ThemeToggle({
  compact = false,
  fullWidth = false,
  className = "",
}: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      data-testid="theme-toggle"
      aria-pressed={isDark}
      aria-label={isDark ? "Beralih ke mode terang (Light)" : "Beralih ke mode gelap (Dark)"}
      title={isDark ? "Mode Terang (Light)" : "Mode Gelap (Dark)"}
      className={`inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl border border-[#DCE6DE] bg-white px-2.5 text-xs font-semibold text-[#4A6170] transition-colors hover:bg-[#F5F8F5] hover:text-[#16354A] ${
        fullWidth ? "w-full" : ""
      } ${className}`}
    >
      {isDark ? (
        <Sun className="h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
      )}
      <span className={compact ? "hidden md:inline" : ""}>
        {isDark ? "Mode Terang" : "Mode Gelap"}
      </span>
    </button>
  );
}
