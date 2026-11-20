import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AccessDeniedState } from "@/components/feedback/FeedbackStates";
import {
  formatAuditAction,
  formatMenuReviewStatus,
  formatObservationStatus,
  formatQCOutcome,
  formatQCStatus,
  formatRoleLabel,
} from "@/lib/formatters/indonesian";

describe("Sprint 3A Multi-Actor & Vision QC Formatters", () => {
  it("formats roles, review statuses, QC statuses, and audit actions in clear Indonesian", () => {
    expect(formatRoleLabel("KITCHEN_MANAGER")).toBe("Kepala Dapur");
    expect(formatRoleLabel("MENU_PLANNER")).toBe("Perencana Menu");
    expect(formatRoleLabel("QC_OFFICER")).toBe("Petugas QC");
    expect(formatRoleLabel("NUTRITIONIST")).toBe("Ahli Gizi");

    expect(formatMenuReviewStatus("DRAFT").label).toContain("Draft");
    expect(formatMenuReviewStatus("SUBMITTED").tone).toBe("warning");
    expect(formatMenuReviewStatus("APPROVED").label).toBe("Disetujui Operasional");
    expect(formatMenuReviewStatus("REVISION_REQUIRED").tone).toBe("critical");

    expect(formatQCStatus("AI_ANALYZED").tone).toBe("warning");
    expect(formatQCStatus("SUBMITTED").label).toContain("Kepala Dapur");

    // Food safety guardrail: ACCEPTED_FOR_RECORD MUST NOT use green safety claims or say safe to eat
    const accepted = formatQCOutcome("ACCEPTED_FOR_RECORD");
    expect(accepted.tone).toBe("neutral");
    expect(accepted.label.toLowerCase()).not.toContain("aman dikonsumsi");
    expect(accepted.label.toLowerCase()).toContain("arsip");

    expect(formatObservationStatus("visible")).toBe("Terlihat Jelas");
    expect(formatObservationStatus("not_visible")).toBe("Belum Terlihat");
    expect(formatAuditAction("qc_inspection.ai_analyzed")).toContain("visual AI");
  });

  it("renders AccessDeniedState clearly with back link", () => {
    render(
      <AccessDeniedState
        title="Akses Khusus Perencana Menu"
        description="Hanya peran Perencana Menu yang dapat mengubah harga."
      />
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Akses Khusus Perencana Menu")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kembali ke Beranda/i })).toHaveAttribute(
      "href",
      "/dashboard"
    );
  });
});
