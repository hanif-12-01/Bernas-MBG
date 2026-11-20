import React, { useState } from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { NumericInput } from "@/components/ui/NumericInput";
import { formatNumericDisplay, parseNumericInput } from "@/lib/formatters/numericInput";

function Harness({
  initial,
  mode,
  min,
}: {
  initial: string;
  mode: "integer" | "decimal";
  min: number;
}) {
  const [val, setVal] = useState(initial);
  const parsed = parseNumericInput(val, { mode, min });
  const error = !parsed.valid && !parsed.isIntermediate ? parsed.error : null;

  return (
    <NumericInput
      id="test-num"
      label="Test Angka"
      mode={mode}
      min={min}
      value={val}
      error={error}
      onChange={setVal}
    />
  );
}

describe("parseNumericInput & formatNumericDisplay", () => {
  it("normalizes leading zeros for integer and Indonesian decimal values", () => {
    const r1 = parseNumericInput("030", { mode: "decimal", min: 0 });
    expect(r1).toEqual({ valid: true, value: 30, normalizedText: "30", isIntermediate: false });

    const r2 = parseNumericInput("007,5", { mode: "decimal", min: 0 });
    expect(r2).toEqual({ valid: true, value: 7.5, normalizedText: "7,5", isIntermediate: false });

    const r3 = parseNumericInput("028000", { mode: "integer", min: 1 });
    expect(r3).toEqual({
      valid: true,
      value: 28000,
      normalizedText: "28000",
      isIntermediate: false,
    });

    expect(formatNumericDisplay(7.5, "decimal")).toBe("7,5");
    expect(formatNumericDisplay(30, "decimal")).toBe("30");
    expect(formatNumericDisplay(28000, "integer")).toBe("28000");
  });

  it("supports Indonesian comma and dot decimal inputs for stock", () => {
    const comma = parseNumericInput("7,5", { mode: "decimal", min: 0 });
    expect(comma.valid).toBe(true);
    if (comma.valid) {
      expect(comma.value).toBe(7.5);
      expect(comma.normalizedText).toBe("7,5");
    }

    const dot = parseNumericInput("7.5", { mode: "decimal", min: 0 });
    expect(dot.valid).toBe(true);
    if (dot.valid) {
      expect(dot.value).toBe(7.5);
      expect(dot.normalizedText).toBe("7,5");
    }

    const zeroStock = parseNumericInput("0", { mode: "decimal", min: 0 });
    expect(zeroStock.valid).toBe(true);
    if (zeroStock.valid) expect(zeroStock.value).toBe(0);
  });

  it("rejects empty input, letters, negative numbers, NaN, Infinity, and malformed decimals", () => {
    for (const bad of ["", "   ", "abc", "-5", "NaN", "Infinity", "-Infinity", "7,5,2", "1e4"]) {
      const dec = parseNumericInput(bad, { mode: "decimal", min: 0 });
      expect(dec.valid, `Expected decimal '${bad}' to be rejected`).toBe(false);

      const intg = parseNumericInput(bad, { mode: "integer", min: 1 });
      expect(intg.valid, `Expected integer '${bad}' to be rejected`).toBe(false);
    }

    // Decimals rejected in integer mode (price)
    const decimalPrice = parseNumericInput("28000,5", { mode: "integer", min: 1 });
    expect(decimalPrice.valid).toBe(false);

    // Zero price rejected per backend contract (price_value > 0)
    const zeroPrice = parseNumericInput("0", { mode: "integer", min: 1 });
    expect(zeroPrice.valid).toBe(false);
  });
});

describe("NumericInput component behavior", () => {
  it("uses text input with numeric/decimal inputMode, selects on focus, and normalizes on blur", () => {
    render(<Harness initial="30" mode="decimal" min={0} />);
    const input = screen.getByLabelText("Test Angka") as HTMLInputElement;

    expect(input.type).toBe("text");
    expect(input.inputMode).toBe("decimal");

    // Focus selects full text
    fireEvent.focus(input);
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(2);

    // Wheel scroll must not mutate value
    fireEvent.wheel(input, { deltaY: -100 });
    expect(input.value).toBe("30");

    // Clearing field keeps it empty (never auto-converts to "0") and shows error
    fireEvent.change(input, { target: { value: "" } });
    expect(input.value).toBe("");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(/tidak boleh kosong/i);

    // Typing "030" and blurring normalizes to "30"
    fireEvent.change(input, { target: { value: "030" } });
    expect(input.value).toBe("030");
    fireEvent.blur(input);
    expect(input.value).toBe("30");
    expect(input).toHaveAttribute("aria-invalid", "false");

    // Typing "007,5" and blurring normalizes to "7,5"
    fireEvent.change(input, { target: { value: "007,5" } });
    fireEvent.blur(input);
    expect(input.value).toBe("7,5");
  });

  it("uses inputMode='numeric' for integer prices and rejects invalid strings", () => {
    render(<Harness initial="28000" mode="integer" min={1} />);
    const input = screen.getByLabelText("Test Angka") as HTMLInputElement;

    expect(input.type).toBe("text");
    expect(input.inputMode).toBe("numeric");

    fireEvent.change(input, { target: { value: "-5" } });
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(/negatif/i);

    fireEvent.change(input, { target: { value: "abc" } });
    expect(input).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(input, { target: { value: "032000" } });
    fireEvent.blur(input);
    expect(input.value).toBe("32000");
    expect(input).toHaveAttribute("aria-invalid", "false");
  });
});
