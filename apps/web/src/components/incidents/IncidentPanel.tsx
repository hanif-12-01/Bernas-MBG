"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Camera,
  CheckCircle2,
  Loader2,
  Lock,
  ShieldAlert,
  Sparkles,
  Trash2,
} from "lucide-react";

import { ErrorState } from "@/components/feedback/FeedbackStates";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatDateTimeID,
  formatExposureStatusLabel,
  formatIncidentCategoryLabel,
  formatIncidentStatus,
  formatWeightFromGrams,
} from "@/lib/formatters/indonesian";
import type {
  IncidentCategoryEnum,
  IncidentSeverityEnum,
  IngredientIncidentResponse,
} from "@/types/api";

interface IncidentPanelProps {
  defaultDatasetId?: string;
  compact?: boolean;
  onIncidentChanged?: () => void;
  onNavigate?: (href: string) => void;
}

const INCIDENT_DEMO_DATASET_ID = "55555555-5555-4555-8555-555555555555";

export function IncidentPanel({
  defaultDatasetId,
  compact = false,
  onIncidentChanged,
  onNavigate,
}: IncidentPanelProps) {
  const { user } = useAuth();
  const { datasets, activeDataset } = useWorkspace();
  const qc = useQueryClient();

  const kitchenId = user?.active_kitchen_id;
  const role = user?.active_role;

  const [showForm, setShowForm] = useState(!compact);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(defaultDatasetId || "");
  const effectiveDatasetId =
    selectedDatasetId ||
    defaultDatasetId ||
    datasets.find((d) => d.id === INCIDENT_DEMO_DATASET_ID)?.id ||
    activeDataset?.id ||
    "";

  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<IncidentCategoryEnum>("SPOILAGE");
  const [severity, setSeverity] = useState<IncidentSeverityEnum>("CRITICAL");
  const [notes, setNotes] = useState("");
  const [selectedLotCodes, setSelectedLotCodes] = useState<string[]>([]);
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null);
  const [confirmDisposeId, setConfirmDisposeId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  const incidentsQuery = useQuery({
    queryKey: ["incidents", kitchenId],
    queryFn: () =>
      typeof apiClient.listIncidents === "function"
        ? apiClient.listIncidents()
        : Promise.resolve([]),
    enabled: Boolean(user),
  });

  const lotsQuery = useQuery({
    queryKey: ["inventory-lots", kitchenId, effectiveDatasetId],
    queryFn: () =>
      typeof apiClient.getInventoryLots === "function"
        ? apiClient.getInventoryLots(effectiveDatasetId || undefined)
        : Promise.resolve({
            kitchen_id: kitchenId || "",
            dataset_version_id: effectiveDatasetId || "",
            production_date: new Date().toISOString(),
            items: [],
          }),
    enabled: Boolean(user && effectiveDatasetId),
  });

  const candidateLots = useMemo(() => {
    const rows: Array<{
      lotId: string;
      lotCode: string;
      ingredientCode: string;
      ingredientName: string;
      usableG: number;
      recordedG: number;
      safetyHoldStatus: string;
      notes?: string | null;
    }> = [];
    for (const item of lotsQuery.data?.items ?? []) {
      for (const lot of item.lots ?? []) {
        rows.push({
          lotId: lot.id,
          lotCode: lot.lot_code,
          ingredientCode: item.ingredient_code,
          ingredientName: item.ingredient_name,
          usableG: lot.usable_raw_g,
          recordedG: lot.recorded_raw_g,
          safetyHoldStatus: lot.safety_hold_status || "NONE",
          notes: lot.notes,
        });
      }
    }
    return rows.sort((a, b) => {
      const a3c = a.lotCode.startsWith("LOT-3C-") ? 0 : 1;
      const b3c = b.lotCode.startsWith("LOT-3C-") ? 0 : 1;
      if (a3c !== b3c) return a3c - b3c;
      return a.ingredientName.localeCompare(b.ingredientName, "id");
    });
  }, [lotsQuery.data]);

  const toggleLotCode = (lotCode: string) => {
    setSelectedLotCodes((prev) =>
      prev.includes(lotCode) ? prev.filter((c) => c !== lotCode) : [...prev, lotCode]
    );
  };

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["incidents"] });
    qc.invalidateQueries({ queryKey: ["inventory-lots"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
    qc.invalidateQueries({ queryKey: ["operational-plans"] });
    qc.invalidateQueries({ queryKey: ["operational-plan-effective"] });
    qc.invalidateQueries({ queryKey: ["manager-summary"] });
    qc.invalidateQueries({ queryKey: ["qc-summary"] });
    qc.invalidateQueries({ queryKey: ["menu-reviews"] });
    onIncidentChanged?.();
  };

  const createMutation = useMutation({
    mutationFn: async () => {
      if (selectedLotCodes.length === 0) {
        throw new Error("Pilih minimal 1 lot/bahan yang bermasalah untuk ditahan keamanannya.");
      }
      if (title.trim().length < 3 || notes.trim().length < 5) {
        throw new Error("Isi judul (min. 3 karakter) dan kronologi temuan (min. 5 karakter).");
      }
      const created = await apiClient.createIncident({
        title: title.trim(),
        category,
        severity,
        notes: notes.trim(),
        dataset_version_id: effectiveDatasetId || undefined,
        affected_lots: selectedLotCodes.map((lot_code) => ({
          lot_code,
          reason_detail: notes.trim(),
        })),
        auto_hold_matching_lots: false,
      });
      if (evidenceFile) {
        await apiClient.uploadIncidentImage(created.id, evidenceFile);
      }
      return created;
    },
    onSuccess: (created) => {
      setTitle("");
      setNotes("");
      setSelectedLotCodes([]);
      setEvidenceFile(null);
      setShowForm(false);
      setFeedback({
        tone: "ok",
        text: `Insiden "${created.title}" dicatat: ${created.affected_lots.length} lot (${created.total_held_kg.toFixed(
          2
        )} kg) langsung berstatus SAFETY HOLD dan rencana terdampak ditahan (ON HOLD).`,
      });
      invalidateAll();
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof ApiError || err instanceof Error ? err.message : "Gagal melaporkan insiden.",
      });
    },
  });

  const recoverMutation = useMutation({
    mutationFn: (inc: IngredientIncidentResponse) =>
      apiClient.startIncidentRecovery(inc.id, {
        title: `Pemulihan Insiden: ${inc.title}`,
      }),
    onSuccess: (ev) => {
      invalidateAll();
      const targetUrl = `/simulator?eventId=${ev.id}${
        ev.baseline_run_id ? `&baselineRun=${ev.baseline_run_id}` : ""
      }${ev.baseline_menu_review_id ? `&reviewId=${ev.baseline_menu_review_id}` : ""}`;
      if (onNavigate) {
        onNavigate(targetUrl);
      } else if (typeof window !== "undefined") {
        window.location.assign(targetUrl);
      }
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof ApiError ? err.message : "Gagal menjalankan pemulihan menu dari insiden.",
      });
    },
  });

  const disposeMutation = useMutation({
    mutationFn: (incidentId: string) =>
      apiClient.updateIncidentStatus(incidentId, {
        status: "REJECTED",
        notes: "Lot ditolak/dimusnahkan oleh Kepala Dapur sesuai SOP internal.",
        dispose_held_lots: true,
        disposal_notes: "Lot dikeluarkan permanen dari stok layak pakai.",
      }),
    onSuccess: (updated) => {
      setConfirmDisposeId(null);
      setFeedback({
        tone: "ok",
        text: `Lot pada insiden "${updated.title}" berstatus REJECTED_DISPOSED dan tidak akan pernah terpakai di optimasi.`,
      });
      invalidateAll();
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof ApiError ? err.message : "Gagal menolak/memusnahkan lot.",
      });
    },
  });

  const incidents = incidentsQuery.data ?? [];

  return (
    <section
      aria-label="Penanganan Bahan Bermasalah & Safety Hold"
      className="space-y-4 rounded-2xl border border-[#F5C2C2] bg-white p-4 sm:p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#EEF3EE] pb-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-[#991B1B]" aria-hidden="true" />
            <h2 className="text-base font-bold text-[#16354A]">
              Laporan Bahan Bermasalah & Penahanan Keamanan (Safety Hold)
            </h2>
            {incidents.filter((i) => i.status === "ON_HOLD" || i.status === "UNDER_REVIEW").length > 0 && (
              <StatusBadge
                tone="critical"
                label={`${
                  incidents.filter((i) => i.status === "ON_HOLD" || i.status === "UNDER_REVIEW").length
                } insiden aktif`}
              />
            )}
          </div>
          <p className="text-xs leading-relaxed text-[#4A6170]">
            Lindungi penerima terlebih dahulu: lot bermasalah langsung dikecualikan dari stok siap pakai dan
            rencana terdampak otomatis berstatus <strong>ON HOLD</strong>.{" "}
            <span className="font-semibold text-[#991B1B]">
              Bukan uji laboratorium/BPOM, bukan validasi gizi klinis, dan bukan sertifikasi BGN.
            </span>
          </p>
        </div>

        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#991B1B] px-4 py-2 text-xs font-bold text-white hover:bg-[#7F1D1D]"
        >
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          <span>{showForm ? "Tutup Form Laporan" : "Laporkan Bahan Bermasalah"}</span>
        </button>
      </div>

      {feedback && (
        <div
          role={feedback.tone === "err" ? "alert" : "status"}
          className={`flex items-start gap-2 rounded-xl border p-3 text-xs font-medium ${
            feedback.tone === "ok"
              ? "border-[#B5DFDA] bg-[#EBF6F5] text-[#0F766E]"
              : "border-[#F5C2C2] bg-[#FEF0F0] text-[#991B1B]"
          }`}
        >
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{feedback.text}</span>
        </div>
      )}

      {showForm && (
        <div className="space-y-4 rounded-xl border border-[#F5C2C2] bg-[#FFF8F8] p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {datasets.length > 0 && (
              <div>
                <label htmlFor="inc-dataset" className="block text-xs font-semibold text-[#16354A]">
                  Dataset / Dapur Acuan
                </label>
                <select
                  id="inc-dataset"
                  value={effectiveDatasetId}
                  onChange={(e) => {
                    setSelectedDatasetId(e.target.value);
                    setSelectedLotCodes([]);
                  }}
                  className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-xs text-[#16354A]"
                >
                  {datasets.map((ds) => (
                    <option key={ds.id} value={ds.id}>
                      {ds.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div>
              <label htmlFor="inc-category" className="block text-xs font-semibold text-[#16354A]">
                Kategori Temuan
              </label>
              <select
                id="inc-category"
                value={category}
                onChange={(e) => setCategory(e.target.value as IncidentCategoryEnum)}
                className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-xs text-[#16354A]"
              >
                <option value="SPOILAGE">Basi / Pembusukan</option>
                <option value="SUSPECTED_CONTAMINATION">Dugaan Kontaminasi</option>
                <option value="ABNORMAL_ODOR_APPEARANCE">Bau / Warna Tidak Wajar</option>
                <option value="TEMPERATURE_EXCURSION">Suhu Penyimpanan Menyimpang</option>
                <option value="DAMAGED_PACKAGING">Kemasan Rusak / Bocor</option>
                <option value="SUPPLIER_RECALL">Penarikan Pemasok (Recall)</option>
                <option value="UNKNOWN_CONDITION">Kondisi Meragukan</option>
              </select>
            </div>

            <div>
              <label htmlFor="inc-severity" className="block text-xs font-semibold text-[#16354A]">
                Tingkat Risiko Operasional
              </label>
              <select
                id="inc-severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value as IncidentSeverityEnum)}
                className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-xs text-[#16354A]"
              >
                <option value="CRITICAL">KRITIS — Segera Tahan & Ganti Menu</option>
                <option value="HIGH">TINGGI — Tahan Lot Terdampak</option>
                <option value="MEDIUM">SEDANG — Evaluasi Batch</option>
                <option value="LOW">RENDAH — Catatan Kualitas</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label htmlFor="inc-title" className="block text-xs font-semibold text-[#16354A]">
                Judul Laporan Insiden
              </label>
              <input
                id="inc-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Contoh: Ayam Lot A Bau Asam + Telur Retak + Bayam Layu"
                className="mt-1 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
              />
            </div>

            <div>
              <label htmlFor="inc-photo" className="block text-xs font-semibold text-[#16354A]">
                Foto Bukti Lapangan (Opsional, EXIF otomatis dihapus)
              </label>
              <label
                htmlFor="inc-photo"
                className="mt-1 flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border border-dashed border-[#DCE6DE] bg-white px-3 text-xs text-[#4A6170] hover:bg-[#F5F8F5]"
              >
                <Camera className="h-4 w-4 text-[#0F766E]" aria-hidden="true" />
                <span className="truncate">
                  {evidenceFile ? evidenceFile.name : "Pilih foto bukti (JPEG/PNG/WEBP)..."}
                </span>
                <input
                  id="inc-photo"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(e) => setEvidenceFile(e.target.files?.[0] ?? null)}
                  className="sr-only"
                />
              </label>
            </div>
          </div>

          <div>
            <label htmlFor="inc-notes" className="block text-xs font-semibold text-[#16354A]">
              Keterangan Kondisi & Lokasi Penyimpanan
            </label>
            <textarea
              id="inc-notes"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Jelaskan kondisi bahan yang mencurigakan, rak/cold storage, atau indikasi kerusakan..."
              className="mt-1 w-full rounded-xl border border-[#DCE6DE] bg-white p-3 text-xs text-[#16354A]"
            />
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-bold text-[#16354A]">
                Pilih Satu atau Beberapa Lot Bahan Terdampak ({selectedLotCodes.length} dipilih):
              </span>
              {lotsQuery.isLoading && <span className="text-xs text-[#647A87]">Memuat daftar lot...</span>}
            </div>

            {candidateLots.length === 0 ? (
              <p className="rounded-xl border border-[#DCE6DE] bg-white p-3 text-xs text-[#647A87]">
                Belum ada batch lot terpisah pada dataset ini. Pilih dataset simulasi kualitas/insiden (3C) di atas untuk melihat daftar lot per bahan.
              </p>
            ) : (
              <div className="grid max-h-56 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
                {candidateLots.map((lot) => {
                  const checked = selectedLotCodes.includes(lot.lotCode);
                  const alreadyHeld = lot.safetyHoldStatus !== "NONE";
                  return (
                    <label
                      key={lot.lotId}
                      className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-2.5 text-xs transition ${
                        alreadyHeld
                          ? "border-[#F5C2C2] bg-[#FEF0F0]/70 opacity-75"
                          : checked
                            ? "border-[#991B1B] bg-[#FEF0F0] ring-1 ring-[#991B1B]"
                            : "border-[#DCE6DE] bg-white hover:bg-[#F5F8F5]"
                      }`}
                    >
                      <input
                        type="checkbox"
                        disabled={alreadyHeld}
                        checked={checked}
                        onChange={() => toggleLotCode(lot.lotCode)}
                        className="mt-0.5 h-4 w-4 accent-[#991B1B]"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="font-bold text-[#16354A] break-words">
                          {lot.ingredientName} ({lot.ingredientCode})
                        </p>
                        <p className="text-[11px] font-semibold text-[#4A6170]">{lot.lotCode}</p>
                        <p className="text-[11px] text-[#647A87]">
                          Siap pakai: {formatWeightFromGrams(lot.usableG)} / Tercatat:{" "}
                          {formatWeightFromGrams(lot.recordedG)}
                        </p>
                        {alreadyHeld && (
                          <span className="mt-1 inline-block rounded bg-[#991B1B] px-1.5 py-0.5 text-[10px] font-bold text-white">
                            {lot.safetyHoldStatus}
                          </span>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              disabled={createMutation.isPending || selectedLotCodes.length === 0}
              onClick={() => createMutation.mutate()}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#991B1B] px-5 py-2 text-sm font-bold text-white hover:bg-[#7F1D1D] disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <ShieldAlert className="h-4 w-4" aria-hidden="true" />
              )}
              <span>Tahan Lot & Laporkan Insiden</span>
            </button>
          </div>
        </div>
      )}

      {incidentsQuery.isError ? (
        <ErrorState
          title="Gagal memuat daftar insiden"
          message={(incidentsQuery.error as Error).message}
          onRetry={() => incidentsQuery.refetch()}
        />
      ) : incidents.length === 0 ? (
        <p className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-4 text-center text-xs text-[#647A87]">
          Belum ada insiden bahan bermasalah yang dilaporkan pada dapur ini.
        </p>
      ) : (
        <div className="space-y-3">
          {incidents.map((inc) => {
            const st = formatIncidentStatus(inc.status);
            const exp = formatExposureStatusLabel(inc.exposure_status);
            return (
              <article
                key={inc.id}
                className="space-y-3 rounded-xl border border-[#DCE6DE] bg-[#F8FAF8] p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-bold text-[#16354A] break-words">{inc.title}</h3>
                      <StatusBadge tone={st.tone} label={st.label} />
                      <StatusBadge tone="neutral" label={formatIncidentCategoryLabel(inc.category)} />
                    </div>
                    <p className="text-[11px] text-[#647A87]">
                      Dilaporkan oleh {inc.reported_by_name} ({inc.reporter_role}) •{" "}
                      {formatDateTimeID(inc.created_at)}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {role === "MENU_PLANNER" && inc.status !== "CLOSED" && (
                      inc.recovery_event_id ? (
                        <Link
                          href={`/simulator?eventId=${inc.recovery_event_id}`}
                          className="inline-flex min-h-[42px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-3.5 py-2 text-xs font-bold text-white hover:bg-[#0B5F58]"
                        >
                          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                          <span>Buka Hasil Pemulihan</span>
                          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                        </Link>
                      ) : (
                        <button
                          type="button"
                          disabled={recoverMutation.isPending}
                          onClick={() => recoverMutation.mutate(inc)}
                          className="inline-flex min-h-[42px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-3.5 py-2 text-xs font-bold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                        >
                          {recoverMutation.isPending ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                          ) : (
                            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                          )}
                          <span>Cari Alternatif Menu</span>
                        </button>
                      )
                    )}

                    {role === "KITCHEN_MANAGER" &&
                      (inc.status === "ON_HOLD" || inc.status === "UNDER_REVIEW") && (
                        confirmDisposeId === inc.id ? (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <button
                              type="button"
                              disabled={disposeMutation.isPending}
                              onClick={() => disposeMutation.mutate(inc.id)}
                              className="inline-flex min-h-[40px] items-center gap-1 rounded-xl bg-[#991B1B] px-3 py-1.5 text-xs font-bold text-white hover:bg-[#7F1D1D]"
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                              <span>Konfirmasi Musnahkan Lot</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDisposeId(null)}
                              className="min-h-[40px] rounded-xl border border-[#DCE6DE] bg-white px-2.5 text-xs font-semibold text-[#4A6170]"
                            >
                              Batal
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setConfirmDisposeId(inc.id)}
                            className="inline-flex min-h-[42px] items-center gap-1.5 rounded-xl border border-[#F5C2C2] bg-white px-3 py-1.5 text-xs font-bold text-[#991B1B] hover:bg-[#FEF0F0]"
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                            <span>Tolak / Musnahkan Lot</span>
                          </button>
                        )
                      )}
                  </div>
                </div>

                {inc.notes && <p className="text-xs text-[#334E5E]">{inc.notes}</p>}

                {/* Lot Hold vs Clean Stock Summary */}
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div className="rounded-lg border border-[#F5C2C2] bg-[#FEF0F0] p-2.5 text-xs">
                    <span className="block text-[11px] font-semibold text-[#991B1B]">
                      Total Stok Ditahan (SAFETY HOLD)
                    </span>
                    <strong className="text-sm font-bold text-[#991B1B] tabular-nums">
                      {inc.total_held_kg.toFixed(2)} kg ({inc.affected_lots.length} lot)
                    </strong>
                  </div>
                  <div className="rounded-lg border border-[#B5DFDA] bg-[#EBF6F5] p-2.5 text-xs">
                    <span className="block text-[11px] font-semibold text-[#0F766E]">
                      Sisa Lot Bersih Terverifikasi (Aman)
                    </span>
                    <strong className="text-sm font-bold text-[#0F766E] tabular-nums">
                      {inc.total_clean_remaining_kg.toFixed(2)} kg
                    </strong>
                  </div>
                  <div className="rounded-lg border border-[#DCE6DE] bg-white p-2.5 text-xs">
                    <span className="block text-[11px] font-semibold text-[#4A6170]">
                      Slot Rencana Aktif Terdampak
                    </span>
                    <strong className="text-sm font-bold text-[#16354A] tabular-nums">
                      {inc.affected_plans.length} slot hidangan
                    </strong>
                  </div>
                </div>

                {/* Per-lot details */}
                <div className="flex flex-wrap gap-1.5">
                  {inc.affected_lots.map((al) => (
                    <span
                      key={al.id}
                      className="inline-flex items-center gap-1 rounded-lg border border-[#F5C2C2] bg-white px-2.5 py-1 text-[11px] font-medium text-[#16354A]"
                    >
                      <strong className="text-[#991B1B]">{al.lot_code}</strong> • {al.ingredient_name}:{" "}
                      {(al.usable_before_hold_raw_g / 1000).toFixed(2)} kg [{al.lot_safety_status}]
                      {al.clean_remaining_raw_g > 0 && (
                        <span className="text-[#0F766E]">
                          (sisa bersih {(al.clean_remaining_raw_g / 1000).toFixed(2)} kg)
                        </span>
                      )}
                    </span>
                  ))}
                </div>

                {/* Exposure banner */}
                <div
                  className={`rounded-lg border p-2.5 text-xs ${
                    exp.tone === "critical"
                      ? "border-[#F5C2C2] bg-[#FEF0F0] text-[#991B1B]"
                      : "border-[#F3D19B] bg-[#FFFBEB] text-[#92400E]"
                  }`}
                >
                  <p className="font-bold">{exp.label}</p>
                  <ul className="mt-1 space-y-0.5 text-[11px]">
                    {inc.production_exposures.map((pe, idx) => (
                      <li key={idx}>• {pe.summary}</li>
                    ))}
                  </ul>
                </div>

                {/* Non-bypassable release rule banner */}
                <div className="flex items-start gap-2 rounded-lg border border-[#DCE6DE] bg-white px-3 py-2 text-[11px] text-[#4A6170]">
                  <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#991B1B]" aria-hidden="true" />
                  <span>
                    Lot berstatus <strong>SAFETY HOLD</strong> terkunci dan tidak dapat dilepaskan
                    sepihak di dalam aplikasi; pelepasan hanya dilakukan setelah keputusan resmi
                    otoritas/laboratorium berwenang di luar sistem ini.
                  </span>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
