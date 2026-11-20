"use client";

import React, { useEffect } from "react";
import Link from "next/link";
import { AlertCircle, Inbox, Lock, RefreshCw } from "lucide-react";

export function LoadingSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Memuat data">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-32 animate-pulse rounded-2xl border border-[#DCE6DE] bg-white p-5"
          >
            <div className="h-3.5 w-28 rounded bg-[#E6EEE8]" />
            <div className="mt-4 h-7 w-36 rounded bg-[#DCE6DE]" />
            <div className="mt-3 h-3 w-44 rounded bg-[#EEF3EE]" />
          </div>
        ))}
      </div>
      <div className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
        <div className="h-4 w-48 animate-pulse rounded bg-[#DCE6DE]" />
        <div className="mt-4 space-y-3">
          {Array.from({ length: rows }).map((_, idx) => (
            <div key={idx} className="h-10 animate-pulse rounded-xl bg-[#F5F8F5]" />
          ))}
        </div>
      </div>
    </div>
  );
}

interface EmptyStateProps {
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[#C7D6CB] bg-white px-6 py-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#EBF6F5] text-[#0F766E]">
        <Inbox className="h-6 w-6" aria-hidden="true" />
      </div>
      <h3 className="mt-4 text-base font-semibold text-[#16354A]">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm leading-relaxed text-[#4A6170]">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export function ErrorState({
  title = "Gagal Memuat Data",
  message,
  onRetry,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start justify-between gap-4 rounded-2xl border border-[#F5C2C2] bg-[#FEF0F0] p-5 sm:flex-row sm:items-center"
    >
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-[#C43D3D]" aria-hidden="true" />
        <div>
          <h3 className="text-sm font-semibold text-[#991B1B]">{title}</h3>
          <p className="mt-1 text-sm leading-relaxed text-[#7F1D1D]">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex min-h-[40px] shrink-0 items-center gap-2 rounded-xl border border-[#F5C2C2] bg-white px-4 py-2 text-sm font-semibold text-[#991B1B] hover:bg-[#FFF5F5]"
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          <span>Coba Lagi</span>
        </button>
      )}
    </div>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Lanjutkan",
  cancelLabel = "Batal",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#16354A]/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
    >
      <div className="w-full max-w-md rounded-2xl border border-[#DCE6DE] bg-white p-6 shadow-lg">
        <h3 id="confirm-dialog-title" className="text-base font-bold text-[#16354A]">
          {title}
        </h3>
        <p className="mt-2 text-sm leading-relaxed text-[#4A6170]">{description}</p>
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="min-h-[40px] rounded-xl border border-[#DCE6DE] bg-white px-4 py-2 text-sm font-semibold text-[#16354A] hover:bg-[#F5F8F5]"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="min-h-[40px] rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58]"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function AccessDeniedState({
  title = "Akses Tidak Diizinkan untuk Peran Anda",
  description = "Halaman ini tidak tersedia untuk peran aktif Anda. Gunakan menu yang sesuai dengan tugas operasional Anda.",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center rounded-2xl border border-[#F5D59B] bg-white px-6 py-12 text-center shadow-[0_1px_2px_rgba(22,53,74,0.04)]"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#FEF6E7] text-[#B45309]">
        <Lock className="h-6 w-6" aria-hidden="true" />
      </div>
      <h2 className="mt-4 text-base font-bold text-[#16354A]">{title}</h2>
      <p className="mt-1.5 max-w-md text-sm leading-relaxed text-[#4A6170]">{description}</p>
      <Link
        href="/dashboard"
        className="mt-5 inline-flex min-h-[42px] items-center rounded-xl bg-[#0F766E] px-4 py-2 text-sm font-semibold text-white hover:bg-[#0B5F58]"
      >
        Kembali ke Beranda
      </Link>
    </div>
  );
}
