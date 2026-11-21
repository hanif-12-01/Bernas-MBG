"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Database,
  Download,
  FileSpreadsheet,
  Loader2,
  Moon,
  Server,
  ShieldCheck,
  Sun,
  Upload,
} from "lucide-react";

import { AccessDeniedState } from "@/components/feedback/FeedbackStates";
import { PageHeader } from "@/components/layout/AppShell";
import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { useWorkspace } from "@/hooks/useWorkspace";
import { API_BASE_URL, apiClient, ApiError } from "@/lib/api/client";
import { formatDateTimeID } from "@/lib/formatters/indonesian";
import type {
  CSVRowError,
  DatasetImportResponse,
  InventoryTransactionImportResponse,
  MarketReferenceImportResponse,
} from "@/types/api";

export default function SettingsPage() {
  const { user } = useAuth();
  if (user && user.active_role === "QC_OFFICER") {
    return (
      <div className="space-y-6">
        <PageHeader title="Data & Pengaturan" />
        <AccessDeniedState
          title="Pengaturan Dataset Tidak Tersedia untuk Petugas QC"
          description="Pengelolaan dataset pengadaan hanya tersedia untuk Perencana Menu dan Kepala Dapur (baca-saja)."
        />
      </div>
    );
  }
  return <SettingsContent canImport={user?.active_role === "MENU_PLANNER"} />;
}

