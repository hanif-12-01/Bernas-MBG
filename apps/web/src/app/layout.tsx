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

const THEME_INIT_SCRIPT = `
(function() {
  try {
    var saved = localStorage.getItem('gizioptima_theme');
    var useDark = saved === 'dark' || (!saved && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var root = document.documentElement;
    if (useDark) {
      root.classList.add('dark');
      root.style.colorScheme = 'dark';
    } else {
      root.classList.remove('dark');
      root.style.colorScheme = 'light';
    }
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className={plusJakarta.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-[#F5F8F5] font-sans text-[#16354A] antialiased dark:bg-[#0B1319] dark:text-[#EBF2F6]">
        <AppProviders>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
