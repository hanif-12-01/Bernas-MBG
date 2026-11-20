export type NumericInputMode = "integer" | "decimal";

export interface NumericValidationOptions {
  mode: NumericInputMode;
  min?: number;
  max?: number;
  minErrorMessage?: string;
  maxErrorMessage?: string;
}

export type NumericParseResult =
  | {
      valid: true;
      value: number;
      normalizedText: string;
      isIntermediate: false;
    }
  | {
      valid: false;
      error: string;
      isIntermediate: boolean;
    };

/**
 * Formats a finite number into clean Indonesian input display text
 * without leading zeros or unnecessary trailing decimal zeros.
 */
export function formatNumericDisplay(value: number, mode: NumericInputMode): string {
  if (!Number.isFinite(value)) return "";
  if (mode === "integer") {
    return String(Math.round(value));
  }
  // Round to max 3 decimal places (1 gram precision for kg inputs) and strip trailing zeros
  const rounded = Number(value.toFixed(3));
  const normalized = Object.is(rounded, -0) ? 0 : rounded;
  return String(normalized).replace(".", ",");
}

/**
 * Strictly validates and parses a user-typed numeric string.
 * - Never coerces empty string to 0.
 * - Supports Indonesian comma (`,`) and standard dot (`.`) as decimal separator in `decimal` mode.
 * - Normalizes leading zeros (`030` -> `30`, `007,5` -> `7,5`).
 * - Rejects letters, negative values (when min >= 0), NaN, Infinity, and malformed decimals.
 */
export function parseNumericInput(
  raw: string,
  options: NumericValidationOptions
): NumericParseResult {
  const { mode, min, max, minErrorMessage, maxErrorMessage } = options;
  const trimmed = raw.trim();

  if (trimmed === "") {
    return {
      valid: false,
      error: "Nilai tidak boleh kosong.",
      isIntermediate: false,
    };
  }

  // Reject explicit negative inputs clearly when min >= 0 (or non-negative domain)
  if (trimmed.startsWith("-")) {
    const isNegativeNumberLike = /^-\s*\d+(?:[.,]\d*)?$/.test(trimmed);
    if (isNegativeNumberLike && min !== undefined && min >= 0) {
      return {
        valid: false,
        error: "Nilai tidak boleh negatif.",
        isIntermediate: false,
      };
    }
    if (min !== undefined && min >= 0) {
      return {
        valid: false,
        error: "Nilai tidak boleh negatif.",
        isIntermediate: false,
      };
    }
  }

  // Reject NaN / Infinity / letters explicitly
  const lower = trimmed.toLowerCase();
  if (lower === "nan" || lower === "infinity" || lower === "+infinity" || lower === "-infinity") {
    return {
      valid: false,
      error: "Masukkan angka yang valid.",
      isIntermediate: false,
    };
  }

  if (mode === "integer") {
    if (/^\d+[.,]\d*$/.test(trimmed)) {
      return {
        valid: false,
        error: "Masukkan bilangan bulat tanpa desimal.",
        isIntermediate: false,
      };
    }
    if (!/^\d+$/.test(trimmed)) {
      return {
        valid: false,
        error: "Masukkan angka bulat yang valid.",
        isIntermediate: false,
      };
    }

    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed) || !Number.isSafeInteger(parsed)) {
      return {
        valid: false,
        error: "Angka terlalu besar atau tidak valid.",
        isIntermediate: false,
      };
    }

    if (min !== undefined && parsed < min) {
      return {
        valid: false,
        error: minErrorMessage ?? `Nilai minimal ${formatNumericDisplay(min, "integer")}.`,
        isIntermediate: false,
      };
    }
    if (max !== undefined && parsed > max) {
      return {
        valid: false,
        error: maxErrorMessage ?? `Nilai maksimal ${formatNumericDisplay(max, "integer")}.`,
        isIntermediate: false,
      };
    }

    return {
      valid: true,
      value: parsed,
      normalizedText: formatNumericDisplay(parsed, "integer"),
      isIntermediate: false,
    };
  }

  // Decimal mode
  // Intermediate typing state like "7," or "7." while user is entering "7,5"
  if (/^\d+[.,]$/.test(trimmed)) {
    return {
      valid: false,
      error: "Lengkapi angka di belakang koma (contoh: 7,5).",
      isIntermediate: true,
    };
  }

  if (!/^\d+(?:[.,]\d+)?$/.test(trimmed)) {
    return {
      valid: false,
      error: "Masukkan angka yang valid (contoh: 7,5 atau 30).",
      isIntermediate: false,
    };
  }

  const canonical = trimmed.replace(",", ".");
  const parsed = Number(canonical);
  if (!Number.isFinite(parsed)) {
    return {
      valid: false,
      error: "Masukkan angka yang valid.",
      isIntermediate: false,
    };
  }

  if (min !== undefined && parsed < min) {
    return {
      valid: false,
      error: minErrorMessage ?? `Nilai minimal ${formatNumericDisplay(min, "decimal")}.`,
      isIntermediate: false,
    };
  }
  if (max !== undefined && parsed > max) {
    return {
      valid: false,
      error: maxErrorMessage ?? `Nilai maksimal ${formatNumericDisplay(max, "decimal")}.`,
      isIntermediate: false,
    };
  }

  return {
    valid: true,
    value: parsed,
    normalizedText: formatNumericDisplay(parsed, "decimal"),
    isIntermediate: false,
  };
}
