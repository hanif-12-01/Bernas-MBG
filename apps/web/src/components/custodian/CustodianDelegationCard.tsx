"use client";

import React, { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldOff, UserCheck } from "lucide-react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { apiClient } from "@/lib/api/client";
import { formatJakartaDateTime } from "@/lib/formatters/jakartaDate";

export function CustodianDelegationCard() {
  const { user, refreshAuth } = useAuth();
  const qc = useQueryClient();
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [feedback, setFeedback] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  const query = useQuery({
    queryKey: ["stock-custodian", user?.active_kitchen_id],
    queryFn: apiClient.getStockCustodian,
    enabled: Boolean(user && user.active_role === "KITCHEN_MANAGER"),
  });

  useEffect(() => {
    const activeId = query.data?.active_assignment?.custodian_user_id;
    const firstEligible = query.data?.eligible_qc_candidates?.[0]?.user_id;
    if (!selectedUserId && (activeId || firstEligible)) {
      setSelectedUserId(activeId || firstEligible || "");
    }
  }, [query.data, selectedUserId]);

  const assignMutation = useMutation({
    mutationFn: () =>
      apiClient.assignStockCustodian({
        custodian_user_id: selectedUserId,
        notes: notes.trim() || undefined,
      }),
    onSuccess: (res) => {
      setFeedback({
        tone: "ok",
        text: `Pengelola Stok Aktif kini: ${res.active_assignment?.custodian_full_name ?? "Petugas QC"}.`,
      });
      setNotes("");
      qc.invalidateQueries({ queryKey: ["stock-custodian"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["qc-summary"] });
      void refreshAuth(true);
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal menunjuk pengelola stok.",
      });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: () => apiClient.revokeStockCustodian(notes.trim() || "Dicabut oleh Kepala Dapur."),
    onSuccess: () => {
      setFeedback({
        tone: "ok",
        text: "Penugasan Pengelola Stok aktif berhasil dicabut.",
      });
      setNotes("");
      qc.invalidateQueries({ queryKey: ["stock-custodian"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["qc-summary"] });
      void refreshAuth(true);
    },
    onError: (err) => {
      setFeedback({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal mencabut penugasan.",
      });
    },
  });

  const active = query.data?.active_assignment;
  const candidates = query.data?.eligible_qc_candidates ?? [];

  return (
    <section
      className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]"
      data-testid="custodian-delegation-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-bold text-[#16354A]">
            <UserCheck className="h-4 w-4 text-[#0F766E]" />
            Penunjukan Petugas QC Pengelola Stok (1 Aktif per Dapur)
          </h2>
          <p className="mt-0.5 text-xs text-[#647A87]">
            Hanya 1 Petugas QC aktif yang berwenang mencatat penerimaan barang, penyesuaian stok, dan laporan penahanan bahan.
          </p>
        </div>
        {active ? (
          <StatusBadge label={`Aktif: ${active.custodian_full_name}`} tone="success" />
        ) : (
          <StatusBadge label="Belum Ditugaskan" tone="warning" />
        )}
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

      {query.isLoading ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Memuat daftar Petugas QC...
        </div>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="custodian-candidate-select" className="block text-[11px] font-semibold text-slate-700">
              Pilih Petugas QC
            </label>
            <select
              id="custodian-candidate-select"
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900"
            >
              {candidates.map((c) => (
                <option key={c.user_id} value={c.user_id}>
                  {c.full_name} ({c.username}){c.is_active_custodian ? " — Aktif" : ""}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-semibold text-slate-700">
              Catatan Serah Terima (opsional)
            </label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Contoh: Shift pagi / cadangan"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs"
            />
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <button
              type="button"
              onClick={() => assignMutation.mutate()}
              disabled={assignMutation.isPending || !selectedUserId}
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg bg-[#0F766E] px-3.5 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-50"
            >
              {assignMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Tugaskan Pengelola Stok
            </button>
            {active && (
              <button
                type="button"
                onClick={() => revokeMutation.mutate()}
                disabled={revokeMutation.isPending}
                className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-800 hover:bg-rose-100 disabled:opacity-50"
              >
                <ShieldOff className="h-3.5 w-3.5" />
                Cabut Penugasan
              </button>
            )}
          </div>
        </div>
      )}

      {(query.data?.history?.length ?? 0) > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-2.5 text-[11px] text-slate-500">
          Riwayat terakhir:{" "}
          {query.data!.history
            .slice(0, 3)
            .map(
              (h) =>
                `${h.custodian_full_name} (${h.status}, ${formatJakartaDateTime(h.effective_from)})`
            )
            .join(" · ")}
        </div>
      )}
    </section>
  );
}
