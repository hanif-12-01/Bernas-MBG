"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, Loader2, LogIn, ShieldCheck, Sprout } from "lucide-react";

import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useAuth } from "@/hooks/useAuth";
import { ApiError } from "@/lib/api/client";

export default function LoginPage() {
  const router = useRouter();
  const { isAuthenticated, isLoadingAuth, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoadingAuth && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isAuthenticated, isLoadingAuth, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Masukkan nama pengguna dan kata sandi Anda.");
      return;
    }

    setSubmitting(true);
    try {
      await login(username.trim(), password);
      router.replace("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Gagal masuk. Periksa koneksi server dan coba lagi.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-[#F5F8F5] px-4 py-10">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#0F766E] text-white shadow-sm">
            <Sprout className="h-6 w-6" aria-hidden="true" />
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-[#16354A]">
            GiziOptima
          </h1>
          <p className="mt-1 text-sm text-[#4A6170]">
            Operasional Dapur, Perencanaan Menu & Pemeriksaan Visual AI
          </p>
        </div>

        <div className="rounded-2xl border border-[#DCE6DE] bg-white p-6 shadow-[0_2px_8px_rgba(22,53,74,0.06)]">
          <div className="flex items-center justify-between gap-2 border-b border-[#EEF3EE] pb-4">
            <div>
              <h2 className="text-base font-bold text-[#16354A]">Masuk ke Akun Dapur</h2>
              <p className="text-xs text-[#647A87]">
                Hak akses menu dan data disesuaikan otomatis dengan peran Anda.
              </p>
            </div>
            <ShieldCheck className="h-5 w-5 shrink-0 text-[#0F766E]" aria-hidden="true" />
          </div>

          <form onSubmit={handleSubmit} className="mt-5 space-y-4">
            <div>
              <label
                htmlFor="login-username"
                className="block text-xs font-semibold text-[#4A6170]"
              >
                Nama Pengguna atau Email
              </label>
              <input
                id="login-username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Nama pengguna atau email"
                className="mt-1.5 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3.5 text-sm text-[#16354A] focus:border-[#0F766E] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E]/30"
              />
            </div>

            <div>
              <label
                htmlFor="login-password"
                className="block text-xs font-semibold text-[#4A6170]"
              >
                Kata Sandi
              </label>
              <input
                id="login-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Masukkan kata sandi akun Anda"
                className="mt-1.5 h-11 w-full rounded-xl border border-[#DCE6DE] bg-white px-3.5 text-sm text-[#16354A] focus:border-[#0F766E] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E]/30"
              />
            </div>

            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-xl border border-[#F5C2C2] bg-[#FEF0F0] p-3 text-xs font-medium text-[#991B1B]"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-[#0F766E] px-4 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-[#0B5F58] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  <span>Memverifikasi sesi...</span>
                </>
              ) : (
                <>
                  <LogIn className="h-4 w-4" aria-hidden="true" />
                  <span>Masuk</span>
                </>
              )}
            </button>
          </form>

          <div className="mt-5 rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3.5 text-xs text-[#4A6170]">
            <p className="font-semibold text-[#16354A]">Peran Operasional yang Didukung:</p>
            <ul className="mt-1.5 space-y-1">
              <li>
                <strong>Perencana Menu:</strong> optimasi menu, simulasi harga/stok, pengajuan rencana.
              </li>
              <li>
                <strong>Kepala Dapur:</strong> peninjauan rencana menu, tinjauan QC, ringkasan operasional & audit.
              </li>
              <li>
                <strong>Petugas QC:</strong> foto sampel makanan, pemeriksaan visual AI, konfirmasi & pengiriman laporan.
              </li>
            </ul>
            <p className="mt-2 text-[11px] text-[#647A87]">
              Hubungi administrator dapur untuk mendapatkan akun atau mengatur ulang kata sandi.
            </p>
          </div>
        </div>

        <DatasetSimulationNotice simulationOnly />
      </div>
    </div>
  );
}
