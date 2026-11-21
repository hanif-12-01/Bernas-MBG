"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Camera,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  Lock,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/feedback/FeedbackStates";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import {
  formatExposureStatusLabel,
  formatIncidentCategoryLabel,
  formatIncidentStatus,
} from "@/lib/formatters/indonesian";
import { formatJakartaDateTime } from "@/lib/formatters/jakartaDate";
import type {
  IncidentCategoryEnum,
  IncidentSeverityEnum,
  IngredientIncidentResponse,
} from "@/types/api";

interface IncidentPanelProps {
  defaultDatasetId?: string;
  compact?: boolean;
  preselectedLotCode?: string | null;
  onIncidentChanged?: () => void;
  onNavigate?: (href: string) => void;
}

const INCIDENT_CATEGORIES: IncidentCategoryEnum[] = [
  "SPOILAGE",
  "SUSPECTED_CONTAMINATION",
  "DAMAGED_PACKAGING",
  "ABNORMAL_ODOR_APPEARANCE",
  "SUPPLIER_RECALL",
  "TEMPERATURE_EXCURSION",
  "UNKNOWN_CONDITION",
];

export function IncidentPanel({
  defaultDatasetId,
  compact = false,
  preselectedLotCode = null,
  onIncidentChanged,
  onNavigate,
}: IncidentPanelProps) {
  const { user } = useAuth();
  const { activeDataset, refreshAll } = useWorkspace();
  const qc = useQueryClient();

  const kitchenId = user?.active_kitchen_id;
  const isCustodian = Boolean(user?.active_role === "QC_OFFICER" && user?.is_active_stock_custodian);
  const effectiveDatasetId = defaultDatasetId || activeDataset?.id || "";

  // Default simplified 2-field flow: Lot/Bahan + Kondisi
  const [selectedLotCodes, setSelectedLotCodes] = useState<string[]>([]);
  const [category, setCategory] = useState<IncidentCategoryEnum>("SPOILAGE");
  const [showOptionalDetails, setShowOptionalDetails] = useState(false);

  // Optional collapsed fields
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<IncidentSeverityEnum>("HIGH");
  const [notes, setNotes] = useState("");
  const [supplierName, setSupplierName] = useState("");
  const [evidenceFile, setEvidenceFile] = useState<File | null>(null);

  // Decoupled upload retry state
  const [pendingRetryUpload, setPendingRetryUpload] = useState<{
    incidentId: string;
    file: File;
    errorMessage: string;
  } | null>(null);

  const [feedback, setFeedback] = useState<{ tone: "ok" | "warn" | "err"; text: string } | null>(
    null
  );
  const [lastCreatedIncident, setLastCreatedIncident] = useState<IngredientIncidentResponse | null>(
    null
  );

  useEffect(() => {
    if (preselectedLotCode) {
      setSelectedLotCodes((prev) =>
        prev.includes(preselectedLotCode) ? prev : [...prev, preselectedLotCode]
      );
    }
  }, [preselectedLotCode]);

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
            dataset_version_id: effectiveDatasetId,
            production_date: new Date().toISOString(),
            items: [],
          }),
    enabled: Boolean(user && isCustodian),
  });

  const flatLots = useMemo(() => {
    const out: Array<{
      lot_code: string;
      ingredient_code: string;
      ingredient_name: string;
      recorded_kg: number;
      safety_hold_status: string;
    }> = [];
    for (const entry of lotsQuery.data?.items ?? []) {
      for (const lot of entry.lots ?? []) {
        out.push({
          lot_code: lot.lot_code,
          ingredient_code: entry.ingredient_code,
          ingredient_name: entry.ingredient_name,
          recorded_kg: lot.recorded_raw_g / 1000,
          safety_hold_status: lot.safety_hold_status,
        });
      }
    }
    return out;
  }, [lotsQuery.data]);

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["incidents"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
    qc.invalidateQueries({ queryKey: ["inventory-lots"] });
    qc.invalidateQueries({ queryKey: ["effective-operational-plan"] });
    qc.invalidateQueries({ queryKey: ["operational-plans"] });
    qc.invalidateQueries({ queryKey: ["qc-summary"] });
    qc.invalidateQueries({ queryKey: ["manager-summary"] });
    qc.invalidateQueries({ queryKey: ["planner-summary"] });
    refreshAll?.();
    onIncidentChanged?.();
  };

  const reportMutation = useMutation({
    mutationFn: async () => {
      if (selectedLotCodes.length === 0) {
        throw new Error("Pilih minimal 1 lot bahan untuk langsung ditahan keamanannya.");
      }

      // Step 1: Atomic incident report & safety hold (ONLY 2 mandatory inputs; optional omitted if blank)
      const created = await apiClient.createIncident({
        dataset_version_id: effectiveDatasetId || undefined,
        category,
        severity,
        title: title.trim() || undefined,
        notes: notes.trim() || undefined,
        supplier_name: supplierName.trim() || undefined,
        affected_lots: selectedLotCodes.map((lotCode) => ({ lot_code: lotCode })),
        auto_hold_matching_lots: false,
        idempotency_key: `INC-UI-${Date.now()}-${selectedLotCodes.join("-")}`,
      });

      // Step 2: Decoupled optional evidence photo upload (never rolls back hold if network upload fails!)
      let uploadWarning: string | null = null;
      let latestIncident = created;
      if (evidenceFile && typeof apiClient.uploadIncidentImage === "function") {
        try {
          await apiClient.uploadIncidentImage(created.id, evidenceFile);
          latestIncident = await apiClient.getIncident(created.id);
        } catch (uploadErr) {
          uploadWarning =
            uploadErr instanceof Error ? uploadErr.message : "Gagal mengunggah foto bukti.";
        }
      }

      return { created: latestIncident, uploadWarning };
    },
    onSuccess: ({ created, uploadWarning }) => {
      setLastCreatedIncident(created);
      setSelectedLotCodes([]);
      setTitle("");
      setNotes("");
      setSupplierName("");
      if (uploadWarning && evidenceFile) {
        setPendingRetryUpload({
          incidentId: created.id,
          file: evidenceFile,
          errorMessage: uploadWarning,
        });
        setFeedback({
          tone: "warn",
          text: "Laporan berhasil dan bahan sudah ditahan. Foto belum berhasil diunggah. Coba unggah ulang.",
        });
      } else {
        setPendingRetryUpload(null);
        setEvidenceFile(null);
        setFeedback({
          tone: "ok",
          text: `Bahan langsung ditahan (${created.total_held_kg.toFixed(2)} kg pada ${created.affected_lots.length} lot).`,
        });
      }
      invalidateAll();
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof ApiError || err instanceof Error ? err.message : "Gagal menahan bahan.",
      });
    },
  });

  const retryUploadMutation = useMutation({
    mutationFn: async () => {
      if (!pendingRetryUpload) return;
      await apiClient.uploadIncidentImage(pendingRetryUpload.incidentId, pendingRetryUpload.file);
      return apiClient.getIncident(pendingRetryUpload.incidentId);
    },
    onSuccess: (updated) => {
      if (updated) setLastCreatedIncident(updated);
      setPendingRetryUpload(null);
      setEvidenceFile(null);
      setFeedback({
        tone: "ok",
        text: "Foto bukti tambahan berhasil diunggah dan terpasang pada laporan penahanan.",
      });
      invalidateAll();
    },
    onError: (err) => {
      setFeedback({
        tone: "warn",
        text: `Laporan berhasil dan bahan sudah ditahan. Foto belum berhasil diunggah (${
          err instanceof Error ? err.message : "coba lagi"
        }).`,
      });
    },
  });

  const disposalExecMutation = useMutation({
    mutationFn: (incidentId: string) => apiClient.recordIncidentDisposal(incidentId),
    onSuccess: (updated) => {
      setLastCreatedIncident(updated);
      setFeedback({
        tone: "ok",
        text: `Pemusnahan fisik lot pada insiden "${updated.title}" resmi dicatat ke buku besar stok.`,
      });
      invalidateAll();
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal mencatat pemusnahan fisik.",
      });
    },
  });

  const toggleLot = (lotCode: string) => {
    setSelectedLotCodes((prev) =>
      prev.includes(lotCode) ? prev.filter((c) => c !== lotCode) : [...prev, lotCode]
    );
  };

  const activeIncidents = useMemo(
    () =>
      (incidentsQuery.data ?? []).filter(
        (inc) => inc.status !== "CLOSED" && inc.disposal_executed_at == null
      ),
    [incidentsQuery.data]
  );

  const pendingDisposalForQC = activeIncidents.filter(
    (inc) => inc.disposal_authorized && !inc.disposal_executed_at
  );

  return (
    <section
      className="rounded-xl border border-rose-200 bg-white p-5 shadow-sm"
      data-testid="incident-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-semibold text-rose-800">
            <ShieldAlert className="h-3.5 w-3.5" />
            Penahanan Bahan Bermasalah
          </span>
          <h2 className="mt-1.5 text-lg font-bold text-slate-900">
            {isCustodian
              ? "Laporkan & Tahan Lot Bermasalah (2 Langkah Wajib)"
              : "Status Tahan Keamanan Bahan"}
          </h2>
          <p className="text-xs text-slate-600">
            {isCustodian
              ? "Pilih lot dan kondisinya — stok langsung dikecualikan agar tidak dipakai produksi maupun perencanaan menu."
              : user?.stock_custodian?.is_assigned
                ? `Penahanan stok hanya dapat dilaporkan oleh Petugas QC Pengelola Stok aktif: ${user.stock_custodian.custodian_full_name}.`
                : "Dapur belum memiliki Petugas QC Pengelola Stok aktif. Kepala Dapur perlu menunjuk petugas terlebih dahulu."}
          </p>
        </div>
      </div>

      {feedback && (
        <div
          className={`mt-3 rounded-lg border px-3.5 py-2.5 text-xs font-medium ${
            feedback.tone === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : feedback.tone === "warn"
                ? "border-amber-300 bg-amber-50 text-amber-950"
                : "border-rose-300 bg-rose-50 text-rose-900"
          }`}
          role="status"
        >
          <p>{feedback.text}</p>
          {pendingRetryUpload && (
            <button
              type="button"
              onClick={() => retryUploadMutation.mutate()}
              disabled={retryUploadMutation.isPending}
              className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-amber-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-800"
            >
              {retryUploadMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Camera className="h-3.5 w-3.5" />
              )}
              Unggah Ulang Foto
            </button>
          )}
        </div>
      )}

      {lastCreatedIncident && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold text-slate-900">{lastCreatedIncident.title}</span>
            <StatusBadge label={formatIncidentStatus(lastCreatedIncident.status).label} tone="critical" />
          </div>
          <p className="mt-1">
            Status paparan: <strong>{formatExposureStatusLabel(lastCreatedIncident.exposure_status).label}</strong>{" "}
            — Lot ditahan tidak dapat dipakai ulang lewat penyesuaian stok biasa.
          </p>
          {user?.active_role === "MENU_PLANNER" && (
            <Link
              href="/simulator"
              className="mt-2 inline-flex items-center gap-1 font-semibold text-indigo-700 hover:underline"
            >
              Buka Pemulihan Menu <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          )}
        </div>
      )}

      {/* Active Stock Custodian fast 2-field form */}
      {isCustodian && (
        <div className="mt-4 space-y-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          {lotsQuery.isError ? (
            <ErrorState message="Daftar lot belum dapat dimuat." onRetry={() => lotsQuery.refetch()} />
          ) : (
            <div>
              <label className="block text-xs font-semibold text-slate-800">
                1. Pilih Lot Bahan Bermasalah *
              </label>
              <div className="mt-2 grid max-h-56 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
                {flatLots
                  .filter((l) => l.safety_hold_status === "NONE")
                  .map((lot) => {
                    const checked = selectedLotCodes.includes(lot.lot_code);
                    return (
                      <label
                        key={lot.lot_code}
                        className={`flex cursor-pointer items-center justify-between rounded-lg border px-3 py-2 text-xs transition ${
                          checked
                            ? "border-rose-500 bg-rose-50 text-rose-950"
                            : "border-slate-200 bg-white text-slate-800 hover:border-slate-300"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleLot(lot.lot_code)}
                            className="h-4 w-4 accent-rose-600"
                          />
                          <div>
                            <div className="font-semibold">{lot.ingredient_name}</div>
                            <div className="text-[11px] text-slate-500">Lot {lot.lot_code}</div>
                          </div>
                        </div>
                        <span className="font-mono font-semibold text-slate-700">
                          {lot.recorded_kg.toFixed(1)} kg
                        </span>
                      </label>
                    );
                  })}
              </div>
              {flatLots.filter((l) => l.safety_hold_status === "NONE").length === 0 && (
                <p className="mt-1 text-xs text-slate-500">
                  Tidak ada lot bersih yang tersedia untuk ditahan pada dataset ini.
                </p>
              )}
            </div>
          )}

          <div>
            <label htmlFor="incident-category-select" className="block text-xs font-semibold text-slate-800">
              2. Kondisi / Penyebab *
            </label>
            <select
              id="incident-category-select"
              value={category}
              onChange={(e) => setCategory(e.target.value as IncidentCategoryEnum)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
            >
              {INCIDENT_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {formatIncidentCategoryLabel(cat)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowOptionalDetails((v) => !v)}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-700 hover:text-slate-950"
            >
              {showOptionalDetails ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
              Detail Tambahan (Opsional)
            </button>

            {showOptionalDetails && (
              <div className="mt-3 grid gap-3 rounded-lg border border-slate-200 bg-white p-3 sm:grid-cols-2">
                <div>
                  <label className="block text-[11px] font-medium text-slate-600">
                    Judul Singkat (otomatis jika kosong)
                  </label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Contoh: Suspek bau asam rak chiller 1"
                    className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-600">
                    Tingkat Keparahan
                  </label>
                  <select
                    value={severity}
                    onChange={(e) => setSeverity(e.target.value as IncidentSeverityEnum)}
                    className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs"
                  >
                    <option value="CRITICAL">Kritis</option>
                    <option value="HIGH">Tinggi</option>
                    <option value="MEDIUM">Sedang</option>
                    <option value="LOW">Rendah</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-600">
                    Nama Pemasok (opsional)
                  </label>
                  <input
                    type="text"
                    value={supplierName}
                    onChange={(e) => setSupplierName(e.target.value)}
                    placeholder="Contoh: CV Sumber Pangan"
                    className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs"
                  />
                </div>
                <div>
                  <label htmlFor="incident-evidence-file" className="block text-[11px] font-medium text-slate-600">
                    Foto Bukti Kondisi Bahan (opsional)
                  </label>
                  <input
                    id="incident-evidence-file"
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    onChange={(e) => setEvidenceFile(e.target.files?.[0] ?? null)}
                    className="mt-1 block w-full text-xs text-slate-600"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-[11px] font-medium text-slate-600">
                    Catatan Tambahan (otomatis jika kosong)
                  </label>
                  <textarea
                    rows={2}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Jelaskan lokasi penyimpanan atau ciri fisik..."
                    className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs"
                  />
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <span className="text-[11px] text-slate-500">
              {selectedLotCodes.length > 0
                ? `${selectedLotCodes.length} lot dipilih untuk langsung ditahan.`
                : "Pilih minimal 1 lot terlebih dahulu."}
            </span>
            <button
              type="button"
              onClick={() => reportMutation.mutate()}
              disabled={reportMutation.isPending || selectedLotCodes.length === 0}
              className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
            >
              {reportMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Lock className="h-4 w-4" />
              )}
              Tahan Bahan & Kirim Laporan
            </button>
          </div>
        </div>
      )}

      {/* Pending Physical Disposal Queue for Active QC Custodian */}
      {isCustodian && pendingDisposalForQC.length > 0 && (
        <div className="mt-4 space-y-2 rounded-xl border border-amber-300 bg-amber-50/70 p-4">
          <h3 className="text-sm font-bold text-amber-950">
            Menunggu Eksekusi Pemusnahan Fisik ({pendingDisposalForQC.length})
          </h3>
          <p className="text-xs text-amber-900">
            Kepala Dapur sudah menyetujui pemusnahan lot berikut. Catat pemusnahan fisik agar status buku besar stok selesai diperbarui.
          </p>
          {pendingDisposalForQC.map((inc) => (
            <div
              key={inc.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-white p-3 text-xs"
            >
              <div>
                <div className="font-semibold text-slate-900">{inc.title}</div>
                <div className="text-slate-600">
                  Disetujui {inc.disposal_authorized_by_name ?? "Kepala Dapur"} ·{" "}
                  {inc.affected_lots.map((l) => l.lot_code).join(", ")}
                </div>
              </div>
              <button
                type="button"
                onClick={() => disposalExecMutation.mutate(inc.id)}
                disabled={disposalExecMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg bg-amber-700 px-3 py-1.5 font-semibold text-white hover:bg-amber-800"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Catat Pemusnahan Fisik
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Read-only active holds list */}
      {!compact && activeIncidents.length > 0 && (
        <div className="mt-5 space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">
            Bahan Sedang Ditahan ({activeIncidents.length})
          </h3>
          {activeIncidents.map((inc) => {
            const st = formatIncidentStatus(inc.status);
            return (
              <div
                key={inc.id}
                className="rounded-lg border border-slate-200 bg-white p-3 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-semibold text-slate-900">{inc.title}</div>
                  <StatusBadge label={st.label} tone={st.tone} />
                </div>
                <p className="mt-1 text-slate-600">
                  {inc.affected_ingredient_names.join(", ")} · {inc.total_held_kg.toFixed(2)} kg ·{" "}
                  {formatJakartaDateTime(inc.observed_at)}
                </p>
                {onNavigate && user?.active_role === "MENU_PLANNER" && (
                  <button
                    type="button"
                    onClick={() => onNavigate("/simulator")}
                    className="mt-2 inline-flex items-center gap-1 font-semibold text-indigo-700 hover:underline"
                  >
                    Cari Pengganti Menu <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!isCustodian && activeIncidents.length === 0 && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2 text-xs text-emerald-900">
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          Tidak ada bahan yang sedang ditahan keamanan saat ini.
        </div>
      )}
    </section>
  );
}
