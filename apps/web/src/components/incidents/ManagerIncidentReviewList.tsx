"use client";

import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, Eye, Loader2, ShieldAlert, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { apiClient } from "@/lib/api/client";
import {
  formatExposureStatusLabel,
  formatIncidentCategoryLabel,
  formatIncidentStatus,
} from "@/lib/formatters/indonesian";
import { formatJakartaDateTime } from "@/lib/formatters/jakartaDate";
import type { IngredientIncidentResponse } from "@/types/api";

export function ManagerIncidentReviewList() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  const incidentsQuery = useQuery({
    queryKey: ["incidents", user?.active_kitchen_id],
    queryFn: () => apiClient.listIncidents(),
    enabled: Boolean(user && user.active_role === "KITCHEN_MANAGER"),
  });

  const statusMutation = useMutation({
    mutationFn: (payload: {
      incidentId: string;
      status: string;
      notes?: string;
      dispose_held_lots?: boolean;
    }) =>
      apiClient.updateIncidentStatus(payload.incidentId, {
        status: payload.status,
        notes: payload.notes,
        dispose_held_lots: payload.dispose_held_lots,
      }),
    onSuccess: (updated) => {
      setFeedback({
        tone: "ok",
        text: updated.disposal_authorized
          ? `Otorisasi pemusnahan untuk "${updated.title}" disetujui. Menunggu pencatatan pemusnahan fisik oleh Petugas QC Pengelola Stok.`
          : `Status insiden "${updated.title}" diperbarui.`,
      });
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["qc-summary"] });
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal memperbarui status insiden.",
      });
    },
  });

  const openIncidents = (incidentsQuery.data ?? []).filter((inc) => inc.status !== "CLOSED");

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      data-testid="manager-incident-review-list"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-slate-900">
            Tinjauan Bahan Bermasalah & Otorisasi Pemusnahan
          </h2>
          <p className="text-xs text-slate-600">
            Kepala Dapur meninjau laporan dan mengotorisasi pemusnahan lot; pencatatan stok akhir dijalankan oleh Petugas QC Pengelola Stok.
          </p>
        </div>
        <StatusBadge
          label={`${openIncidents.length} Perlu Pantauan`}
          tone={openIncidents.length > 0 ? "warning" : "success"}
        />
      </div>

      {feedback && (
        <div
          className={`mt-3 rounded-lg border px-3 py-2 text-xs font-medium ${
            feedback.tone === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-rose-200 bg-rose-50 text-rose-900"
          }`}
        >
          {feedback.text}
        </div>
      )}

      {incidentsQuery.isLoading ? (
        <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Memuat daftar insiden...
        </div>
      ) : openIncidents.length === 0 ? (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50/70 px-3 py-2.5 text-xs text-emerald-900">
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          Tidak ada insiden bahan bermasalah yang menunggu tinjauan saat ini.
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {openIncidents.map((inc: IngredientIncidentResponse) => {
            const st = formatIncidentStatus(inc.status);
            const exp = formatExposureStatusLabel(inc.exposure_status);
            const expanded = expandedId === inc.id;
            return (
              <div key={inc.id} className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <ShieldAlert className="h-4 w-4 text-rose-600" />
                      <h3 className="text-sm font-bold text-slate-900">{inc.title}</h3>
                      <StatusBadge label={st.label} tone={st.tone} />
                      <StatusBadge label={exp.label} tone={exp.tone} />
                    </div>
                    <p className="mt-1 text-xs text-slate-600">
                      {formatIncidentCategoryLabel(inc.category)} ·{" "}
                      <strong>{inc.affected_ingredient_names.join(", ")}</strong> ({inc.total_held_kg.toFixed(2)} kg)
                      · Dilaporkan oleh {inc.reported_by_name} pada {formatJakartaDateTime(inc.observed_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setExpandedId(expanded ? null : inc.id)}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    {expanded ? "Tutup Detail" : "Lihat Detail & Foto"}
                  </button>
                </div>

                {inc.disposal_authorized && !inc.disposal_executed_at && (
                  <div className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-900">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    Otorisasi disetujui — Menunggu eksekusi pemusnahan oleh Petugas QC Stok
                  </div>
                )}

                {expanded && (
                  <div className="mt-3 space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-700">
                    <p>{inc.notes}</p>
                    <div className="flex flex-wrap gap-2">
                      {inc.affected_lots.map((l) => (
                        <span
                          key={l.id}
                          className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px]"
                        >
                          {l.lot_code}: {l.lot_safety_status} ({(l.recorded_raw_g_snapshot / 1000).toFixed(2)} kg)
                        </span>
                      ))}
                    </div>
                    {inc.images.length > 0 && (
                      <div className="grid grid-cols-2 gap-2 pt-1 sm:grid-cols-3">
                        {inc.images.map((img) => (
                          <img
                            key={img.id}
                            src={apiClient.getProtectedImageUrl(img.image_url)}
                            alt={img.original_filename_sanitized}
                            className="h-28 w-full rounded-md border border-slate-200 object-cover"
                          />
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="mt-3 flex flex-wrap gap-2">
                  {inc.status === "ON_HOLD" && !inc.disposal_authorized && (
                    <button
                      type="button"
                      onClick={() =>
                        statusMutation.mutate({
                          incidentId: inc.id,
                          status: "UNDER_REVIEW",
                          notes: "Sedang ditinjau oleh Kepala Dapur.",
                        })
                      }
                      disabled={statusMutation.isPending}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-800 hover:bg-slate-100"
                    >
                      Tandai Sedang Ditinjau
                    </button>
                  )}
                  {!inc.disposal_authorized && (
                    <button
                      type="button"
                      onClick={() =>
                        statusMutation.mutate({
                          incidentId: inc.id,
                          status: "REJECTED",
                          dispose_held_lots: true,
                          notes: "Otorisasi pemusnahan lot disetujui oleh Kepala Dapur.",
                        })
                      }
                      disabled={statusMutation.isPending}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Setujui Pemusnahan Lot
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
