"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Download,
  FileText,
  Info,
  Loader2,
  PackageCheck,
  Search,
  ShoppingBasket,
  Upload,
  XCircle,
} from "lucide-react";

import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { apiClient, ApiError } from "@/lib/api/client";
import { formatIDR, formatWeightFromGrams } from "@/lib/formatters/indonesian";
import {
  formatJakartaDate,
  formatJakartaDateTime,
  getJakartaTodayISO,
} from "@/lib/formatters/jakartaDate";
import type { EvidenceStatusEnum, GoodsConditionEnum } from "@/types/api";

type ActiveTab = "needs" | "purchases" | "receipts";

function evidenceBadge(status: EvidenceStatusEnum): {
  label: string;
  tone: "success" | "warning" | "critical" | "neutral";
} {
  switch (status) {
    case "NO_EVIDENCE":
      return { label: "Belum Ada Bukti", tone: "neutral" };
    case "RECEIPT_UPLOADED":
      return { label: "Bukti Diunggah", tone: "warning" };
    case "GOODS_RECEIVED":
      return { label: "Barang Diterima", tone: "warning" };
    case "VERIFIED_MATCH":
      return { label: "Terverifikasi Cocok", tone: "success" };
    case "DISCREPANCY_FLAGGED":
      return { label: "Ada Selisih", tone: "critical" };
  }
}

function conditionLabel(c: GoodsConditionEnum): string {
  switch (c) {
    case "GOOD":
      return "Baik (Layak Pakai)";
    case "DAMAGED":
      return "Rusak / Kemasan Sobek";
    case "QUARANTINED":
      return "Karantina (Perlu Cek)";
    case "REJECTED":
      return "Ditolak Saat Terima";
  }
}

