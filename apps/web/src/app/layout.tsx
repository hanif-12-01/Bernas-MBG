import type { Metadata } from "next";
import localFont from "next/font/local";
import React from "react";

import { AppShell } from "@/components/layout/AppShell";
import { AppProviders } from "@/hooks/useWorkspace";
import "./globals.css";

const plusJakarta = localFont({
  src: "./fonts/plus-jakarta-sans-latin.woff2",
  weight: "400 700",
  variable: "--font-plus-jakarta",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GiziOptima — Perencanaan Menu & Pengadaan Adaptif",
  description:
    "Sistem pendukung keputusan untuk merencanakan menu bergizi berbasis resep terverifikasi, mengelola biaya, dan mensimulasikan perubahan harga serta stok bahan pangan.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className={plusJakarta.variable}>
      <body className="min-h-screen bg-[#F5F8F5] font-sans text-[#16354A] antialiased">
        <AppProviders>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
