"use client";

import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  ClipboardCheck,
  Eye,
  History,
  Loader2,
  Plus,
  Send,
  ShieldAlert,
  Sparkles,
  Upload,
} from "lucide-react";

import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { IncidentPanel } from "@/components/incidents/IncidentPanel";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatDateTimeID,
  formatDayLabel,
  formatObservationStatus,
  formatOperationalStatus,
  formatQCOutcome,
  formatQCStatus,
  formatSlotLabel,
} from "@/lib/formatters/indonesian";
import type {
  ComparisonStatusEnum,
  HumanCorrectedComponent,
  ObservationStatusEnum,
  QCInspectionResponse,
  QCReviewOutcomeEnum,
} from "@/types/api";

const PHOTO_TYPES = "image/jpeg,image/png,image/webp";
const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

function comparisonTone(
  status: ComparisonStatusEnum
): "success" | "warning" | "critical" | "neutral" {
  if (status === "visual_match") return "neutral"; // Deliberately neutral/teal—not microbiological safety!
  if (status === "missing_expected") return "critical";
  return "warning";
}

function KitchenQCContent() {
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const { user } = useAuth();
  const { health, healthError, refreshAll } = useWorkspace();
  const kitchenId = user?.active_kitchen_id;
  const detailRef = useRef<HTMLDivElement>(null);
  const createRef = useRef<HTMLElement>(null);

  const initialInspectionParam = searchParams.get("inspection");
  const initialRunParam = searchParams.get("run");
  const initialReviewParam = searchParams.get("review");

  const [selectedInspectionId, setSelectedInspectionId] = useState<string | null>(
    initialInspectionParam
  );
  const [newReviewId, setNewReviewId] = useState<string>(initialReviewParam ?? "");
  const [newDayIndex, setNewDayIndex] = useState<number>(1);
  const [newBatchCode, setNewBatchCode] = useState<string>("");
  const [previousInspection, setPreviousInspection] = useState<QCInspectionResponse | null>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [localPreviewUrl, setLocalPreviewUrl] = useState<string | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [brokenImageId, setBrokenImageId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const [humanDrafts, setHumanDrafts] = useState<HumanCorrectedComponent[]>([]);
  const [humanNotes, setHumanNotes] = useState<string>("");
  const [requestRetake, setRequestRetake] = useState<boolean>(false);
  const [reviewDirty, setReviewDirty] = useState(false);

  const [managerNotes, setManagerNotes] = useState<string>("");
  const [banner, setBanner] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const isQC = user?.active_role === "QC_OFFICER";
  const isManager = user?.active_role === "KITCHEN_MANAGER";

  const inspectionsQuery = useQuery({
    queryKey: ["qc-inspections", kitchenId],
    queryFn: () => apiClient.listQCInspections(),
    enabled: Boolean(user),
  });

  const menuReviewsQuery = useQuery({
    queryKey: ["menu-reviews", kitchenId],
    queryFn: () => apiClient.listMenuReviews(),
    enabled: isQC,
  });

  const approvedPlans = useMemo(() => {
    const filtered = (menuReviewsQuery.data ?? []).filter(
      (m) => m.status === "APPROVED" && m.operational_status !== "SUPERSEDED"
    );
    return filtered.sort((a, b) => {
      const rank = (s?: string | null) =>
        s === "ACTIVE" ? 0 : s === "ON_HOLD" ? 1 : s === "APPROVED_NOT_ACTIVE" ? 2 : 3;
      return rank(a.operational_status) - rank(b.operational_status);
    });
  }, [menuReviewsQuery.data]);
  const selectedPlan = approvedPlans.find((plan) => plan.id === newReviewId);
  const selectedPlanBlockedByHold =
    selectedPlan?.operational_status === "ON_HOLD" ||
    selectedPlan?.operational_status === "APPROVED_NOT_ACTIVE";
  const newRunId = selectedPlan?.run_id;
  const planRunQuery = useQuery({
    queryKey: ["run", kitchenId, newRunId],
    queryFn: () => apiClient.getRun(newRunId!),
    enabled: isQC && Boolean(newRunId),
  });
  const planDays = planRunQuery.data?.days ?? [];
  const effectiveDay = planDays.find((day) => day.day_index === newDayIndex)?.day_index
    ?? planDays[0]?.day_index;

  useEffect(() => {
    if (!menuReviewsQuery.isSuccess || approvedPlans.some((plan) => plan.id === newReviewId)) return;
    const preferred = approvedPlans.find((plan) => plan.run_id === initialRunParam) ?? approvedPlans[0];
    setNewReviewId(preferred?.id ?? "");
  }, [approvedPlans, initialRunParam, menuReviewsQuery.isSuccess, newReviewId]);

  useEffect(() => {
    if (initialInspectionParam) setSelectedInspectionId(initialInspectionParam);
  }, [initialInspectionParam]);

  useEffect(() => {
    if (selectedInspectionId || initialInspectionParam || initialRunParam) return;
    const list = inspectionsQuery.data ?? [];
    const first = isManager ? list.find((item) => item.status === "SUBMITTED") ?? list[0] : list[0];
    if (first) setSelectedInspectionId(first.id);
  }, [initialInspectionParam, initialRunParam, inspectionsQuery.data, isManager, selectedInspectionId]);

  const activeInspectionQuery = useQuery({
    queryKey: ["qc-inspection", kitchenId, selectedInspectionId],
    queryFn: () => apiClient.getQCInspection(selectedInspectionId!),
    enabled: Boolean(selectedInspectionId),
  });

  const activeInspection: QCInspectionResponse | undefined = activeInspectionQuery.data;

  const latestAI = activeInspection?.ai_observations.at(-1);
  const latestHuman = activeInspection?.human_reviews.at(-1);
  const latestImage = activeInspection?.images.at(-1);
  const currentAI = latestAI && latestImage?.id === latestAI.image_id ? latestAI : undefined;
  const currentHuman = latestHuman && currentAI?.id === latestHuman.ai_observation_id ? latestHuman : undefined;

  useEffect(() => {
    setSelectedFile(null);
    setLocalPreviewUrl(null);
    setPhotoError(null);
    setBrokenImageId(null);
    setManagerNotes("");
  }, [selectedInspectionId]);

  useEffect(() => {
    if (!activeInspection) return;
    setReviewDirty(false);
    if (currentHuman) {
      setHumanDrafts(currentHuman.corrected_components);
      setHumanNotes(currentHuman.notes ?? "");
      setRequestRetake(currentHuman.request_retake);
      return;
    }
    const defaults: HumanCorrectedComponent[] = currentAI ? activeInspection.expected_menu.map((slot) => {
      const finding = currentAI.comparison_findings.find((item) => item.slot === slot.slot);
      const statuses: Partial<Record<ComparisonStatusEnum, ObservationStatusEnum>> = {
        visual_match: "visible", missing_expected: "not_visible", uncertain: "uncertain",
      };
      return {
        slot: slot.slot,
        confirmed_status: finding ? statuses[finding.status] ?? "needs_review" : "needs_review",
        observed_food_name: finding?.matched_observation ?? "",
        officer_note: "",
      };
    }) : [];
    setHumanDrafts(defaults);
    setHumanNotes(activeInspection.qc_notes ?? "");
    setRequestRetake(false);
    // Match a new analysis or persisted correction. A background refetch must not erase local input.
  }, [activeInspection?.id, currentAI?.id, currentHuman?.id]);

  useEffect(() => {
    return () => {
      if (localPreviewUrl) URL.revokeObjectURL(localPreviewUrl);
    };
  }, [localPreviewUrl]);

  const invalidateQC = (id?: string) => {
    qc.invalidateQueries({ queryKey: ["qc-inspections"] });
    qc.invalidateQueries({ queryKey: ["qc-summary"] });
    qc.invalidateQueries({ queryKey: ["manager-summary"] });
    if (id) qc.invalidateQueries({ queryKey: ["qc-inspection", kitchenId, id] });
  };
  const cacheInspection = (updated: QCInspectionResponse) => {
    qc.setQueryData(["qc-inspection", kitchenId, updated.id], updated);
    invalidateQC(updated.id);
  };

  const createMutation = useMutation({
    mutationFn: () => {
      if (!newRunId || !effectiveDay) throw new Error("Pilih rencana menu dan hari.");
      return apiClient.createQCInspection({
        run_id: newRunId,
        menu_review_id: newReviewId,
        day_index: effectiveDay,
        meal_batch_code: newBatchCode.trim() || undefined,
        previous_inspection_id: previousInspection?.id,
      });
    },
    onSuccess: (created) => {
      cacheInspection(created);
      setBanner({ type: "ok", text: "Pemeriksaan baru dibuat. Silakan ambil atau unggah foto sampel." });
      setSelectedInspectionId(created.id);
      setNewBatchCode("");
      setPreviousInspection(null);
      requestAnimationFrame(() => detailRef.current?.focus());
    },
    onError: (err) => {
      setBanner({
        type: "err",
        text: err instanceof ApiError ? err.message : "Gagal membuat pemeriksaan baru.",
      });
    },
  });

  const uploadMutation = useMutation({
    mutationFn: ({ inspectionId, file }: { inspectionId: string; file: File }) =>
      apiClient.uploadQCImage(inspectionId, file),
    onSuccess: async (_image, { inspectionId }) => {
      setSelectedFile(null);
      setLocalPreviewUrl(null);
      invalidateQC();
      await qc.invalidateQueries({ queryKey: ["qc-inspection", kitchenId, inspectionId] });
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: ({ inspectionId, imageId }: { inspectionId: string; imageId: string }) =>
      apiClient.analyzeQCInspection(inspectionId, imageId),
    onSuccess: (updated) => {
      cacheInspection(updated);
      requestAnimationFrame(() => document.getElementById("qc-comparison")?.focus());
    },
  });

  const saveHumanMutation = useMutation({
    mutationFn: () =>
      apiClient.patchQCObservations(selectedInspectionId!, {
        corrected_components: humanDrafts.map((component) => ({
          ...component,
          observed_food_name: component.observed_food_name.trim() || "Tidak teridentifikasi",
        })),
        notes: humanNotes.trim() || undefined,
        request_retake: requestRetake,
        ai_observation_id: currentAI?.id,
      }),
    onSuccess: (updated) => {
      setBanner({
        type: "ok",
        text: "Konfirmasi dan koreksi Petugas QC berhasil disimpan. Observasi AI asli tetap tersimpan terpisah.",
      });
      cacheInspection(updated);
    },
    onError: (err) => {
      setBanner({
        type: "err",
        text: err instanceof ApiError ? err.message : "Gagal menyimpan tinjauan Petugas QC.",
      });
    },
  });

  const submitQCMutation = useMutation({
    mutationFn: () => apiClient.submitQCInspection(selectedInspectionId!),
    onSuccess: (updated) => {
      setBanner({
        type: "ok",
        text: "Laporan pemeriksaan QC berhasil dikirim ke Kepala Dapur untuk ditinjau.",
      });
      cacheInspection(updated);
    },
    onError: (err) => {
      setBanner({
        type: "err",
        text: err instanceof ApiError ? err.message : "Gagal mengirim pemeriksaan QC.",
      });
    },
  });

  const managerReviewMutation = useMutation({
    mutationFn: (outcome: QCReviewOutcomeEnum) =>
      apiClient.reviewQCInspection(selectedInspectionId!, outcome, managerNotes.trim() || undefined),
    onSuccess: (updated) => {
      setManagerNotes("");
      setBanner({
        type: "ok",
        text: `Keputusan Kepala Dapur (${formatQCOutcome(updated.review_outcome).label}) telah dicatat pada riwayat audit.`,
      });
      cacheInspection(updated);
    },
    onError: (err) => {
      setBanner({
        type: "err",
        text: err instanceof ApiError ? err.message : "Gagal menyimpan keputusan Kepala Dapur.",
      });
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    e.target.value = "";
    if (!f) return;
    uploadMutation.reset();
    analyzeMutation.reset();
    if (f.size > MAX_PHOTO_BYTES || (f.type && !PHOTO_TYPES.split(",").includes(f.type))) {
      setPhotoError("Pilih foto JPEG, PNG, atau WebP dengan ukuran maksimal 5 MB.");
      setSelectedFile(null);
      setLocalPreviewUrl(null);
      return;
    }
    setPhotoError(null);
    setSelectedFile(f);
    setLocalPreviewUrl(URL.createObjectURL(f));
    setBanner(null);
  };

  if (inspectionsQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Pemeriksaan Menu AI" subtitle="Memuat data pemeriksaan visual dapur..." />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (inspectionsQuery.error) {
    return (
      <div className="space-y-6">
        <PageHeader title="Pemeriksaan Menu AI" />
        <ErrorState
          message={inspectionsQuery.error.message}
          onRetry={() => inspectionsQuery.refetch()}
        />
      </div>
    );
  }

  const inspections = inspectionsQuery.data ?? [];
  const isLockedForQC =
    activeInspection?.status === "SUBMITTED" || activeInspection?.status === "REVIEWED";
  const provider = health?.vision_provider;
  const canAnalyze = provider?.configured === true && !healthError;
  const isWorking = uploadMutation.isPending || analyzeMutation.isPending
    || saveHumanMutation.isPending || submitQCMutation.isPending || managerReviewMutation.isPending;
  const canSubmit = activeInspection?.status === "HUMAN_REVIEWED" && Boolean(currentHuman)
    && !reviewDirty && !selectedFile && !isWorking;
  const hasMissingFoodName = humanDrafts.some((item) => item.confirmed_status === "visible" && !item.observed_food_name.trim());
  const photoExpired = Boolean(latestImage?.expires_at && Date.parse(latestImage.expires_at) <= Date.now());
  const detailUnavailable = activeInspectionQuery.isError && !activeInspection;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pemeriksaan Menu AI"
        subtitle="Bandingkan foto sampel dengan rencana menu dapur. Petugas QC mengonfirmasi temuan sebelum mengirim laporan."
        badges={
          <div className="flex flex-wrap gap-2">
            <DatasetSimulationNotice compact simulationOnly />
            {provider && (
              <StatusBadge
                tone={provider.is_live_ai ? "success" : "warning"}
                label={
                  provider.is_live_ai
                    ? "Vision AI Terkonfigurasi"
                    : provider.configured
                    ? "Mode Uji Deterministik"
                    : "Vision AI Belum Dikonfigurasi"
                }
              />
            )}
          </div>
        }
      />

      {isQC && healthError && (
        <ErrorState title="Status Vision AI tidak tersedia" message={healthError.message} onRetry={refreshAll} />
      )}
      {isQC && provider && !provider.configured && !healthError && (
        <p role="status" className="rounded-xl border border-[#F5D59B] bg-[#FEF6E7] p-4 text-sm text-[#8A5300]">
          <strong>Konfigurasi Vision AI diperlukan.</strong> Hubungi administrator agar analisis foto dapat dijalankan. Anda masih bisa membuka rencana dan menyimpan foto.
        </p>
      )}
      {/* Mandatory Food Safety & Visual Scope Disclaimer */}
      <div className="flex items-start gap-2.5 rounded-2xl border border-[#DCE6DE] bg-white p-4 text-xs leading-relaxed text-[#4A6170]">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
        <div>
          <strong className="text-[#16354A]">Batasan Pemeriksaan Visual:</strong> Fitur ini hanya
          membantu pencocokan visual komponen menu (makanan pokok, lauk protein, sayur, buah) untuk
          dokumentasi internal. Analisis foto <strong>tidak</strong> mengukur berat/gizi/suhu dan{" "}
          <strong>tidak</strong> menyatakan keamanan mikrobiologis atau sertifikasi BGN/SLHS/halal.
        </div>
      </div>

      {banner && (
        <div
          role={banner.type === "err" ? "alert" : "status"}
          className={`flex items-start gap-2.5 rounded-xl border p-3.5 text-sm font-medium ${
            banner.type === "ok"
              ? "border-[#B5DFDA] bg-[#EBF6F5] text-[#0F766E]"
              : "border-[#F5C2C2] bg-[#FEF0F0] text-[#991B1B]"
          }`}
        >
          {banner.type === "ok" ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          )}
          <span>{banner.text}</span>
        </div>
      )}

      <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: Create New Inspection (QC only) + History List */}
        <div className="min-w-0 space-y-5 lg:col-span-4">
          {isQC && (
            <section ref={createRef} tabIndex={-1} className="scroll-mt-20 rounded-2xl border border-[#DCE6DE] bg-white p-4 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
              <div className="flex items-center gap-2 border-b border-[#EEF3EE] pb-3">
                <Plus className="h-4 w-4 text-[#0F766E]" aria-hidden="true" />
                <h2 className="text-sm font-bold text-[#16354A]">Buat Pemeriksaan Baru</h2>
              </div>

              {menuReviewsQuery.isLoading ? <p className="mt-3 text-sm text-[#647A87]">Memuat rencana menu…</p>
                : menuReviewsQuery.error ? <div className="mt-3"><ErrorState title="Rencana menu gagal dimuat" message={menuReviewsQuery.error.message} onRetry={() => void menuReviewsQuery.refetch()} /></div>
                : approvedPlans.length === 0 ? <p className="mt-3 text-sm leading-relaxed text-[#647A87]">Belum ada rencana yang disetujui. Pemeriksaan dapat dimulai setelah Kepala Dapur menyetujui rencana.</p>
                : <div className="mt-3 space-y-3">
                {previousInspection && (
                  <div className="rounded-xl border border-[#F5D59B] bg-[#FEF6E7] p-3 text-sm text-[#8A5300]">
                    <p>Tindak lanjut pemeriksaan {formatDayLabel(previousInspection.day_index)}.</p>
                    <button type="button" onClick={() => setPreviousInspection(null)} className="mt-1 min-h-[44px] font-semibold underline">Batalkan tindak lanjut</button>
                  </div>
                )}
                <div>
                  <label htmlFor="qc-plan-select" className="block text-xs font-semibold text-[#4A6170]">
                    Rencana Menu Acuan
                  </label>
                  <select
                    id="qc-plan-select"
                    value={newReviewId}
                    disabled={Boolean(previousInspection)}
                    onChange={(e) => {
                      setNewReviewId(e.target.value);
                      setNewDayIndex(1);
                    }}
                    className="mt-1 min-h-[44px] w-full min-w-0 rounded-xl border border-[#DCE6DE] bg-white px-3 text-base text-[#16354A] sm:text-sm"
                  >
                    <option value="" disabled>Pilih rencana yang disetujui</option>
                    {approvedPlans.map((plan) => {
                      const tag = plan.operational_status
                        ? ` [${formatOperationalStatus(plan.operational_status).label}]`
                        : "";
                      return (
                        <option key={plan.id} value={plan.id}>
                          {plan.title} · v{plan.version_number}{tag}
                        </option>
                      );
                    })}
                  </select>
                </div>

                {selectedPlanBlockedByHold && selectedPlan && (
                  <div
                    role="alert"
                    className="rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-3 text-xs text-[#991B1B]"
                  >
                    <p className="font-bold">
                      {selectedPlan.operational_status === "ON_HOLD"
                        ? "Rencana Dipilih Sedang DITAHAN (ON HOLD)"
                        : "Rencana Belum Diaktifkan Operasional"}
                    </p>
                    <p className="mt-0.5">
                      {selectedPlan.hold_reason ??
                        "Pemeriksaan QC rutin diblokir hingga Kepala Dapur mengaktifkan rencana operasional aktif."}
                    </p>
                  </div>
                )}

                {planRunQuery.error && <ErrorState title="Hari menu gagal dimuat" message={planRunQuery.error.message} onRetry={() => void planRunQuery.refetch()} />}
                <div className="grid min-w-0 grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="qc-day-select" className="block text-xs font-semibold text-[#4A6170]">
                      Hari Menu
                    </label>
                    <select
                      id="qc-day-select"
                      value={effectiveDay ?? ""}
                      disabled={!effectiveDay || Boolean(previousInspection)}
                      onChange={(e) => setNewDayIndex(Number(e.target.value))}
                      className="mt-1 min-h-[44px] w-full min-w-0 rounded-xl border border-[#DCE6DE] bg-white px-3 text-base text-[#16354A] sm:text-sm"
                    >
                      {!effectiveDay && <option value="">{planRunQuery.isLoading ? "Memuat…" : "Pilih hari"}</option>}
                      {planDays.map((day) => (
                        <option key={day.day_index} value={day.day_index}>
                          {formatDayLabel(day.day_index)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="qc-batch-input" className="block text-xs font-semibold text-[#4A6170]">
                      Kode Batch (Opsional)
                    </label>
                    <input
                      id="qc-batch-input"
                      type="text"
                      maxLength={64}
                      value={newBatchCode}
                      onChange={(e) => setNewBatchCode(e.target.value)}
                      placeholder="Mis. B-H1-01"
                      className="mt-1 min-h-[44px] w-full min-w-0 rounded-xl border border-[#DCE6DE] bg-white px-3 text-base text-[#16354A] sm:text-sm"
                    />
                  </div>
                </div>

                <button
                  type="button"
                  disabled={
                    !newRunId ||
                    !effectiveDay ||
                    selectedPlanBlockedByHold ||
                    createMutation.isPending ||
                    isWorking
                  }
                  onClick={() => createMutation.mutate()}
                  className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {createMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <Camera className="h-4 w-4" aria-hidden="true" />
                  )}
                  <span>{previousInspection ? "Mulai Pemeriksaan Tindak Lanjut" : "Mulai Pemeriksaan"}</span>
                </button>
              </div>}
            </section>
          )}

          {/* Inspection History */}
          <section className="rounded-2xl border border-[#DCE6DE] bg-white p-4 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
            <div className="flex items-center justify-between border-b border-[#EEF3EE] pb-3">
              <div className="flex min-w-0 items-center gap-2">
                <History className="h-4 w-4 text-[#0F766E]" aria-hidden="true" />
                <h2 className="text-sm font-bold text-[#16354A]">
                  Riwayat Pemeriksaan ({inspections.length})
                </h2>
              </div>
              {inspections.length > 0 && (
                <button type="button" className="min-h-[44px] shrink-0 px-2 text-xs font-semibold text-[#0F766E] lg:hidden"
                  onClick={() => setShowHistory((open) => !open)} aria-expanded={showHistory} aria-controls="qc-inspection-history">
                  {showHistory ? "Tutup" : "Lihat"}
                </button>
              )}
            </div>

            {inspections.length === 0 ? (
              <p className="py-6 text-center text-xs text-[#647A87]">
                Belum ada pemeriksaan visual untuk dapur ini.
              </p>
            ) : (
              <div id="qc-inspection-history" className={`mt-3 max-h-[460px] space-y-2 overflow-y-auto ${showHistory ? "block" : "hidden lg:block"}`}>
                {inspections.map((insp) => {
                  const active = insp.id === selectedInspectionId;
                  const st = formatQCStatus(insp.status);
                  return (
                    <button
                      key={insp.id}
                      type="button"
                      disabled={isWorking}
                      aria-pressed={active}
                      onClick={() => {
                        uploadMutation.reset();
                        analyzeMutation.reset();
                        setSelectedInspectionId(insp.id);
                        setBanner(null);
                        setShowHistory(false);
                        requestAnimationFrame(() => detailRef.current?.focus());
                      }}
                      className={`w-full rounded-xl border p-3 text-left transition-colors ${
                        active
                          ? "border-[#0F766E] bg-[#EBF6F5]/60"
                          : "border-[#EEF3EE] bg-white hover:bg-[#F5F8F5]"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-bold text-[#16354A]">
                          {insp.scenario_name}
                        </span>
                        <span className="shrink-0 text-[11px] font-semibold text-[#0F766E]">
                          Hari {insp.day_index}
                        </span>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <StatusBadge tone={st.tone} label={st.label} />
                        {insp.review_outcome && (
                          <StatusBadge
                            tone={formatQCOutcome(insp.review_outcome).tone}
                            label={formatQCOutcome(insp.review_outcome).label}
                          />
                        )}
                      </div>
                      <p className="mt-1 text-[11px] text-[#647A87]">
                        {insp.created_by_name} • {formatDateTimeID(insp.updated_at)}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        {/* Right Column: Active Inspection Workspace */}
        <div ref={detailRef} tabIndex={-1} className="min-w-0 scroll-mt-20 space-y-5 lg:col-span-8">
          {detailUnavailable ? (
            <ErrorState title="Pemeriksaan gagal dimuat" message={activeInspectionQuery.error.message}
              onRetry={() => void activeInspectionQuery.refetch()} />
          ) : activeInspectionQuery.isLoading ? <LoadingSkeleton rows={2} /> : !activeInspection ? (
            <EmptyState
              title="Pilih atau Mulai Pemeriksaan Visual"
              description={
                isQC
                  ? "Gunakan panel 'Buat Pemeriksaan Baru' untuk memilih rencana menu dan hari, lalu ambil foto sampel nampan."
                   : "Pilih catatan dalam Riwayat Pemeriksaan untuk melihat foto, temuan AI, dan koreksi petugas QC."
              }
            />
          ) : (
            <>
              {/* Header + Expected Menu Card */}
              <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#EEF3EE] pb-4">
                  <div>
                    <h2 className="break-words text-base font-bold text-[#16354A]">
                      {activeInspection.scenario_name} — {formatDayLabel(activeInspection.day_index)}
                    </h2>
                    <p className="mt-0.5 text-xs text-[#647A87]">
                      Dibuat oleh {activeInspection.created_by_name} •{" "}
                      {formatDateTimeID(activeInspection.created_at)}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <StatusBadge
                      tone={formatQCStatus(activeInspection.status).tone}
                      label={formatQCStatus(activeInspection.status).label}
                    />
                    {activeInspection.review_outcome && (
                      <StatusBadge
                        tone={formatQCOutcome(activeInspection.review_outcome).tone}
                        label={formatQCOutcome(activeInspection.review_outcome).label}
                      />
                    )}
                  </div>
                </div>

                <div className="mt-4">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-[#647A87]">
                    Komponen Menu Terencana (Acuan)
                  </h3>
                  <div className="mt-2 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    {activeInspection.expected_menu.map((slot) => (
                      <div
                        key={slot.slot}
                        className="rounded-xl border border-[#EEF3EE] bg-[#F5F8F5] p-3"
                      >
                        <span className="block text-[11px] font-semibold text-[#0F766E]">
                          {formatSlotLabel(slot.slot)}
                        </span>
                        <span className="mt-0.5 block text-sm font-bold text-[#16354A]">
                          {slot.recipe_name}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* Photo Capture / Upload & Preview */}
              <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EEF3EE] pb-3">
                  <div className="flex items-center gap-2">
                    <Camera className="h-4 w-4 text-[#0F766E]" aria-hidden="true" />
                    <h3 className="text-sm font-bold text-[#16354A]">
                      Foto Sampel Nampan ({activeInspection.images.length})
                    </h3>
                  </div>
                  {latestImage && (
                    <span className="text-[11px] text-[#647A87]">
                      {latestImage.width_px}×{latestImage.height_px}px • EXIF dihapus otomatis
                    </span>
                  )}
                </div>

                <div className="mt-4 grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-2">
                  {/* Stored / Preview Image */}
                  <div className="flex min-h-[200px] flex-col items-center justify-center overflow-hidden rounded-xl border border-dashed border-[#C7D6CB] bg-[#F5F8F5] p-3">
                    {localPreviewUrl ? (
                      <img
                        src={localPreviewUrl}
                        alt="Pratinjau foto sampel yang akan diunggah"
                        className="max-h-64 w-auto max-w-full rounded-lg object-contain"
                      />
                    ) : latestImage && (photoExpired || latestImage.id === brokenImageId) ? (
                      <div className="text-center text-sm text-[#647A87]">
                        {photoExpired ? "Masa penyimpanan foto berakhir. Catatan pemeriksaan masih tersedia." : "Foto belum dapat dimuat."}
                        {!photoExpired && <button type="button" onClick={() => setBrokenImageId(null)}
                          className="mx-auto mt-2 block min-h-[44px] font-semibold text-[#0F766E] underline">Muat ulang foto</button>}
                      </div>
                    ) : latestImage ? (
                      <img
                        src={apiClient.getProtectedImageUrl(latestImage.image_url)}
                        crossOrigin="use-credentials"
                        alt={`Foto sampel ${activeInspection.scenario_name}`}
                        onError={() => setBrokenImageId(latestImage.id)}
                        className="max-h-64 w-auto max-w-full rounded-lg object-contain"
                      />
                    ) : (
                      <div className="text-center text-xs text-[#647A87]">
                        <Camera className="mx-auto h-8 w-8 text-[#9BB0A5]" aria-hidden="true" />
                        <p className="mt-2">Belum ada foto sampel diunggah.</p>
                      </div>
                    )}
                  </div>

                  {/* Upload & Analyze Actions (QC Officer only while unlocked) */}
                  <div className="flex min-w-0 flex-col justify-between gap-4">
                    {isQC && !isLockedForQC ? (
                      <div className="space-y-3">
                        <p id="qc-photo-requirements" className="text-xs text-[#4A6170]">
                          JPEG, PNG, atau WebP, maksimal 5 MB.
                        </p>
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                          <label className="flex min-h-[48px] cursor-pointer items-center justify-center gap-2 rounded-xl border border-[#B5DFDA] bg-[#EBF6F5] px-3 text-sm font-semibold text-[#0F766E] focus-within:ring-2 focus-within:ring-[#0F766E]">
                            <Camera className="h-4 w-4 shrink-0" aria-hidden="true" />
                            Ambil Foto
                            <input id="qc-photo-camera" type="file" accept={PHOTO_TYPES} capture="environment"
                              aria-describedby="qc-photo-requirements" disabled={isWorking}
                              onChange={handleFileChange} className="sr-only" />
                          </label>
                          <label className="flex min-h-[48px] cursor-pointer items-center justify-center gap-2 rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm font-semibold text-[#16354A] focus-within:ring-2 focus-within:ring-[#0F766E]">
                            <Upload className="h-4 w-4 shrink-0" aria-hidden="true" />
                            Pilih dari Galeri
                            <input id="qc-photo-file" type="file" accept={PHOTO_TYPES}
                              aria-describedby="qc-photo-requirements" disabled={isWorking}
                              onChange={handleFileChange} className="sr-only" />
                          </label>
                        </div>
                        {selectedFile && (
                          <p className="break-all text-xs text-[#4A6170]" role="status">Siap diunggah • {selectedFile.name}</p>
                        )}
                        {photoError && <p role="alert" className="text-sm text-[#991B1B]">{photoError}</p>}
                        {uploadMutation.error && <p role="alert" className="text-sm text-[#991B1B]">{uploadMutation.error.message}</p>}
                        {analyzeMutation.error && <p role="alert" className="text-sm text-[#991B1B]">{analyzeMutation.error.message}</p>}
                        {uploadMutation.isSuccess && !selectedFile && (
                          <p role="status" className="text-sm text-[#0F766E]">Foto tersimpan.</p>
                        )}
                        <div className="grid gap-2 sm:flex sm:flex-wrap">
                          <button
                            type="button"
                            disabled={!selectedFile || isWorking}
                            onClick={() => selectedFile && uploadMutation.mutate({ inspectionId: activeInspection.id, file: selectedFile })}
                            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-[#0F766E] bg-white px-4 py-2 text-sm font-semibold text-[#0F766E] hover:bg-[#EBF6F5] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {uploadMutation.isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                            ) : (
                              <Upload className="h-4 w-4" aria-hidden="true" />
                            )}
                            <span>{uploadMutation.isError ? "Coba Unggah Lagi" : "Unggah Foto"}</span>
                          </button>

                          <button
                            type="button"
                            disabled={!latestImage || Boolean(selectedFile) || !canAnalyze || isWorking || photoExpired || detailUnavailable}
                            onClick={() => latestImage && analyzeMutation.mutate({ inspectionId: activeInspection.id, imageId: latestImage.id })}
                            className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {analyzeMutation.isPending ? (
                              <>
                                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                                <span>Memeriksa foto...</span>
                              </>
                            ) : (
                              <>
                                <Sparkles className="h-4 w-4" aria-hidden="true" />
                                <span>{analyzeMutation.isError ? "Coba Analisis Lagi" : "Periksa dengan AI"}</span>
                              </>
                            )}
                          </button>
                        </div>
                        {!canAnalyze && (
                          <p className="text-xs text-[#8A5300]">{provider?.configured === false ? "Analisis menunggu konfigurasi Vision AI." : "Analisis menunggu status layanan Vision AI."}</p>
                        )}
                      </div>
                    ) : (
                      <div className="rounded-xl border border-[#EEF3EE] bg-[#F5F8F5] p-3 text-xs text-[#4A6170]">
                        {isLockedForQC
                          ? "Pemeriksaan sudah dikirim/ditinjau sehingga bukti foto dan observasi AI terkunci (immutable)."
                          : "Hanya Petugas QC yang dapat mengunggah foto sampel dan menjalankan pemeriksaan Vision AI."}
                      </div>
                    )}

                    <p className="text-[11px] leading-relaxed text-[#647A87]">
                      Privasi & Keamanan: Hindari memotret wajah atau identitas pribadi. Foto
                      disimpan pada penyimpanan privat terbatas untuk dapur Anda dan metadata EXIF
                      dihapus otomatis.
                    </p>
                  </div>
                </div>
              </section>

              {/* AI Observations & Grounded Comparison (Immutable Original Record) */}
              {latestAI && (
                <section id="qc-comparison" tabIndex={-1} className="scroll-mt-20 rounded-2xl border border-[#DCE6DE] bg-white p-4 shadow-[0_1px_2px_rgba(22,53,74,0.04)] sm:p-5">
                  <div className="flex flex-wrap items-start justify-between gap-2 border-b border-[#EEF3EE] pb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <Eye className="h-4 w-4 text-[#0F766E]" aria-hidden="true" />
                        <h3 className="text-sm font-bold text-[#16354A]">
                          Perbandingan Foto dan Rencana Menu
                        </h3>
                      </div>
                      <p className="mt-0.5 text-[11px] text-[#647A87]">
                        Waktu analisis: {formatDateTimeID(latestAI.created_at)} ({latestAI.latency_ms} ms)
                      </p>
                    </div>
                    <StatusBadge
                      tone={latestAI.is_live_ai ? "success" : "warning"}
                      label={
                        latestAI.is_live_ai
                          ? "Analisis AI Live"
                          : "Mode Simulasi / Test Provider (Non-Live)"
                      }
                    />
                  </div>

                  {!latestAI.is_live_ai && (
                    <div className="mt-3 rounded-xl border border-[#F5D59B] bg-[#FEF6E7] p-3 text-xs text-[#8A5300]">
                      Hasil ini berasal dari <strong>mode uji deterministik</strong> yang diaktifkan untuk pengujian.
                    </div>
                  )}
                  {!currentAI && (
                    <p className="mt-3 rounded-xl bg-[#FEF6E7] p-3 text-sm text-[#8A5300]">
                      Temuan di bawah berasal dari foto sebelumnya. Jalankan analisis untuk foto terbaru.
                    </p>
                  )}

                  {/* Grounded Comparison Findings */}
                  <div className="mt-4 space-y-2.5">
                    {latestAI.comparison_findings.map((finding) => (
                      <div
                        key={finding.slot}
                        className="rounded-xl border border-[#EEF3EE] bg-[#F5F8F5]/70 p-3.5"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-sm font-bold text-[#16354A]">{formatSlotLabel(finding.slot)}</span>
                          <StatusBadge
                            tone={comparisonTone(finding.status)}
                            label={finding.finding_label}
                          />
                        </div>
                        <dl className="mt-2 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
                          <div className="min-w-0">
                            <dt className="text-xs font-semibold text-[#647A87]">Pada rencana</dt>
                            <dd className="break-words">{finding.expected_recipe_name}</dd>
                          </div>
                          <div className="min-w-0">
                            <dt className="text-xs font-semibold text-[#647A87]">Teramati pada foto</dt>
                            <dd className="break-words">{finding.matched_observation || "Belum teridentifikasi"}</dd>
                          </div>
                        </dl>
                        <p className="mt-1 text-xs leading-relaxed text-[#4A6170]">
                          {finding.explanation}
                        </p>
                      </div>
                    ))}
                  </div>

                  {latestAI.validated_output.limitations.length > 0 && (
                    <div className="mt-4 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3 text-[11px] text-[#4A6170]">
                      <p className="font-semibold text-[#16354A]">Keterbatasan Pengamatan Visual:</p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4">
                        {latestAI.validated_output.limitations.map((lim, idx) => (
                          <li key={idx}>{lim}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </section>
              )}

              {/* Human-in-the-Loop Confirmation & Correction (QC Officer) */}
              {currentAI && isQC && !isLockedForQC && (
                <section className="rounded-2xl border border-[#B5DFDA] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
                  <div className="border-b border-[#EEF3EE] pb-3">
                    <h3 className="text-sm font-bold text-[#16354A]">
                      Konfirmasi & Koreksi Petugas QC (Wajib Sebelum Kirim)
                    </h3>
                    <p className="mt-0.5 text-xs text-[#647A87]">
                      Koreksi Anda disimpan terpisah tanpa mengubah catatan observasi AI asli.
                    </p>
                  </div>

                  <div className="mt-4 space-y-3">
                    {humanDrafts.map((item, idx) => (
                      <div
                        key={item.slot}
                        className="grid grid-cols-1 gap-2.5 rounded-xl border border-[#EEF3EE] bg-[#F5F8F5]/60 p-3 sm:grid-cols-12"
                      >
                        <div className="sm:col-span-3">
                          <span className="block text-xs font-bold text-[#16354A]">
                            {formatSlotLabel(item.slot)}
                          </span>
                          <label htmlFor={`qc-status-${item.slot}`} className="sr-only">
                            Status konfirmasi {formatSlotLabel(item.slot)}
                          </label>
                          <select
                            id={`qc-status-${item.slot}`}
                            value={item.confirmed_status}
                            onChange={(e) => {
                              const next = [...humanDrafts];
                              next[idx] = {
                                ...item,
                                confirmed_status: e.target.value as ObservationStatusEnum,
                              };
                              setHumanDrafts(next);
                              setReviewDirty(true);
                            }}
                            className="mt-1 min-h-[44px] w-full rounded-lg border border-[#DCE6DE] bg-white px-2 text-base text-[#16354A] sm:text-sm"
                          >
                            <option value="visible">Terlihat Jelas</option>
                            <option value="uncertain">Sulit Dipastikan</option>
                            <option value="not_visible">Belum Terlihat</option>
                            <option value="needs_review">Perlu Pemeriksaan Manual</option>
                          </select>
                        </div>

                        <div className="sm:col-span-5">
                          <label
                            htmlFor={`qc-food-${item.slot}`}
                            className="block text-[11px] font-semibold text-[#4A6170]"
                          >
                            Komponen Teramati (Koreksi Petugas)
                          </label>
                          <input
                            id={`qc-food-${item.slot}`}
                            type="text"
                            value={item.observed_food_name}
                            maxLength={160}
                            aria-invalid={item.confirmed_status === "visible" && !item.observed_food_name.trim()}
                            onChange={(e) => {
                              const next = [...humanDrafts];
                              next[idx] = { ...item, observed_food_name: e.target.value };
                              setHumanDrafts(next);
                              setReviewDirty(true);
                            }}
                            className="mt-1 min-h-[44px] w-full rounded-lg border border-[#DCE6DE] bg-white px-2.5 text-base text-[#16354A] sm:text-sm"
                          />
                        </div>

                        <div className="sm:col-span-4">
                          <label
                            htmlFor={`qc-note-${item.slot}`}
                            className="block text-[11px] font-semibold text-[#4A6170]"
                          >
                            Catatan Slot (Opsional)
                          </label>
                          <input
                            id={`qc-note-${item.slot}`}
                            type="text"
                            value={item.officer_note ?? ""}
                            maxLength={500}
                            onChange={(e) => {
                              const next = [...humanDrafts];
                              next[idx] = { ...item, officer_note: e.target.value };
                              setHumanDrafts(next);
                              setReviewDirty(true);
                            }}
                            placeholder="Mis. diletakkan terpisah"
                            className="mt-1 min-h-[44px] w-full rounded-lg border border-[#DCE6DE] bg-white px-2.5 text-base text-[#16354A] sm:text-sm"
                          />
                        </div>
                      </div>
                    ))}

                    <div>
                      <label htmlFor="qc-general-notes" className="block text-xs font-semibold text-[#4A6170]">
                        Catatan Umum Pemeriksaan QC
                      </label>
                      <textarea
                        id="qc-general-notes"
                        rows={2}
                        value={humanNotes}
                        maxLength={2000}
                        onChange={(e) => { setHumanNotes(e.target.value); setReviewDirty(true); }}
                        placeholder="Tambahkan keterangan kondisi pencahayaan, buah terpisah, atau catatan lain..."
                        className="mt-1 w-full rounded-xl border border-[#DCE6DE] bg-white p-3 text-base text-[#16354A] sm:text-sm"
                      />
                    </div>

                    <label className="inline-flex min-h-[44px] items-center gap-2 text-sm text-[#4A6170]">
                      <input
                        type="checkbox"
                        checked={requestRetake}
                        onChange={(e) => { setRequestRetake(e.target.checked); setReviewDirty(true); }}
                        className="h-5 w-5 shrink-0 rounded border-[#DCE6DE] text-[#0F766E]"
                      />
                      <span>Tandai perlu pengambilan foto ulang (foto kurang jelas)</span>
                    </label>

                    {hasMissingFoodName && <p role="status" className="text-sm text-[#991B1B]">Isi nama untuk setiap komponen yang terlihat jelas.</p>}
                    {reviewDirty && currentHuman && <p role="status" className="text-sm text-[#8A5300]">Simpan perubahan sebelum mengirim laporan.</p>}
                    {saveHumanMutation.error && <p role="alert" className="text-sm text-[#991B1B]">{saveHumanMutation.error.message}</p>}
                    {submitQCMutation.error && <p role="alert" className="text-sm text-[#991B1B]">{submitQCMutation.error.message}</p>}
                    <div className="grid gap-3 pt-2 sm:flex sm:flex-wrap">
                      <button
                        type="button"
                        disabled={!humanDrafts.length || hasMissingFoodName || isWorking || Boolean(selectedFile)}
                        onClick={() => saveHumanMutation.mutate()}
                        className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-[#0F766E] bg-white px-4 py-2 text-sm font-semibold text-[#0F766E] hover:bg-[#EBF6F5] disabled:opacity-60"
                      >
                        {saveHumanMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                        ) : (
                          <ClipboardCheck className="h-4 w-4" aria-hidden="true" />
                        )}
                        <span>Simpan Tinjauan Manusia</span>
                      </button>

                      <button
                        type="button"
                        disabled={!canSubmit}
                        onClick={() => submitQCMutation.mutate()}
                        className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {submitQCMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                        ) : (
                          <Send className="h-4 w-4" aria-hidden="true" />
                        )}
                        <span>Kirim Pemeriksaan ke Kepala Dapur</span>
                      </button>
                    </div>
                  </div>
                </section>
              )}

              {/* Persisted Human Review Summary (visible to Manager, Planner & after submit) */}
              {latestHuman && (isLockedForQC || !isQC) && (
                <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
                  <h3 className="border-b border-[#EEF3EE] pb-3 text-sm font-bold text-[#16354A]">
                    Konfirmasi & Koreksi Petugas QC ({latestHuman.reviewer_name})
                  </h3>
                  <div className="mt-3 space-y-2">
                    {latestHuman.corrected_components.map((c) => (
                      <div
                        key={c.slot}
                        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#EEF3EE] bg-[#F5F8F5] px-3.5 py-2.5 text-xs"
                      >
                        <div>
                          <span className="font-bold text-[#16354A]">{formatSlotLabel(c.slot)}:</span>{" "}
                          <span className="text-[#16354A]">{c.observed_food_name}</span>
                          {c.officer_note && (
                            <span className="ml-2 text-[#647A87]">({c.officer_note})</span>
                          )}
                        </div>
                        <StatusBadge
                          tone={
                            c.confirmed_status === "not_visible"
                              ? "critical"
                              : c.confirmed_status === "visible"
                              ? "neutral"
                              : "warning"
                          }
                          label={formatObservationStatus(c.confirmed_status)}
                        />
                      </div>
                    ))}
                  </div>
                  {latestHuman.notes && (
                    <p className="mt-3 text-xs text-[#4A6170]">
                      <strong>Catatan Petugas QC:</strong> {latestHuman.notes}
                    </p>
                  )}
                </section>
              )}

              {/* Manager Review Panel */}
              {isManager && activeInspection.status === "SUBMITTED" && (
                <section className="rounded-2xl border border-[#0F766E] bg-white p-5 shadow-[0_1px_4px_rgba(15,118,110,0.08)]">
                  <h3 className="text-sm font-bold text-[#16354A]">
                    Keputusan Peninjauan Kepala Dapur
                  </h3>
                  <p className="mt-1 text-xs text-[#647A87]">
                    Keputusan ini hanya mencatat status dokumentasi pemeriksaan visual — bukan
                    pernyataan keamanan konsumsi makanan.
                  </p>

                  <div className="mt-3">
                    <label
                      htmlFor="qc-manager-notes"
                      className="block text-xs font-semibold text-[#4A6170]"
                    >
                      Catatan Kepala Dapur (wajib diisi untuk Revisi atau Foto Ulang)
                    </label>
                    <textarea
                      id="qc-manager-notes"
                      rows={2}
                        maxLength={2000}
                      value={managerNotes}
                      onChange={(e) => setManagerNotes(e.target.value)}
                      placeholder="Contoh: Diterima untuk arsip operasional dapur."
                      className="mt-1 w-full rounded-xl border border-[#DCE6DE] bg-white p-3 text-xs text-[#16354A]"
                    />
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2.5">
                    <button
                      type="button"
                      disabled={managerReviewMutation.isPending}
                      onClick={() => managerReviewMutation.mutate("ACCEPTED_FOR_RECORD")}
                      className="inline-flex min-h-[42px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      <span>Terima untuk Arsip Operasional</span>
                    </button>
                    <button
                      type="button"
                        disabled={managerReviewMutation.isPending || !managerNotes.trim()}
                      onClick={() => managerReviewMutation.mutate("REVISION_REQUIRED")}
                      className="inline-flex min-h-[42px] items-center rounded-xl border border-[#F5D59B] bg-[#FEF6E7] px-4 py-2 text-xs font-semibold text-[#8A5300] hover:bg-[#FDECC8] disabled:opacity-60"
                    >
                      <span>Minta Revisi Catatan</span>
                    </button>
                    <button
                      type="button"
                        disabled={managerReviewMutation.isPending || !managerNotes.trim()}
                      onClick={() => managerReviewMutation.mutate("RETAKE_REQUIRED")}
                      className="inline-flex min-h-[42px] items-center rounded-xl border border-[#F5C2C2] bg-white px-4 py-2 text-xs font-semibold text-[#991B1B] hover:bg-[#FEF0F0] disabled:opacity-60"
                    >
                      <span>Minta Foto Ulang</span>
                    </button>
                  </div>
                </section>
              )}

              {activeInspection.status === "REVIEWED" && (
                <section className="rounded-2xl border border-[#DCE6DE] bg-[#F5F8F5] p-4 text-xs text-[#4A6170]">
                  <p className="font-bold text-[#16354A]">
                    Hasil Tinjauan Kepala Dapur ({activeInspection.reviewed_by_name}):
                  </p>
                  {activeInspection.manager_notes && <p className="mt-1">{activeInspection.manager_notes}</p>}
                  {isQC && (activeInspection.review_outcome === "REVISION_REQUIRED" || activeInspection.review_outcome === "RETAKE_REQUIRED") && (
                    <button type="button" disabled={!approvedPlans.some((plan) => plan.id === activeInspection.menu_review_id)}
                      className="mt-2 min-h-[44px] rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                      onClick={() => {
                        setPreviousInspection(activeInspection);
                        setNewReviewId(activeInspection.menu_review_id ?? "");
                        setNewDayIndex(activeInspection.day_index);
                        setBanner(null);
                        requestAnimationFrame(() => createRef.current?.focus());
                      }}>
                      Siapkan Pemeriksaan Tindak Lanjut
                    </button>
                  )}
                </section>
              )}
            </>
          )}
        </div>
      </div>

      {/* Compromised Ingredient Reporting for QC & Manager */}
      <IncidentPanel compact />
    </div>
  );
}

export default function KitchenQCPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6">
          <PageHeader title="Pemeriksaan Menu AI" />
          <LoadingSkeleton rows={4} />
        </div>
      }
    >
      <KitchenQCContent />
    </Suspense>
  );
}
