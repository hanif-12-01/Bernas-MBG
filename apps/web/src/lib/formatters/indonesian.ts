import type {
  DisruptionTypeEnum,
  MenuReviewStatusEnum,
  ObservationStatusEnum,
  QCInspectionStatusEnum,
  QCReviewOutcomeEnum,
  RecoveryModeEnum,
  RecoveryStatusEnum,
  RoleEnum,
  SlotEnum,
  SolverStatusEnum,
} from "@/types/api";

/**
 * Format rupiah in Indonesian standard: Rp7.530 (or Rp3.765.100).
 * Rounding is strictly for display; underlying values are preserved.
 */
export function formatIDR(value: number | null | undefined, maximumFractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "Belum tersedia";
  }
  const absFormatted = new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(Math.abs(value));
  const prefix = value < 0 ? "-Rp" : "Rp";
  return `${prefix}${absFormatted}`;
}

export function formatSignedIDR(value: number | null | undefined, maximumFractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "Tidak tersedia";
  }
  if (value === 0) return "Rp0";
  const formatted = formatIDR(Math.abs(value), maximumFractionDigits);
  return value > 0 ? `+${formatted}` : `-${formatted}`;
}

export function formatDecimal(value: number | null | undefined, maximumFractionDigits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(value);
}

export function formatPercent(value: number | null | undefined, maximumFractionDigits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${formatDecimal(value, maximumFractionDigits)}%`;
}

/**
 * Display grams in kg when >= 1000g for kitchen readability, with exact unit.
 */
export function formatWeightFromGrams(grams: number | null | undefined): string {
  if (grams === null || grams === undefined || !Number.isFinite(grams)) {
    return "Belum tersedia";
  }
  if (Math.abs(grams) >= 1000) {
    return `${formatDecimal(grams / 1000, 2)} kg`;
  }
  return `${formatDecimal(grams, 0)} gram`;
}

export function formatDateID(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const dt = new Date(isoDate);
  if (Number.isNaN(dt.getTime())) return isoDate;
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(dt);
}

export function formatDateTimeID(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const dt = new Date(isoDate);
  if (Number.isNaN(dt.getTime())) return isoDate;
  return new Intl.DateTimeFormat("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(dt);
}

const DAY_NAMES = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"];

export function formatDayLabel(dayIndex: number, serviceDate?: string | null): string {
  if (serviceDate) {
    const trimmed = serviceDate.trim();
    const dt = /^\d{4}-\d{2}-\d{2}$/.test(trimmed)
      ? new Date(`${trimmed}T08:00:00+07:00`)
      : new Date(trimmed);
    if (!Number.isNaN(dt.getTime())) {
      const formatted = new Intl.DateTimeFormat("id-ID", {
        timeZone: "Asia/Jakarta",
        weekday: "short",
        day: "numeric",
        month: "short",
      }).format(dt);
      return `Hari ${dayIndex} (${formatted})`;
    }
  }
  if (dayIndex >= 1 && dayIndex <= DAY_NAMES.length) {
    return `Hari ${dayIndex} (${DAY_NAMES[dayIndex - 1]})`;
  }
  return `Hari ${dayIndex}`;
}

export function formatPeriodPhase(phase: string | null | undefined): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} | null {
  if (!phase) return null;
  if (phase === "IN_PROGRESS") return { label: "Minggu Berjalan", tone: "success" };
  if (phase === "UPCOMING") return { label: "Minggu Mendatang", tone: "warning" };
  if (phase === "COMPLETED") return { label: "Periode Selesai", tone: "neutral" };
  return { label: phase, tone: "neutral" };
}

export function formatSlotLabel(slot: SlotEnum | string): string {
  const map: Record<string, string> = {
    staple: "Makanan Pokok",
    protein: "Lauk Protein",
    vegetable: "Sayuran",
    fruit: "Buah",
  };
  return map[slot] ?? slot;
}

export function formatCategoryLabel(category: string): string {
  const map: Record<string, string> = {
    staple: "Bahan Pokok",
    protein: "Sumber Protein",
    vegetable: "Sayuran",
    fruit: "Buah-buahan",
    seasoning: "Bumbu & Minyak",
  };
  return map[category.toLowerCase()] ?? category;
}

export function formatNutrientLabel(key: string): { label: string; unit: string } {
  const map: Record<string, { label: string; unit: string }> = {
    energy_kcal: { label: "Energi", unit: "kkal" },
    protein_g: { label: "Protein", unit: "g" },
    fat_g: { label: "Lemak", unit: "g" },
    carb_g: { label: "Karbohidrat", unit: "g" },
    fiber_g: { label: "Serat", unit: "g" },
    iron_mg: { label: "Zat Besi", unit: "mg" },
  };
  return map[key] ?? { label: key, unit: "" };
}

export function formatMealTypeLabel(mealType: string | undefined): string {
  const map: Record<string, string> = {
    lunch: "Makan Siang",
    breakfast: "Sarapan",
    dinner: "Makan Malam",
  };
  if (!mealType) return "Sesi Makan";
  return map[mealType.toLowerCase()] ?? mealType;
}

export interface StatusPresentation {
  label: string;
  shortLabel: string;
  description: string;
  tone: "success" | "warning" | "critical" | "neutral";
}

export function formatRunStatus(
  status: SolverStatusEnum | undefined,
  validationPassed: boolean | undefined
): StatusPresentation {
  if (!status) {
    return {
      label: "Belum Dihitung",
      shortLabel: "Menunggu",
      description: "Rencana belum dijalankan. Klik Hitung Menu untuk mengevaluasi kelayakan.",
      tone: "neutral",
    };
  }
  if (status === "OPTIMAL" && validationPassed) {
    return {
      label: "Memenuhi Seluruh Batasan (Optimal)",
      shortLabel: "Layak & Optimal",
      description:
        "Kombinasi menu terverifikasi memenuhi anggaran, target gizi simulasi, stok, dan variasi dengan biaya terendah.",
      tone: "success",
    };
  }
  if (status === "FEASIBLE" && validationPassed) {
    return {
      label: "Memenuhi Batasan (Layak, Belum Terbukti Paling Murah)",
      shortLabel: "Layak (Feasible)",
      description:
        "Menu memenuhi seluruh batasan terverifikasi, namun solver berhenti sebelum membuktikan biaya minimum global.",
      tone: "warning",
    };
  }
  if (status === "TIME_LIMIT" && validationPassed) {
    return {
      label: "Layak dengan Batas Waktu",
      shortLabel: "Batas Waktu (Layak)",
      description:
        "Perhitungan mencapai batas waktu dengan solusi sementara yang lolos pemeriksa batasan independen.",
      tone: "warning",
    };
  }
  if (status === "INFEASIBLE") {
    return {
      label: "Belum Ditemukan Kombinasi Menu Layak",
      shortLabel: "Tidak Layak",
      description:
        "Tidak ada susunan menu yang memenuhi seluruh batasan anggaran, gizi, stok, dan alergen sekaligus.",
      tone: "critical",
    };
  }
  if (status === "TIME_LIMIT") {
    return {
      label: "Batas Waktu Tercapai Tanpa Solusi Layak",
      shortLabel: "Batas Waktu",
      description: "Solver belum menemukan kombinasi menu lengkap sebelum batas waktu habis.",
      tone: "critical",
    };
  }
  return {
    label: "Gagal Memproses atau Ditolak Verifier",
    shortLabel: "Gagal Verifikasi",
    description:
      "Terjadi kendala saat menghitung atau hasil tidak lolos pemeriksa batasan independen.",
    tone: "critical",
  };
}

export function formatRoleLabel(role: RoleEnum | string | undefined): string {
  const map: Record<string, string> = {
    KITCHEN_MANAGER: "Kepala Dapur",
    MENU_PLANNER: "Perencana Menu",
    QC_OFFICER: "Petugas QC",
    NUTRITIONIST: "Ahli Gizi",
  };
  if (!role) return "Pengguna";
  return map[role] ?? role;
}

export function formatMenuReviewStatus(status: MenuReviewStatusEnum): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} {
  const map: Record<
    MenuReviewStatusEnum,
    { label: string; tone: "success" | "warning" | "critical" | "neutral" }
  > = {
    DRAFT: { label: "Draft Perencana", tone: "neutral" },
    SUBMITTED: { label: "Menunggu Peninjauan", tone: "warning" },
    APPROVED: { label: "Disetujui Operasional", tone: "success" },
    REVISION_REQUIRED: { label: "Perlu Revisi", tone: "critical" },
  };
  return map[status];
}

export function formatQCStatus(status: QCInspectionStatusEnum): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} {
  const map: Record<
    QCInspectionStatusEnum,
    { label: string; tone: "success" | "warning" | "critical" | "neutral" }
  > = {
    CREATED: { label: "Baru Dibuat (Belum Difoto)", tone: "neutral" },
    AI_ANALYZED: { label: "Selesai Analisis AI (Perlu Tinjauan QC)", tone: "warning" },
    HUMAN_REVIEWED: { label: "Sudah Ditinjau QC (Siap Kirim)", tone: "warning" },
    SUBMITTED: { label: "Menunggu Tinjauan Kepala Dapur", tone: "warning" },
    REVIEWED: { label: "Selesai Ditinjau", tone: "neutral" },
  };
  return map[status];
}

export function formatQCOutcome(outcome: QCReviewOutcomeEnum | null): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} {
  if (!outcome) return { label: "Belum Diputuskan", tone: "neutral" };
  const map: Record<
    QCReviewOutcomeEnum,
    { label: string; tone: "success" | "warning" | "critical" | "neutral" }
  > = {
    // Deliberately neutral/teal phrasing: NEVER claim food is microbiologically safe!
    ACCEPTED_FOR_RECORD: { label: "Diterima untuk Arsip Operasional", tone: "neutral" },
    REVISION_REQUIRED: { label: "Perlu Revisi Catatan QC", tone: "warning" },
    RETAKE_REQUIRED: { label: "Perlu Foto Ulang", tone: "critical" },
  };
  return map[outcome];
}

export function formatObservationStatus(status: ObservationStatusEnum): string {
  const map: Record<ObservationStatusEnum, string> = {
    visible: "Terlihat Jelas",
    uncertain: "Sulit Dipastikan",
    not_visible: "Belum Terlihat",
    needs_review: "Perlu Pemeriksaan Manual",
  };
  return map[status] ?? status;
}

export function formatAuditAction(action: string): string {
  const map: Record<string, string> = {
    "auth.login": "Masuk ke sistem",
    "auth.logout": "Keluar dari sistem",
    "auth.switch_kitchen": "Berpindah dapur aktif",
    "scenario.created": "Membuat skenario menu baru",
    "scenario.next_week_prepared": "Menyiapkan draf rencana minggu berikutnya",
    "scenario.cloned": "Menyalin skenario untuk simulasi",
    "scenario.price_overrides_updated": "Mengubah simulasi harga bahan",
    "scenario.stock_overrides_updated": "Mengubah simulasi stok bahan",
    "optimization_run.executed": "Menjalankan optimasi menu",
    "dataset.imported": "Mengimpor versi dataset CSV baru",
    "menu_review.created": "Membuat draft pengajuan rencana menu",
    "menu_review.submitted": "Mengajukan rencana menu ke Kepala Dapur",
    "menu_review.approved": "Menyetujui rencana menu (operasional)",
    "menu_review.revision_required": "Meminta revisi rencana menu",
    "qc_inspection.created": "Membuat pemeriksaan visual QC",
    "qc_inspection.image_uploaded": "Mengunggah foto sampel makanan",
    "qc_inspection.ai_analyzed": "Menjalankan analisis visual AI",
    "qc_inspection.human_reviewed": "Menyimpan konfirmasi/koreksi petugas QC",
    "qc_inspection.submitted": "Mengirim laporan QC ke Kepala Dapur",
    "qc_inspection.reviewed_accepted_for_record": "Menerima laporan QC untuk arsip operasional",
    "qc_inspection.reviewed_revision_required": "Meminta revisi laporan QC",
    "qc_inspection.reviewed_retake_required": "Meminta pengambilan foto ulang sampel",
    "recovery.event_analyzed": "Menganalisis dampak gangguan & membuat alternatif pemulihan",
    "recovery.candidate_submitted": "Mengajukan rencana menu pengganti pemulihan",
  };
  return map[action] ?? action;
}

export function formatDisruptionTypeLabel(type: DisruptionTypeEnum | string): string {
  const map: Record<string, string> = {
    PRICE_CHANGE: "Perubahan Harga",
    STOCK_SHORTAGE: "Stok Berkurang",
    SUPPLIER_DELAY: "Pengiriman Tertunda",
    PARTIAL_DELIVERY: "Pengiriman Parsial",
    INGREDIENT_UNAVAILABLE: "Bahan Tidak Tersedia",
    SERVING_COUNT_CHANGE: "Perubahan Jumlah Porsi",
    SAFETY_HOLD: "Tahan Keamanan Bahan",
  };
  return map[type] ?? type;
}

export function formatOperationalStatus(status: string | null | undefined): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} {
  const map: Record<string, { label: string; tone: "success" | "warning" | "critical" | "neutral" }> = {
    ACTIVE: { label: "AKTIF BERJALAN", tone: "success" },
    ON_HOLD: { label: "DITAHAN (ON HOLD)", tone: "critical" },
    ACTIVE_ON_HOLD: { label: "DITAHAN (ON HOLD)", tone: "critical" },
    SUPERSEDED: { label: "DIGANTIKAN", tone: "neutral" },
    APPROVED_NOT_ACTIVE: { label: "Disetujui (Belum Aktif)", tone: "warning" },
    DRAFT: { label: "Draft / Menunggu Tinjauan", tone: "warning" },
    NO_PLAN: { label: "Belum Ada Rencana", tone: "neutral" },
  };
  return status ? (map[status] ?? { label: status, tone: "neutral" }) : { label: "Belum Aktif", tone: "neutral" };
}

export function formatIncidentCategoryLabel(category: string): string {
  const map: Record<string, string> = {
    SPOILAGE: "Basi / Pembusukan",
    SUSPECTED_CONTAMINATION: "Dugaan Kontaminasi",
    DAMAGED_PACKAGING: "Kemasan Rusak / Bocor",
    ABNORMAL_ODOR_APPEARANCE: "Bau / Warna Tidak Wajar",
    SUPPLIER_RECALL: "Penarikan Pemasok (Recall)",
    TEMPERATURE_EXCURSION: "Suhu Penyimpanan Menyimpang",
    UNKNOWN_CONDITION: "Kondisi Meragukan",
  };
  return map[category] ?? category;
}

export function formatIncidentStatus(status: string): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} {
  const map: Record<string, { label: string; tone: "success" | "warning" | "critical" | "neutral" }> = {
    REPORTED: { label: "Dilaporkan", tone: "critical" },
    ON_HOLD: { label: "Ditahan (SAFETY HOLD)", tone: "critical" },
    UNDER_REVIEW: { label: "Dalam Pemulihan / Evaluasi", tone: "warning" },
    REJECTED: { label: "Ditolak & Dimusnahkan", tone: "neutral" },
    RESOLVED: { label: "Ditindaklanjuti", tone: "success" },
    CLOSED: { label: "Ditutup", tone: "neutral" },
  };
  return map[status] ?? { label: status, tone: "neutral" };
}

export function formatExposureStatusLabel(status: string): {
  label: string;
  tone: "warning" | "critical" | "neutral";
} {
  if (status === "POTENTIAL_PRODUCTION_EXPOSURE") {
    return { label: "PERINGATAN PAPARAN PRODUKSI", tone: "critical" };
  }
  if (status === "NO_RECORDED_PRODUCTION_EXPOSURE") {
    return { label: "Belum Ada Konsumsi Tercatat", tone: "neutral" };
  }
  return { label: "Paparan Hilir Tidak Diketahui (Verifikasi Manual)", tone: "warning" };
}

export function formatRecoveryModeLabel(mode: RecoveryModeEnum | string | null | undefined): string {
  if (mode === "MIN_DISRUPTION") return "Alternatif A — Minim Perubahan Menu";
  if (mode === "MIN_COST") return "Alternatif B — Biaya Bahan Terendah";
  return mode ?? "Pemulihan Menu";
}

export function formatRecoveryStatus(status: RecoveryStatusEnum | string): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} {
  const map: Record<string, { label: string; tone: "success" | "warning" | "critical" | "neutral" }> = {
    ANALYZED: { label: "Siap Diajukan", tone: "warning" },
    SUBMITTED: { label: "Menunggu Persetujuan Kepala Dapur", tone: "warning" },
    APPROVED: { label: "Disetujui Operasional", tone: "success" },
    REVISION_REQUIRED: { label: "Perlu Hitung Ulang", tone: "critical" },
    INFEASIBLE: { label: "Tidak Ada Alternatif Layak", tone: "critical" },
  };
  return map[status] ?? { label: status, tone: "neutral" };
}