function SettingsContent({ canImport }: { canImport: boolean }) {
  const qc = useQueryClient();
  const { theme, setTheme } = useTheme();
  const { health, healthError, datasets, activeDataset } = useWorkspace();

  const [datasetName, setDatasetName] = useState("");
  const [isSynthetic, setIsSynthetic] = useState(true);
  const [ingFile, setIngFile] = useState<File | null>(null);
  const [priceFile, setPriceFile] = useState<File | null>(null);
  const [stockFile, setStockFile] = useState<File | null>(null);
  const [recipeFile, setRecipeFile] = useState<File | null>(null);

  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<CSVRowError[]>([]);
  const [importResult, setImportResult] = useState<DatasetImportResponse | null>(null);

  // Pilot / Batch Inventory Transactions Import State
  const [txDatasetId, setTxDatasetId] = useState<string>("");
  const [txFile, setTxFile] = useState<File | null>(null);
  const [txClass, setTxClass] = useState<"synthetic" | "pilot_real">("synthetic");
  const [txAuthorized, setTxAuthorized] = useState(false);
  const [txUploading, setTxUploading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);
  const [txResult, setTxResult] = useState<InventoryTransactionImportResponse | null>(null);

  // Market Price Reference Import State
  const [mktSourceName, setMktSourceName] = useState("Referensi Harga Pangan Resmi (Impor Manual)");
  const [mktFile, setMktFile] = useState<File | null>(null);
  const [mktUploading, setMktUploading] = useState(false);
  const [mktError, setMktError] = useState<string | null>(null);
  const [mktResult, setMktResult] = useState<MarketReferenceImportResponse | null>(null);

  const sourcesQuery = useQuery({
    queryKey: ["inventory-sources"],
    queryFn: () => apiClient.listInventorySources(),
  });

  const handleTxImport = async (dryRun: boolean) => {
    setTxError(null);
    setTxResult(null);
    if (!txFile) {
      setTxError("Pilih file CSV transaksi stok terlebih dahulu.");
      return;
    }
    const fd = new FormData();
    fd.append("transactions_file", txFile);
    if (txDatasetId || activeDataset?.id) {
      fd.append("dataset_version_id", txDatasetId || activeDataset?.id || "");
    }
    fd.append("data_classification", txClass);
    fd.append("authorization_confirmed", String(txAuthorized));
    fd.append("dry_run", String(dryRun));
    setTxUploading(true);
    try {
      const res = await apiClient.importInventoryTransactions(fd);
      setTxResult(res);
      if (!dryRun) {
        qc.invalidateQueries({ queryKey: ["inventory"] });
      }
    } catch (err) {
      setTxError(err instanceof Error ? err.message : "Gagal memproses transaksi stok.");
    } finally {
      setTxUploading(false);
    }
  };

  const handleMarketImport = async (e: React.FormEvent) => {
    e.preventDefault();
    setMktError(null);
    setMktResult(null);
    if (!mktFile) {
      setMktError("Pilih file CSV referensi harga pasar terlebih dahulu.");
      return;
    }
    const fd = new FormData();
    fd.append("market_file", mktFile);
    fd.append("source_name", mktSourceName.trim() || "Referensi Harga Pasar Resmi");
    fd.append("price_provenance", "OFFICIAL_MARKET_REFERENCE");
    setMktUploading(true);
    try {
      const res = await apiClient.importMarketReferences(fd);
      setMktResult(res);
      qc.invalidateQueries({ queryKey: ["inventory"] });
    } catch (err) {
      setMktError(err instanceof Error ? err.message : "Gagal mengimpor referensi harga pasar.");
    } finally {
      setMktUploading(false);
    }
  };

  const handleImport = async (e: React.FormEvent) => {
    e.preventDefault();
    setUploadError(null);
    setRowErrors([]);
    setImportResult(null);

    if (!ingFile || !priceFile || !stockFile || !recipeFile) {
      setUploadError(
        "Lengkapi keempat file CSV (Bahan, Harga, Stok, dan Resep) sebelum mengunggah."
      );
      return;
    }

    const fd = new FormData();
    fd.append("name", datasetName.trim() || "Dataset Impor CSV");
    fd.append("source_type", isSynthetic ? "synthetic" : "uploaded");
    fd.append("is_synthetic", String(isSynthetic));
    fd.append("ingredients_file", ingFile);
    fd.append("prices_file", priceFile);
    fd.append("stock_file", stockFile);
    fd.append("recipes_file", recipeFile);

    setIsUploading(true);
    try {
      const res = await apiClient.importDatasetCsv(fd);
      setImportResult(res);
      qc.invalidateQueries({ queryKey: ["datasets"] });
    } catch (err) {
      if (err instanceof ApiError) {
        setUploadError(err.message);
        if (err.rowErrors) setRowErrors(err.rowErrors);
      } else {
        setUploadError("Gagal mengunggah dataset CSV ke server.");
      }
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data & Pengaturan"
        subtitle="Kelola versi dataset bahan pangan, impor paket CSV tervalidasi, dan pantau status koneksi server backend."
        badges={<DatasetSimulationNotice compact simulationOnly={health?.simulation_only ?? true} />}
      />

      {/* Appearance / Theme Selection Card */}
      <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#DCE6DE] bg-white p-5">
        <div>
          <h2 className="text-base font-bold text-[#16354A]">Tema Tampilan Aplikasi</h2>
          <p className="mt-0.5 text-xs text-[#647A87]">
            Pilih mode terang (Light) atau mode gelap (Dark). Preferensi tersimpan otomatis di browser ini.
          </p>
        </div>
        <div
          role="group"
          aria-label="Pilih tema tampilan"
          className="inline-flex rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-1"
        >
          <button
            type="button"
            onClick={() => setTheme("light")}
            aria-pressed={theme === "light"}
            className={`inline-flex min-h-[40px] items-center gap-1.5 rounded-lg px-3.5 text-xs font-semibold transition-colors ${
              theme === "light"
                ? "bg-[#0F766E] text-white shadow-xs"
                : "text-[#4A6170] hover:text-[#16354A]"
            }`}
          >
            <Sun className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Terang (Light)</span>
          </button>
          <button
            type="button"
            onClick={() => setTheme("dark")}
            aria-pressed={theme === "dark"}
            className={`inline-flex min-h-[40px] items-center gap-1.5 rounded-lg px-3.5 text-xs font-semibold transition-colors ${
              theme === "dark"
                ? "bg-[#0F766E] text-white shadow-xs"
                : "text-[#4A6170] hover:text-[#16354A]"
            }`}
          >
            <Moon className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Gelap (Dark)</span>
          </button>
        </div>
      </section>

      {/* Connection & Active Dataset Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <Server className="h-5 w-5 text-[#0F766E]" aria-hidden="true" />
              <h2 className="text-base font-bold text-[#16354A]">Status Koneksi Server</h2>
            </div>
            <StatusBadge
              tone={healthError ? "critical" : health ? "success" : "neutral"}
              label={healthError ? "Terputus" : health ? "Terhubung" : "Memeriksa"}
            />
          </div>
          <dl className="mt-4 space-y-2 text-xs text-[#4A6170]">
            <div className="flex justify-between">
              <dt className="text-[#647A87]">Alamat API Backend</dt>
              <dd className="font-mono font-semibold text-[#16354A]">{API_BASE_URL}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-[#647A87]">Versi Model Optimasi</dt>
              <dd className="font-semibold text-[#16354A]">{health?.model_version ?? "—"}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-[#647A87]">Penyimpanan Persisten</dt>
              <dd className="font-semibold text-[#16354A]">
                {health?.persistence ? health.persistence.toUpperCase() : "—"}
              </dd>
            </div>
          </dl>
        </section>

        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <Database className="h-5 w-5 text-[#0F766E]" aria-hidden="true" />
              <h2 className="text-base font-bold text-[#16354A]">Dataset Aktif Saat Ini</h2>
            </div>
            <StatusBadge tone="teal" label="Aktif" />
          </div>
          {activeDataset ? (
            <dl className="mt-4 space-y-2 text-xs text-[#4A6170]">
              <div className="flex justify-between gap-2">
                <dt className="text-[#647A87]">Nama Dataset</dt>
                <dd className="text-right font-semibold text-[#16354A]">{activeDataset.name}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#647A87]">Status Data</dt>
                <dd className="font-semibold text-[#8A5300]">
                  {activeDataset.is_synthetic ? "Data Simulasi (DEMO_ONLY)" : activeDataset.source_type}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-[#647A87]">Dibuat Pada</dt>
                <dd className="font-semibold text-[#16354A]">
                  {formatDateTimeID(activeDataset.created_at)}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="mt-4 text-xs text-[#647A87]">Belum ada dataset aktif terdeteksi.</p>
          )}
        </section>
      </div>

      {/* CSV Import Form (MENU_PLANNER only) */}
      {canImport ? (
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 shadow-[0_1px_2px_rgba(22,53,74,0.04)]">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#EBF6F5] text-[#0F766E]">
            <FileSpreadsheet className="h-5 w-5" aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-base font-bold text-[#16354A]">Impor Paket Dataset CSV Baru</h2>
            <p className="mt-0.5 text-xs leading-relaxed text-[#647A87]">
              Impor baru akan divalidasi secara menyeluruh per baris (unit harga, nilai gizi tanpa
              nilai kosong/NaN, dan kecocokan kode bahan) lalu disimpan sebagai{" "}
              <strong>versi immutable terpisah</strong> tanpa menimpa dataset aktif saat ini.
            </p>
          </div>
        </div>

        <form onSubmit={handleImport} className="mt-5 space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="ds-name" className="block text-xs font-semibold text-[#4A6170]">
                Nama Versi Dataset
              </label>
              <input
                id="ds-name"
                type="text"
                value={datasetName}
                onChange={(e) => setDatasetName(e.target.value)}
                required
                className="mt-1.5 h-10 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
              />
            </div>

            <div className="flex items-end">
              <label className="flex min-h-[40px] cursor-pointer items-center gap-2.5 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] px-3.5 py-2 text-xs font-medium text-[#16354A]">
                <input
                  type="checkbox"
                  checked={isSynthetic}
                  onChange={(e) => setIsSynthetic(e.target.checked)}
                  className="h-4 w-4 accent-[#0F766E]"
                />
                <span>Tandai sebagai Data Simulasi (DEMO_ONLY)</span>
              </label>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
            <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-3.5">
              <label htmlFor="file-ing" className="block text-xs font-bold text-[#16354A]">
                1. File Bahan & Gizi (<code className="font-mono font-semibold">ingredients.csv</code>)
              </label>
              <p className="mt-0.5 text-[11px] text-[#647A87]">
                Kolom wajib: code, name, category, edible_fraction, energy_kcal_100g, protein_g_100g, fat_g_100g, carb_g_100g
              </p>
              <input
                id="file-ing"
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setIngFile(e.target.files?.[0] ?? null)}
                className="mt-2 block w-full text-xs text-[#4A6170] file:mr-3 file:rounded-lg file:border-0 file:bg-[#EBF6F5] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-[#0F766E]"
              />
            </div>

            <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-3.5">
              <label htmlFor="file-price" className="block text-xs font-bold text-[#16354A]">
                2. File Harga Bahan (<code className="font-mono font-semibold">prices.csv</code>)
              </label>
              <p className="mt-0.5 text-[11px] text-[#647A87]">
                Kolom wajib: ingredient_code + (price_idr_per_kg atau price_value, unit). Unit liter wajib density_g_per_ml.
              </p>
              <input
                id="file-price"
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setPriceFile(e.target.files?.[0] ?? null)}
                className="mt-2 block w-full text-xs text-[#4A6170] file:mr-3 file:rounded-lg file:border-0 file:bg-[#EBF6F5] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-[#0F766E]"
              />
            </div>

            <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-3.5">
              <label htmlFor="file-stock" className="block text-xs font-bold text-[#16354A]">
                3. File Stok Mentah (<code className="font-mono font-semibold">stock.csv</code>)
              </label>
              <p className="mt-0.5 text-[11px] text-[#647A87]">
                Kolom wajib: ingredient_code, stock_raw_g (dalam gram, nilai &ge; 0).
              </p>
              <input
                id="file-stock"
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setStockFile(e.target.files?.[0] ?? null)}
                className="mt-2 block w-full text-xs text-[#4A6170] file:mr-3 file:rounded-lg file:border-0 file:bg-[#EBF6F5] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-[#0F766E]"
              />
            </div>

            <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5]/60 p-3.5">
              <label htmlFor="file-rec" className="block text-xs font-bold text-[#16354A]">
                4. File Varian Resep (<code className="font-mono font-semibold">recipes.csv</code>)
              </label>
              <p className="mt-0.5 text-[11px] text-[#647A87]">
                Kolom wajib: recipe_code, recipe_name, slot, ingredient_code, raw_g_per_serving, retention_factor, review_status
              </p>
              <input
                id="file-rec"
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setRecipeFile(e.target.files?.[0] ?? null)}
                className="mt-2 block w-full text-xs text-[#4A6170] file:mr-3 file:rounded-lg file:border-0 file:bg-[#EBF6F5] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-[#0F766E]"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isUploading}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#0F766E] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
          >
            {isUploading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                <span>Memvalidasi & Mengimpor CSV...</span>
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" aria-hidden="true" />
                <span>Validasi & Impor Paket CSV</span>
              </>
            )}
          </button>
        </form>

        {/* Success Feedback */}
        {importResult && (
          <div
            role="status"
            className="mt-4 rounded-xl border border-[#BBE9CC] bg-[#ECFDF3] p-4 text-xs text-[#166534]"
          >
            <div className="flex items-start gap-2.5">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-bold">
                  Dataset &ldquo;{importResult.name}&rdquo; berhasil disimpan sebagai versi baru!
                </p>
                <p className="mt-1">
                  Tersimpan: {importResult.ingredients_imported} bahan,{" "}
                  {importResult.prices_imported} harga, {importResult.stock_items_imported} stok,{" "}
                  {importResult.recipes_imported} resep ({importResult.reviewed_recipes_count}{" "}
                  berstatus reviewed).
                </p>
                <Link href={`/menu-planning?dataset=${encodeURIComponent(importResult.dataset_version_id)}`}
                  className="mt-2 inline-flex min-h-[44px] items-center font-bold text-[#0F766E] underline">
                  Gunakan Dataset Ini untuk Rencana Baru
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* Validation Errors Table */}
        {uploadError && (
          <div
            role="alert"
            className="mt-4 rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-4 text-xs text-[#991B1B]"
          >
            <div className="flex items-start gap-2.5">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div className="w-full">
                <p className="font-bold">{uploadError}</p>
                {rowErrors.length > 0 && (
                  <div className="mt-3 overflow-x-auto rounded-lg border border-[#F5C2C2] bg-white">
                    <table className="w-full text-left text-xs">
                      <thead className="border-b border-[#F5C2C2] bg-[#FFF5F5] text-[#991B1B]">
                        <tr>
                          <th className="px-3 py-2 font-semibold">File</th>
                          <th className="px-3 py-2 font-semibold">Baris</th>
                          <th className="px-3 py-2 font-semibold">Kolom</th>
                          <th className="px-3 py-2 font-semibold">Keterangan Error</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#FEE2E2] text-[#7F1D1D]">
                        {rowErrors.map((err, i) => (
                          <tr key={i}>
                            <td className="px-3 py-2 font-mono">{err.file}</td>
                            <td className="px-3 py-2 tabular-nums">{err.row}</td>
                            <td className="px-3 py-2 font-mono">{err.field}</td>
                            <td className="px-3 py-2">{err.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </section>
      ) : (
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-4 text-xs text-[#4A6170]">
          Impor dataset CSV hanya tersedia untuk peran <strong>Perencana Menu</strong>. Anda dapat
          meninjau versi dataset tersimpan di bawah ini secara baca-saja.
        </section>
      )}

      {/* Persisted Dataset Versions Table */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
        <h2 className="text-base font-bold text-[#16354A]">
          Daftar Versi Dataset Tersimpan ({datasets.length})
        </h2>
        <p className="mt-0.5 text-xs text-[#647A87]">
          Seluruh versi dataset disimpan secara immutable untuk menjamin keterlacakan hasil optimasi.
        </p>
        {datasets.length === 0 && <p className="mt-4 text-sm text-[#647A87]">Belum ada versi dataset untuk dapur ini.</p>}
        <ul className="mt-4 space-y-2 md:hidden" aria-label="Versi dataset">
          {datasets.map((dataset) => (
            <li key={dataset.id} className="rounded-xl border border-[#DCE6DE] p-3">
              <h3 className="break-words text-sm font-bold">{dataset.name}</h3>
              <p className="mt-1 text-xs text-[#647A87]">
                {dataset.is_synthetic ? "Simulasi (DEMO_ONLY)" : dataset.source_type} • {formatDateTimeID(dataset.created_at)}
              </p>
              {canImport && (
                <Link href={`/menu-planning?dataset=${encodeURIComponent(dataset.id)}`}
                  className="inline-flex min-h-[44px] items-center text-sm font-semibold text-[#0F766E] underline">
                  Gunakan untuk Rencana Baru
                </Link>
              )}
            </li>
          ))}
        </ul>
        <div className="mt-4 hidden overflow-x-auto md:block">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#DCE6DE] text-[#647A87]">
              <tr>
                <th className="pb-2.5 pr-3 font-semibold">Nama Dataset</th>
                <th className="pb-2.5 pr-3 font-semibold">Jenis Sumber</th>
                <th className="pb-2.5 pr-3 font-semibold">Status</th>
                <th className="pb-2.5 font-semibold">Tanggal Dibuat</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EEF3EE]">
              {datasets.map((ds) => (
                <tr key={ds.id}>
                  <td className="py-2.5 pr-3 font-semibold text-[#16354A]">
                    {ds.name}
                    {canImport && (
                      <Link href={`/menu-planning?dataset=${encodeURIComponent(ds.id)}`}
                        className="block min-h-[44px] py-2 text-[#0F766E] underline">Gunakan untuk Rencana Baru</Link>
                    )}
                  </td>
                  <td className="py-2.5 pr-3 text-[#4A6170]">
                    {ds.is_synthetic ? "Simulasi (DEMO_ONLY)" : ds.source_type}
                  </td>
                  <td className="py-2.5 pr-3">
                    <StatusBadge
                      tone={ds.is_active ? "teal" : "neutral"}
                      label={ds.is_active ? "Aktif" : "Versi Tersimpan"}
                    />
                  </td>
                  <td className="py-2.5 text-[#4A6170]">{formatDateTimeID(ds.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Pilot & Market Reference Templates + Importers */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 space-y-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 className="text-base font-bold text-[#16354A]">
                Impor Transaksi Stok &amp; Pilot Dapur (Idempoten)
              </h2>
              <p className="mt-0.5 text-xs text-[#647A87]">
                Pratinjau dan unggah mutasi batch, kerusakan, reservasi, hitung fisik, serta
                penerimaan pemasok terotorisasi dengan deteksi duplikasi &amp; karantina satuan.
              </p>
            </div>
            <a
              href={apiClient.getInventoryTemplateUrl("pilot-transactions")}
              className="inline-flex min-h-[36px] shrink-0 items-center gap-1.5 rounded-lg border border-[#B5DFDA] bg-[#EBF6F5] px-3 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#DDF0EE]"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Templat CSV</span>
            </a>
          </div>

          {canImport ? (
            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="tx-ds" className="block font-semibold text-[#4A6170]">
                    Dataset Target
                  </label>
                  <select
                    id="tx-ds"
                    value={txDatasetId || activeDataset?.id || ""}
                    onChange={(e) => setTxDatasetId(e.target.value)}
                    className="mt-1 h-10 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                  >
                    {datasets.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="tx-cls" className="block font-semibold text-[#4A6170]">
                    Klasifikasi Sumber
                  </label>
                  <select
                    id="tx-cls"
                    value={txClass}
                    onChange={(e) => setTxClass(e.target.value as "synthetic" | "pilot_real")}
                    className="mt-1 h-10 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                  >
                    <option value="synthetic">Data Simulasi / Uji (synthetic)</option>
                    <option value="pilot_real">Data Dapur Pilot Terotorisasi (pilot_real)</option>
                  </select>
                </div>
              </div>

              {txClass === "pilot_real" && (
                <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-[#F3D19B] bg-[#FFFBEB] p-3 text-xs text-[#92400E]">
                  <input
                    type="checkbox"
                    checked={txAuthorized}
                    onChange={(e) => setTxAuthorized(e.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-[#0F766E]"
                  />
                  <span>
                    Saya mengonfirmasi otorisasi resmi dapur untuk mengunggah catatan pilot nyata
                    (tanpa data penerima pribadi dan tidak otomatis mengubah menu yang sudah
                    disetujui).
                  </span>
                </label>
              )}

              <div>
                <label htmlFor="file-tx" className="block font-semibold text-[#4A6170]">
                  File CSV Transaksi Stok
                </label>
                <input
                  id="file-tx"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setTxFile(e.target.files?.[0] ?? null)}
                  className="mt-1.5 block w-full text-xs text-[#4A6170] file:mr-3 file:rounded-lg file:border-0 file:bg-[#EBF6F5] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-[#0F766E]"
                />
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={txUploading}
                  onClick={() => handleTxImport(true)}
                  className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-[#B5DFDA] bg-white px-4 py-2 text-xs font-semibold text-[#0F766E] hover:bg-[#EBF6F5] disabled:opacity-60"
                >
                  <span>Pratinjau Validasi (Dry Run)</span>
                </button>
                <button
                  type="button"
                  disabled={txUploading}
                  onClick={() => handleTxImport(false)}
                  className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
                >
                  <span>Terapkan ke Buku Stok</span>
                </button>
              </div>

              {txError && (
                <div role="alert" className="rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-3 text-[#991B1B]">
                  {txError}
                </div>
              )}
              {txResult && (
                <div role="status" className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3 text-[#16354A]">
                  <p className="font-bold">
                    {txResult.dry_run ? "Hasil Pratinjau (Dry Run)" : "Impor Transaksi Selesai"}:{" "}
                    {txResult.applied_count} diterapkan/valid, {txResult.duplicate_skipped_count}{" "}
                    duplikat dilewati, {txResult.quarantined_count} dikarantina,{" "}
                    {txResult.error_count} error.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-[#647A87]">
              Impor transaksi inventaris hanya dapat dijalankan oleh Perencana Menu.
            </p>
          )}
        </section>

        <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5 space-y-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 className="text-base font-bold text-[#16354A]">
                Referensi Harga Pangan Indonesia (Terpisah dari Stok)
              </h2>
              <p className="mt-0.5 text-xs text-[#647A87]">
                Impor manual CSV resmi (mis. ekspor sah Bapanas SAPA / Panel Harga). Data ini hanya
                menjadi pembanding dan tidak pernah mengubah stok dapur atau harga kontrak pemasok.
              </p>
            </div>
            <a
              href={apiClient.getInventoryTemplateUrl("market-references")}
              className="inline-flex min-h-[36px] shrink-0 items-center gap-1.5 rounded-lg border border-[#B5DFDA] bg-[#EBF6F5] px-3 py-1.5 text-xs font-semibold text-[#0F766E] hover:bg-[#DDF0EE]"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Templat CSV</span>
            </a>
          </div>

          {canImport ? (
            <form onSubmit={handleMarketImport} className="space-y-3 text-xs">
              <div>
                <label htmlFor="mkt-src" className="block font-semibold text-[#4A6170]">
                  Nama Sumber Resmi
                </label>
                <input
                  id="mkt-src"
                  type="text"
                  value={mktSourceName}
                  onChange={(e) => setMktSourceName(e.target.value)}
                  className="mt-1 h-10 w-full rounded-xl border border-[#DCE6DE] bg-white px-3 text-sm text-[#16354A]"
                />
              </div>
              <div>
                <label htmlFor="file-mkt" className="block font-semibold text-[#4A6170]">
                  File CSV Referensi Pasar
                </label>
                <input
                  id="file-mkt"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setMktFile(e.target.files?.[0] ?? null)}
                  className="mt-1.5 block w-full text-xs text-[#4A6170] file:mr-3 file:rounded-lg file:border-0 file:bg-[#EBF6F5] file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-[#0F766E]"
                />
              </div>
              <button
                type="submit"
                disabled={mktUploading}
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl bg-[#0F766E] px-4 py-2 text-xs font-semibold text-white hover:bg-[#0B5F58] disabled:opacity-60"
              >
                <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Impor Referensi Harga Pasar</span>
              </button>
              {mktError && (
                <div role="alert" className="rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-3 text-[#991B1B]">
                  {mktError}
                </div>
              )}
              {mktResult && (
                <div role="status" className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3 text-[#16354A]">
                  <p className="font-bold">
                    {mktResult.imported_count} referensi harga pasar diimpor ({mktResult.skipped_count} dilewati).
                  </p>
                  {mktResult.warnings[0] && <p className="mt-1 text-[11px]">{mktResult.warnings[0]}</p>}
                </div>
              )}
            </form>
          ) : (
            <p className="text-xs text-[#647A87]">
              Impor referensi harga pasar hanya tersedia untuk Perencana Menu.
            </p>
          )}
        </section>
      </div>

      {/* Audit Sumber Data & Lisensi */}
      <section className="rounded-2xl border border-[#DCE6DE] bg-white p-5">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-[#0F766E]" aria-hidden="true" />
          <h2 className="text-base font-bold text-[#16354A]">
            Katalog Audit Sumber Data &amp; Izin Penggunaan
          </h2>
        </div>
        <p className="mt-0.5 text-xs text-[#647A87]">
          Sumber eksternal tanpa izin redistribusi hanya dipakai sebagai referensi model konseptual;
          portal pemerintah terbatas hanya didukung melalui impor manual resmi.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#DCE6DE] text-[#647A87]">
              <tr>
                <th className="pb-2 pr-3 font-semibold">Nama Sumber</th>
                <th className="pb-2 pr-3 font-semibold">Jenis</th>
                <th className="pb-2 pr-3 font-semibold">Lisensi / Akses</th>
                <th className="pb-2 font-semibold">Kebijakan Penggunaan</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EEF3EE]">
              {(sourcesQuery.data ?? []).map((src) => (
                <tr key={src.id}>
                  <td className="py-2 pr-3 font-semibold text-[#16354A]">{src.source_name}</td>
                  <td className="py-2 pr-3 text-[#4A6170]">{src.dataset_type}</td>
                  <td className="py-2 pr-3 font-mono text-[11px] text-[#4A6170]">{src.license}</td>
                  <td className="py-2 text-[#4A6170]">{src.allowed_use}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
