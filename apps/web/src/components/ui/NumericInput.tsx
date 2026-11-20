"use client";

import React, { useRef } from "react";

import {
  parseNumericInput,
  type NumericInputMode,
  type NumericParseResult,
} from "@/lib/formatters/numericInput";

export interface NumericInputProps {
  id: string;
  value: string;
  onChange: (rawValue: string) => void;
  onBlurNormalize?: (result: NumericParseResult) => void;
  mode: NumericInputMode;
  min?: number;
  max?: number;
  minErrorMessage?: string;
  maxErrorMessage?: string;
  label: string;
  disabled?: boolean;
  error?: string | null;
  isModified?: boolean;
  modifiedTone?: "teal" | "amber";
  placeholder?: string;
  className?: string;
}

/**
 * Accessible controlled text-based numeric input without browser spinners or mouse-wheel mutation.
 * - Selects existing text on focus so typing immediately replaces the previous number.
 * - Keeps raw string while typing (allows empty field and Indonesian comma decimals like `7,5`).
 * - Normalizes leading zeros (`030` -> `30`, `007,5` -> `7,5`) on blur.
 */
export function NumericInput({
  id,
  value,
  onChange,
  onBlurNormalize,
  mode,
  min,
  max,
  minErrorMessage,
  maxErrorMessage,
  label,
  disabled = false,
  error,
  isModified = false,
  modifiedTone = "teal",
  placeholder,
  className = "",
}: NumericInputProps) {
  const selectOnMouseUpRef = useRef(false);
  const errorId = `${id}-error`;

  const handleFocus = (e: React.FocusEvent<HTMLInputElement>) => {
    e.currentTarget.select();
    selectOnMouseUpRef.current = true;
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLInputElement>) => {
    if (selectOnMouseUpRef.current) {
      e.preventDefault();
      selectOnMouseUpRef.current = false;
    }
  };

  const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    selectOnMouseUpRef.current = false;
    const result = parseNumericInput(e.currentTarget.value, {
      mode,
      min,
      max,
      minErrorMessage,
      maxErrorMessage,
    });
    if (result.valid && result.normalizedText !== value) {
      onChange(result.normalizedText);
    }
    onBlurNormalize?.(result);
  };

  const stateClasses = error
    ? "border-[#C43D3D] bg-[#FEF0F0] text-[#991B1B] focus-visible:border-[#C43D3D] focus-visible:ring-[#C43D3D]/30"
    : isModified
    ? modifiedTone === "amber"
      ? "border-[#E9A23B] bg-[#FEF6E7] text-[#8A5300] focus-visible:border-[#E9A23B] focus-visible:ring-[#E9A23B]/30"
      : "border-[#0F766E] bg-[#EBF6F5] text-[#0F766E] focus-visible:border-[#0F766E] focus-visible:ring-[#0F766E]/30"
    : "border-[#DCE6DE] bg-white text-[#16354A] focus-visible:border-[#0F766E] focus-visible:ring-[#0F766E]/30";

  return (
    <div className="relative flex flex-col">
      <label className="sr-only" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="text"
        inputMode={mode === "integer" ? "numeric" : "decimal"}
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
        value={value}
        placeholder={placeholder}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? errorId : undefined}
        onFocus={handleFocus}
        onMouseUp={handleMouseUp}
        onChange={(e) => onChange(e.target.value)}
        onBlur={handleBlur}
        className={`h-9 rounded-lg border px-2.5 text-sm font-medium tabular-nums transition-colors focus:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-60 ${stateClasses} ${className}`}
      />
      {error && (
        <p id={errorId} role="alert" className="mt-1 text-[11px] font-medium leading-tight text-[#C43D3D]">
          {error}
        </p>
      )}
    </div>
  );
}