function ShoppingListContent() {
  const { user } = useAuth();
  const { selectedRun, selectedScenario, activeDataset, isLoadingList, isLoadingRun, refreshAll } =
    useWorkspace();
  const qc = useQueryClient();
  const searchParams = useSearchParams();

  const isQC = user?.active_role === "QC_OFFICER";
  const isCustodian = Boolean(user?.active_role === "QC_OFFICER" && user?.is_active_stock_custodian);
  const isManager = user?.active_role === "KITCHEN_MANAGER";
  const canSeePrices = !isQC;

  const initialTabParam = searchParams.get("tab");
  const [tab, setTab] = useState<ActiveTab>(
    initialTabParam === "purchases" || initialTabParam === "receipts" ? initialTabParam : "needs"
  );

  useEffect(() => {
    const p = searchParams.get("tab");
    if (p === "needs" || p === "purchases" || p === "receipts") {
      setTab(p);
    }
  }, [searchParams]);

  // Tab 1 state
  const [search, setSearch] = useState("");
  const [exportMessage, setExportMessage] = useState<{ tone: "ok" | "err"; text: string } | null>(
    null
  );
  const [isExporting, setIsExporting] = useState(false);

  // Tab 2 state (New Purchase Record - NEVER auto-filled!)
  const [supplierName, setSupplierName] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [purchaseDate, setPurchaseDate] = useState(() => getJakartaTodayISO());
  const [totalAmountIdr, setTotalAmountIdr] = useState("");
  const [docNotes, setDocNotes] = useState("");
  const [docFeedback, setDocFeedback] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  // Tab 3 state (Goods Receipt)
  const [receiptDocId, setReceiptDocId] = useState("");
  const [receiptIngCode, setReceiptIngCode] = useState("");
  const [receiptLotCode, setReceiptLotCode] = useState("");
  const [receiptQty, setReceiptQty] = useState("");
  const [receiptUnit, setReceiptUnit] = useState("kg");
  const [receiptExpiry, setReceiptExpiry] = useState("");
  const [receiptSupplier, setReceiptSupplier] = useState("");
  const [receiptCondition, setReceiptCondition] = useState<GoodsConditionEnum>("GOOD");
  const [receiptNotes, setReceiptNotes] = useState("");
  const [receiptFeedback, setReceiptFeedback] = useState<{ tone: "ok" | "err"; text: string } | null>(
    null
  );

  const shoppingQuery = useQuery({
    queryKey: ["shopping-list", selectedRun?.run_id],
    queryFn: () => apiClient.getShoppingList(selectedRun!.run_id),
    enabled: Boolean(selectedRun?.run_id && selectedRun?.validation_passed && !isQC),
    retry: 0,
  });

  const inventoryQuery = useQuery({
    queryKey: ["inventory", user?.active_kitchen_id, activeDataset?.id],
    queryFn: () => apiClient.getInventory(activeDataset?.id),
    enabled: Boolean(user),
  });

  const docsQuery = useQuery({
    queryKey: ["purchase-documents", user?.active_kitchen_id],
    queryFn: () => apiClient.listPurchaseDocuments(50),
    enabled: Boolean(user),
  });

  const receiptsQuery = useQuery({
    queryKey: ["goods-receipts", user?.active_kitchen_id],
    queryFn: () => apiClient.listGoodsReceipts(50),
    enabled: Boolean(user),
  });

  useEffect(() => {
    if (!receiptIngCode && (inventoryQuery.data?.items?.length ?? 0) > 0) {
      setReceiptIngCode(inventoryQuery.data!.items[0].code);
    }
  }, [inventoryQuery.data?.items, receiptIngCode]);

  const createDocMutation = useMutation({
    mutationFn: () => {
      if (!supplierName.trim()) throw new Error("Nama pemasok wajib diisi.");
      const amt = totalAmountIdr.trim() ? Number(totalAmountIdr) : undefined;
      if (amt !== undefined && (!Number.isFinite(amt) || amt < 0)) {
        throw new Error("Total nominal pembelian tidak valid.");
      }
      return apiClient.createPurchaseDocument({
        dataset_version_id: activeDataset?.id,
        linked_run_id: selectedRun?.run_id,
        supplier_name: supplierName.trim(),
        invoice_number: invoiceNumber.trim() || undefined,
        purchase_date: purchaseDate || undefined,
        total_amount_idr: amt,
        notes: docNotes.trim() || undefined,
      });
    },
    onSuccess: (created) => {
      setDocFeedback({
        tone: "ok",
        text: `Catatan pembelian dari ${created.supplier_name} disimpan. Silakan unggah foto/PDF struk.`,
      });
      setSupplierName("");
      setInvoiceNumber("");
      setTotalAmountIdr("");
      setDocNotes("");
      qc.invalidateQueries({ queryKey: ["purchase-documents"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
    },
    onError: (err) => {
      setDocFeedback({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal mencatat pembelian.",
      });
    },
  });

  const uploadEvidenceMutation = useMutation({
    mutationFn: ({ docId, file }: { docId: string; file: File }) =>
      apiClient.uploadPurchaseEvidence(docId, file),
    onSuccess: () => {
      setDocFeedback({ tone: "ok", text: "Bukti struk/faktur berhasil diunggah." });
      qc.invalidateQueries({ queryKey: ["purchase-documents"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
    },
    onError: (err) => {
      setDocFeedback({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal mengunggah berkas bukti.",
      });
    },
  });

  const reviewDocMutation = useMutation({
    mutationFn: ({
      docId,
      decision,
    }: {
      docId: string;
      decision: "VERIFIED_MATCH" | "DISCREPANCY_FLAGGED";
    }) => apiClient.reviewPurchaseDocument(docId, { decision }),
    onSuccess: (updated) => {
      setDocFeedback({
        tone: "ok",
        text: `Status bukti pembelian "${updated.supplier_name}" diperbarui.`,
      });
      qc.invalidateQueries({ queryKey: ["purchase-documents"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
    },
    onError: (err) => {
      setDocFeedback({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal memverifikasi bukti.",
      });
    },
  });

  const createReceiptMutation = useMutation({
    mutationFn: () => {
      const qty = Number(receiptQty);
      if (!receiptIngCode) throw new Error("Pilih bahan yang diterima.");
      if (!Number.isFinite(qty) || qty <= 0) throw new Error("Jumlah diterima harus lebih dari 0.");
      return apiClient.createGoodsReceipt({
        dataset_version_id: activeDataset?.id,
        purchase_document_id: receiptDocId || undefined,
        ingredient_code: receiptIngCode,
        lot_code: receiptLotCode.trim() || undefined,
        received_quantity: qty,
        unit: receiptUnit,
        expiry_date: receiptExpiry || undefined,
        supplier_name: receiptSupplier.trim() || undefined,
        condition_status: receiptCondition,
        notes: receiptNotes.trim() || undefined,
      });
    },
    onSuccess: (res) => {
      setReceiptFeedback({
        tone: "ok",
        text: `Penerimaan ${res.ingredient_name} (${(res.received_raw_g / 1000).toFixed(2)} kg, lot ${res.lot_code}) tercatat — stok siap pakai bertambah ${(res.usable_added_raw_g / 1000).toFixed(2)} kg.`,
      });
      setReceiptLotCode("");
      setReceiptQty("");
      setReceiptNotes("");
      qc.invalidateQueries({ queryKey: ["goods-receipts"] });
      qc.invalidateQueries({ queryKey: ["purchase-documents"] });
      qc.invalidateQueries({ queryKey: ["inventory"] });
      qc.invalidateQueries({ queryKey: ["inventory-detail"] });
      refreshAll?.();
    },
    onError: (err) => {
      setReceiptFeedback({
        tone: "err",
        text: err instanceof ApiError || err instanceof Error ? err.message : "Gagal mencatat penerimaan.",
      });
    },
  });

  const handleDownloadCsv = async () => {
    if (!selectedRun) return;
    setIsExporting(true);
    setExportMessage(null);
    try {
      const { blob, filename } = await apiClient.downloadRunCsv(selectedRun.run_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      setExportMessage({ tone: "ok", text: `Berhasil mengunduh ${filename}.` });
    } catch (err) {
      setExportMessage({
        tone: "err",
        text: err instanceof Error ? err.message : "Gagal mengunduh CSV.",
      });
    } finally {
      setIsExporting(false);
    }
  };

  const materialItems = useMemo(() => {
    const raw = isQC ? selectedRun?.material_usage ?? [] : shoppingQuery.data ?? [];
    const prices = selectedRun?.input_snapshot?.prices_idr_per_g ?? {};
    const q = search.trim().toLowerCase();
    return raw
      .filter((m) => !q || m.ingredient_name.toLowerCase().includes(q) || m.ingredient_code.toLowerCase().includes(q))
      .map((item) => {
        const priceG = canSeePrices ? prices[item.ingredient_code] ?? null : null;
        return {
          ...item,
          estimatedCost: priceG !== null ? item.used_raw_g * priceG : null,
          additionalPurchaseG: Math.max(0, item.used_raw_g - item.available_raw_g),
        };
      });
  }, [isQC, selectedRun, shoppingQuery.data, search, canSeePrices]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Belanja & Penerimaan Barang"
        subtitle="Kelola kebutuhan belanja rencana menu, dokumentasi struk/faktur pembelian nyata, dan pencatatan barang masuk ke stok dapur."
        badges={<DatasetSimulationNotice compact />}
      />

      {/* Shared 3-Tab Switcher */}
      <div className="flex flex-wrap gap-2 border-b border-[#DCE6DE] pb-3">
        <button
          type="button"
          onClick={() => setTab("needs")}
          className={`inline-flex min-h-[40px] items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition ${
            tab === "needs"
              ? "bg-[#0F766E] text-white"
              : "border border-[#DCE6DE] bg-white text-[#4A6170] hover:bg-[#F5F8F5]"
          }`}
        >
          <ShoppingBasket className="h-4 w-4" />
          Kebutuhan Bahan
        </button>
        <button
          type="button"
          onClick={() => setTab("purchases")}
          className={`inline-flex min-h-[40px] items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition ${
            tab === "purchases"
              ? "bg-[#0F766E] text-white"
              : "border border-[#DCE6DE] bg-white text-[#4A6170] hover:bg-[#F5F8F5]"
          }`}
        >
          <FileText className="h-4 w-4" />
          Pembelian & Bukti ({docsQuery.data?.length ?? 0})
        </button>
        <button
          type="button"
          onClick={() => setTab("receipts")}
          className={`inline-flex min-h-[40px] items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition ${
            tab === "receipts"
              ? "bg-[#0F766E] text-white"
              : "border border-[#DCE6DE] bg-white text-[#4A6170] hover:bg-[#F5F8F5]"
          }`}
        >
          <PackageCheck className="h-4 w-4" />
          Penerimaan Barang ({receiptsQuery.data?.length ?? 0})
        </button>
      </div>

      {/* TAB 1: KEBUTUHAN BAHAN */}
      {tab === "needs" && (
        <div className="space-y-4">
          {isLoadingList || isLoadingRun ? (
            <LoadingSkeleton rows={4} />
          ) : !selectedRun || !selectedRun.validation_passed ? (
            <EmptyState
              title="Belum ada rencana menu aktif atau layak yang dipilih"
              description="Pilih rencana menu terverifikasi dari pemilih di bagian atas untuk melihat daftar kebutuhan bahan."
              action={
                user?.active_role === "MENU_PLANNER" ? (
                  <Link
                    href="/menu-planning"
                    className="inline-flex min-h-[40px] items-center rounded-xl bg-[#0F766E] px-4 text-xs font-semibold text-white"
                  >
                    Buka Rencana Menu
                  </Link>
                ) : undefined
              }
            />
          ) : shoppingQuery.isError ? (
            <ErrorState
              message={shoppingQuery.error?.message ?? "Gagal memuat daftar kebutuhan."}
              onRetry={() => shoppingQuery.refetch()}
            />
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#DCE6DE] bg-white p-4">
                <div className="relative min-w-[220px] flex-1">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder={`Cari bahan untuk ${selectedScenario?.name ?? "rencana ini"}...`}
                    className="w-full rounded-lg border border-slate-300 py-2 pl-9 pr-3 text-sm"
                  />
                </div>
                {canSeePrices && (
                  <button
                    type="button"
                    onClick={() => void handleDownloadCsv()}
                    disabled={isExporting}
                    className="inline-flex min-h-[40px] items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
                  >
                    <Download className="h-4 w-4" />
                    Ekspor CSV
                  </button>
                )}
              </div>

              {exportMessage && (
                <p className="text-xs font-medium text-slate-700">{exportMessage.text}</p>
              )}

              <div className="overflow-x-auto rounded-xl border border-[#DCE6DE] bg-white">
                <table className="w-full border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50 text-slate-600">
                      <th className="px-4 py-3">Bahan</th>
                      <th className="px-4 py-3">Kebutuhan Rencana</th>
                      <th className="px-4 py-3">Stok Terikat Rencana</th>
                      <th className="px-4 py-3">Tambahan Perlu Dibeli</th>
                      {canSeePrices && <th className="px-4 py-3">Estimasi Biaya</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {materialItems.map((item) => (
                      <tr key={item.ingredient_code} className="border-b border-slate-100">
                        <td className="px-4 py-3 font-semibold text-slate-900">
                          {item.ingredient_name}{" "}
                          <span className="font-normal text-slate-500">({item.ingredient_code})</span>
                        </td>
                        <td className="px-4 py-3 font-mono font-semibold">
                          {formatWeightFromGrams(item.used_raw_g)}
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-600">
                          {formatWeightFromGrams(item.available_raw_g)}
                        </td>
                        <td className="px-4 py-3 font-mono font-semibold text-amber-800">
                          {item.additionalPurchaseG > 0
                            ? formatWeightFromGrams(item.additionalPurchaseG)
                            : "Cukup di stok"}
                        </td>
                        {canSeePrices && (
                          <td className="px-4 py-3 font-mono text-slate-800">
                            {formatIDR(item.estimatedCost)}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: PEMBELIAN & BUKTI */}
      {tab === "purchases" && (
        <div className="space-y-4">
          {docFeedback && (
            <div
              className={`rounded-lg border px-4 py-2.5 text-xs font-medium ${
                docFeedback.tone === "ok"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                  : "border-rose-200 bg-rose-50 text-rose-900"
              }`}
            >
              {docFeedback.text}
            </div>
          )}

          {isCustodian ? (
            <section className="rounded-xl border border-[#DCE6DE] bg-white p-4 shadow-sm">
              <h2 className="text-sm font-bold text-[#16354A]">
                Catat Pembelian Nyata (Manual — Tanpa Isi Otomatis dari Estimasi)
              </h2>
              <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-600">
                <Info className="h-3.5 w-3.5 text-[#0F766E]" />
                Isi nominal & pemasok sesuai faktur/struk pembelian sebenarnya.
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    Nama Pemasok *
                  </label>
                  <input
                    type="text"
                    value={supplierName}
                    onChange={(e) => setSupplierName(e.target.value)}
                    placeholder="Contoh: CV Sumber Pangan"
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    No. Faktur / Nota
                  </label>
                  <input
                    type="text"
                    value={invoiceNumber}
                    onChange={(e) => setInvoiceNumber(e.target.value)}
                    placeholder="Opsional"
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    Tanggal Belanja (WIB)
                  </label>
                  <input
                    type="date"
                    value={purchaseDate}
                    onChange={(e) => setPurchaseDate(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    Total Nominal Struk (Rp)
                  </label>
                  <input
                    type="number"
                    min="0"
                    value={totalAmountIdr}
                    onChange={(e) => setTotalAmountIdr(e.target.value)}
                    placeholder="Kosongkan jika belum ada"
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs"
                  />
                </div>
                <div className="sm:col-span-2 lg:col-span-4">
                  <label className="block text-[11px] font-semibold text-slate-700">Catatan</label>
                  <input
                    type="text"
                    value={docNotes}
                    onChange={(e) => setDocNotes(e.target.value)}
                    placeholder="Catatan singkat pengiriman atau kelengkapan..."
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs"
                  />
                </div>
              </div>
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => createDocMutation.mutate()}
                  disabled={createDocMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
                >
                  {createDocMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Simpan Catatan Pembelian
                </button>
              </div>
            </section>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
              Pencatatan pembelian & unggah struk dilakukan oleh Petugas QC Pengelola Stok aktif. Kepala Dapur memverifikasi kecocokan bukti di daftar bawah ini.
            </div>
          )}

          {docsQuery.isLoading ? (
            <LoadingSkeleton rows={3} />
          ) : (docsQuery.data?.length ?? 0) === 0 ? (
            <EmptyState
              title="Belum ada catatan pembelian"
              description="Petugas QC Pengelola Stok dapat mencatat pembelian dan mengunggah foto atau PDF faktur di sini."
            />
          ) : (
            <div className="space-y-3" data-testid="purchase-documents-list">
              {docsQuery.data!.map((doc) => {
                const badge = evidenceBadge(doc.evidence_status);
                return (
                  <div key={doc.id} className="rounded-xl border border-[#DCE6DE] bg-white p-4 text-xs">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-bold text-slate-900">{doc.supplier_name}</span>
                          <StatusBadge label={badge.label} tone={badge.tone} />
                        </div>
                        <p className="mt-1 text-slate-600">
                          Tanggal: {formatJakartaDate(doc.purchase_date)}
                          {doc.invoice_number ? ` · Nota ${doc.invoice_number}` : ""}
                          {doc.total_amount_idr != null ? ` · ${formatIDR(doc.total_amount_idr)}` : ""}
                        </p>
                      </div>
                      {doc.has_evidence_file && doc.evidence_url && (
                        <a
                          href={apiClient.getProtectedImageUrl(doc.evidence_url)}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 font-semibold text-[#0F766E] hover:bg-slate-50"
                        >
                          <FileText className="h-3.5 w-3.5" />
                          Lihat Bukti ({doc.document_original_filename})
                        </a>
                      )}
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {isCustodian && (
                        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[#B5DFDA] bg-[#EBF6F5] px-3 py-1.5 font-semibold text-[#0F766E] hover:bg-[#DDF0EE]">
                          <Upload className="h-3.5 w-3.5" />
                          <span>
                            {doc.has_evidence_file ? "Ganti Bukti (Foto/PDF)" : "Unggah Bukti (Foto/PDF)"}
                          </span>
                          <input
                            type="file"
                            accept="image/jpeg,image/png,image/webp,application/pdf"
                            className="hidden"
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              if (file) uploadEvidenceMutation.mutate({ docId: doc.id, file });
                            }}
                          />
                        </label>
                      )}

                      {isManager && (
                        <>
                          <button
                            type="button"
                            disabled={!doc.has_evidence_file || reviewDocMutation.isPending}
                            onClick={() =>
                              reviewDocMutation.mutate({
                                docId: doc.id,
                                decision: "VERIFIED_MATCH",
                              })
                            }
                            className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-1.5 font-semibold text-white hover:bg-emerald-800 disabled:opacity-40"
                          >
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            Tandai Cocok
                          </button>
                          <button
                            type="button"
                            disabled={reviewDocMutation.isPending}
                            onClick={() =>
                              reviewDocMutation.mutate({
                                docId: doc.id,
                                decision: "DISCREPANCY_FLAGGED",
                              })
                            }
                            className="inline-flex items-center gap-1 rounded-lg border border-rose-300 bg-rose-50 px-3 py-1.5 font-semibold text-rose-800 hover:bg-rose-100"
                          >
                            <XCircle className="h-3.5 w-3.5" />
                            Tandai Ada Selisih
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* TAB 3: PENERIMAAN BARANG */}
      {tab === "receipts" && (
        <div className="space-y-4">
          {receiptFeedback && (
            <div
              className={`rounded-lg border px-4 py-2.5 text-xs font-medium ${
                receiptFeedback.tone === "ok"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                  : "border-rose-200 bg-rose-50 text-rose-900"
              }`}
            >
              {receiptFeedback.text}
            </div>
          )}

          {isCustodian ? (
            <section className="rounded-xl border border-[#DCE6DE] bg-white p-4 shadow-sm">
              <h2 className="text-sm font-bold text-[#16354A]">
                Catat Penerimaan Barang Fisik ke Stok Dapur
              </h2>
              <p className="mt-0.5 text-xs text-slate-600">
                Hanya barang berkondisi Baik dengan tanggal kedaluwarsa yang masuk ke stok siap pakai. Tanpa kedaluwarsa atau rusak tidak dihitung siap pakai.
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">Bahan *</label>
                  <select
                    value={receiptIngCode}
                    onChange={(e) => setReceiptIngCode(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs"
                  >
                    {(inventoryQuery.data?.items ?? []).map((i) => (
                      <option key={i.code} value={i.code}>
                        {i.name} ({i.code})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    Jumlah Diterima *
                  </label>
                  <div className="mt-1 flex gap-1.5">
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      value={receiptQty}
                      onChange={(e) => setReceiptQty(e.target.value)}
                      placeholder="10"
                      className="w-full rounded-lg border border-slate-300 px-2.5 py-2 text-xs"
                    />
                    <select
                      value={receiptUnit}
                      onChange={(e) => setReceiptUnit(e.target.value)}
                      className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-xs"
                    >
                      <option value="kg">kg</option>
                      <option value="g">g</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    Tanggal Kedaluwarsa
                  </label>
                  <input
                    type="date"
                    value={receiptExpiry}
                    onChange={(e) => setReceiptExpiry(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">Kondisi *</label>
                  <select
                    value={receiptCondition}
                    onChange={(e) => setReceiptCondition(e.target.value as GoodsConditionEnum)}
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs"
                  >
                    <option value="GOOD">Baik (Layak Pakai)</option>
                    <option value="DAMAGED">Rusak</option>
                    <option value="QUARANTINED">Karantina</option>
                    <option value="REJECTED">Ditolak</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    Terkait Catatan Belanja (opsional)
                  </label>
                  <select
                    value={receiptDocId}
                    onChange={(e) => setReceiptDocId(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-xs"
                  >
                    <option value="">— Tanpa tautan dokumen —</option>
                    {(docsQuery.data ?? []).map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.supplier_name} ({formatJakartaDate(d.purchase_date)})
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">Kode Lot</label>
                  <input
                    type="text"
                    value={receiptLotCode}
                    onChange={(e) => setReceiptLotCode(e.target.value)}
                    placeholder="Otomatis jika dikosongkan"
                    className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">
                    Pemasok Nyata
                  </label>
                  <input
                    type="text"
                    value={receiptSupplier}
                    onChange={(e) => setReceiptSupplier(e.target.value)}
                    placeholder="Sesuai surat jalan"
                    className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-2 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-700">Catatan</label>
                  <input
                    type="text"
                    value={receiptNotes}
                    onChange={(e) => setReceiptNotes(e.target.value)}
                    placeholder="Suhu / kondisi kemasan..."
                    className="mt-1 w-full rounded-lg border border-slate-300 px-2.5 py-2 text-xs"
                  />
                </div>
              </div>
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => createReceiptMutation.mutate()}
                  disabled={createReceiptMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58]"
                >
                  {createReceiptMutation.isPending && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  )}
                  Catat Penerimaan Barang
                </button>
              </div>
            </section>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
              Pencatatan penerimaan barang ke buku besar stok hanya dapat dilakukan oleh Petugas QC Pengelola Stok aktif.
            </div>
          )}

          {receiptsQuery.isLoading ? (
            <LoadingSkeleton rows={3} />
          ) : (receiptsQuery.data?.length ?? 0) === 0 ? (
            <EmptyState
              title="Belum ada catatan penerimaan barang"
              description="Penerimaan barang baru yang dicatat oleh Petugas QC Pengelola Stok akan langsung masuk ke tabel stok."
            />
          ) : (
            <div className="space-y-2.5" data-testid="goods-receipts-list">
              {receiptsQuery.data!.map((gr) => (
                <div key={gr.id} className="rounded-xl border border-[#DCE6DE] bg-white p-4 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-bold text-slate-900">
                      {gr.ingredient_name} — {(gr.received_raw_g / 1000).toFixed(2)} kg
                    </span>
                    <StatusBadge
                      label={conditionLabel(gr.condition_status)}
                      tone={gr.usable_added_raw_g > 0 ? "success" : "warning"}
                    />
                  </div>
                  <p className="mt-1 text-slate-600">
                    Lot <span className="font-mono font-semibold">{gr.lot_code}</span> · Pemasok:{" "}
                    {gr.supplier_name ?? "Belum dicatat"} · Diterima{" "}
                    {formatJakartaDateTime(gr.received_at)} · Siap pakai bertambah{" "}
                    <strong>{(gr.usable_added_raw_g / 1000).toFixed(2)} kg</strong>
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ShoppingListPage() {
  return (
    <Suspense fallback={<LoadingSkeleton rows={4} />}>
      <ShoppingListContent />
    </Suspense>
  );
}
