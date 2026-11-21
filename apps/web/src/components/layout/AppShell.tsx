"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  CalendarDays,
  Camera,
  ChevronDown,
  LayoutDashboard,
  LogOut,
  Menu,
  Package,
  RefreshCw,
  Settings,
  ShoppingBasket,
  SlidersHorizontal,
  Sprout,
  UserCircle2,
  X,
} from "lucide-react";

import { DatasetSimulationNotice } from "@/components/ui/DatasetSimulationNotice";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { ErrorState } from "@/components/feedback/FeedbackStates";
import { useAuth } from "@/hooks/useAuth";
import { useWorkspace } from "@/hooks/useWorkspace";
import { formatIDR, formatRoleLabel, formatRunStatus } from "@/lib/formatters/indonesian";
import type { RoleEnum } from "@/types/api";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  allowedRoles: RoleEnum[];
}

const ALL_NAV_ITEMS: NavItem[] = [
  {
    href: "/dashboard",
    label: "Beranda",
    icon: LayoutDashboard,
    allowedRoles: ["KITCHEN_MANAGER", "MENU_PLANNER", "QC_OFFICER", "NUTRITIONIST"],
  },
  {
    href: "/menu-planning",
    label: "Rencana Menu",
    icon: CalendarDays,
    allowedRoles: ["KITCHEN_MANAGER", "MENU_PLANNER", "QC_OFFICER", "NUTRITIONIST"],
  },
  {
    href: "/kitchen-qc",
    label: "Pemeriksaan Sajian",
    icon: Camera,
    allowedRoles: ["KITCHEN_MANAGER", "MENU_PLANNER", "QC_OFFICER"],
  },
  {
    href: "/simulator",
    label: "Pemulihan & Simulasi",
    icon: SlidersHorizontal,
    allowedRoles: ["MENU_PLANNER"],
  },
  {
    href: "/inventory",
    label: "Stok Bahan",
    icon: Package,
    allowedRoles: ["KITCHEN_MANAGER", "MENU_PLANNER", "QC_OFFICER", "NUTRITIONIST"],
  },
  {
    href: "/shopping-list",
    label: "Belanja & Penerimaan",
    icon: ShoppingBasket,
    allowedRoles: ["KITCHEN_MANAGER", "MENU_PLANNER", "QC_OFFICER"],
  },
  {
    href: "/settings",
    label: "Pengaturan",
    icon: Settings,
    allowedRoles: ["KITCHEN_MANAGER", "MENU_PLANNER", "QC_OFFICER"],
  },
];

export function ScenarioSelector() {
  const { user } = useAuth();
  const { runs, scenarios, selectedRunId, setSelectedRunId, isLoadingList } = useWorkspace();
  const scenarioById = new Map(scenarios.map((s) => [s.id, s]));
  const canSeePrice = user?.active_role !== "QC_OFFICER";

  if (isLoadingList) {
    return (
      <div className="h-11 w-56 min-w-0 max-w-full animate-pulse rounded-xl bg-[#EEF3EE]" aria-label="Memuat skenario" />
    );
  }

  if (runs.length === 0) {
    return (
      <span className="inline-flex min-h-[44px] min-w-0 items-center rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] px-2 text-xs font-medium text-[#647A87] sm:px-3">
        Belum ada rencana
      </span>
    );
  }

  return (
    <div className="relative flex min-w-0 flex-1 items-center sm:flex-initial">
      <label htmlFor="global-run-selector" className="sr-only">
        Pilih rencana menu tersimpan
      </label>
      <select
        id="global-run-selector"
        value={selectedRunId ?? ""}
        onChange={(e) => setSelectedRunId(e.target.value || null)}
        className="h-11 w-full min-w-0 max-w-full appearance-none truncate rounded-xl border border-[#DCE6DE] bg-white pl-3 pr-8 text-base font-semibold text-[#16354A] shadow-[0_1px_2px_rgba(22,53,74,0.03)] hover:border-[#B5DFDA] sm:w-auto sm:max-w-[300px] sm:text-sm"
      >
        {runs.map((run) => {
          const sc = scenarioById.get(run.scenario_id);
          const status = formatRunStatus(run.solver_status, run.validation_passed);
          const costPart =
            canSeePrice && run.cost_per_serving_average_idr !== null
              ? ` • ${formatIDR(run.cost_per_serving_average_idr)}/porsi`
              : ` • ${status.shortLabel}`;
          return (
            <option key={run.run_id} value={run.run_id}>
              {(sc?.name ?? `Skenario ${run.scenario_id.slice(0, 6)}`) + costPart}
            </option>
          );
        })}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2.5 h-4 w-4 text-[#647A87]"
        aria-hidden="true"
      />
    </div>
  );
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  badges?: React.ReactNode;
  actions?: React.ReactNode;
}

export function PageHeader({ title, subtitle, badges, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col justify-between gap-4 border-b border-[#DCE6DE] pb-5 lg:flex-row lg:items-end">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-2xl font-bold tracking-tight text-[#16354A] sm:text-[26px]">
            {title}
          </h1>
          {badges}
        </div>
        {subtitle && <p className="max-w-2xl break-words text-sm leading-relaxed text-[#4A6170]">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerTrigger = useRef<HTMLButtonElement>(null);
  const closeDrawer = useRef<HTMLButtonElement>(null);
  const { user, isLoadingAuth, isAuthenticated, authError, refreshAuth, logout, switchKitchen } = useAuth();
  const { health, healthError, refreshAll } = useWorkspace();
  const [accountPending, setAccountPending] = useState(false);
  const [accountError, setAccountError] = useState("");

  const isAuthPage = pathname === "/login";

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!isAuthPage && !isLoadingAuth && !isAuthenticated && !authError) {
      router.replace("/login");
    }
  }, [isAuthPage, isLoadingAuth, isAuthenticated, authError, router]);

  useEffect(() => {
    if (!drawerOpen) return;
    const trigger = drawerTrigger.current;
    closeDrawer.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const desktop = window.matchMedia("(min-width: 1024px)");
    const handleDesktop = () => { if (desktop.matches) setDrawerOpen(false); };
    desktop.addEventListener("change", handleDesktop);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      desktop.removeEventListener("change", handleDesktop);
      document.body.style.overflow = previousOverflow;
      trigger?.focus();
    };
  }, [drawerOpen]);

  const navItems = useMemo(() => {
    if (!user) return [];
    return ALL_NAV_ITEMS.filter((item) => item.allowedRoles.includes(user.active_role));
  }, [user]);

  if (isAuthPage) {
    return <>{children}</>;
  }

  if (authError && !isAuthenticated) {
    return (
      <main className="mx-auto flex min-h-screen max-w-lg items-center px-4">
        <ErrorState title="Sesi belum dapat diperiksa" message={authError.message} onRetry={() => void refreshAuth()} />
      </main>
    );
  }

  if (isLoadingAuth || !isAuthenticated || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F5F8F5] px-4">
        <div className="flex items-center gap-3 rounded-2xl border border-[#DCE6DE] bg-white px-5 py-4 text-sm font-medium text-[#4A6170] shadow-xs">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#0F766E] border-t-transparent" />
          <span>Memeriksa sesi pengguna...</span>
        </div>
      </div>
    );
  }

  const handleLogout = async () => {
    setAccountError("");
    setAccountPending(true);
    try {
      await logout();
      router.replace("/login");
    } catch (err) {
      setAccountError(err instanceof Error ? err.message : "Gagal keluar. Silakan coba lagi.");
    } finally {
      setAccountPending(false);
    }
  };

  const handleSwitchKitchen = async (kitchenId: string) => {
    setAccountError("");
    setAccountPending(true);
    try {
      await switchKitchen(kitchenId);
      setDrawerOpen(false);
      router.replace("/dashboard");
    } catch (err) {
      setAccountError(err instanceof Error ? err.message : "Dapur belum dapat diganti.");
    } finally {
      setAccountPending(false);
    }
  };

  const sidebarContent = (mobile: boolean) => (
    <div className="flex h-full flex-col justify-between overflow-y-auto overscroll-contain bg-white">
      <div>
        <div className="flex items-center justify-between border-b border-[#DCE6DE] px-5 py-4">
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#0F766E] text-white shadow-xs">
              <Sprout className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <span className="block text-base font-bold leading-none text-[#16354A]">
                GiziOptima
              </span>
              <span className="mt-0.5 block text-[11px] font-medium text-[#647A87]">
                Operasional Dapur SPPG
              </span>
            </div>
          </Link>
          {mobile && <button
            ref={closeDrawer}
            type="button"
            onClick={() => setDrawerOpen(false)}
            className="flex h-11 w-11 items-center justify-center rounded-xl text-[#4A6170] hover:bg-[#F5F8F5]"
            aria-label="Tutup menu navigasi"
          >
            <X className="h-5 w-5" />
          </button>}
        </div>

        {/* Active Role & Kitchen Context */}
        <div className="border-b border-[#EEF3EE] bg-[#F5F8F5]/70 px-4 py-3">
          <div className="flex items-center gap-2">
            <UserCircle2 className="h-4 w-4 shrink-0 text-[#0F766E]" aria-hidden="true" />
            <span className="truncate text-xs font-bold text-[#16354A]">{user.full_name}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span className="inline-flex rounded-full bg-[#EBF6F5] px-2 py-0.5 text-[11px] font-semibold text-[#0F766E]">
              {formatRoleLabel(user.active_role)}
            </span>
            {user.active_role === "QC_OFFICER" && user.is_active_stock_custodian && (
              <span className="inline-flex rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-900">
                Pengelola Stok Aktif
              </span>
            )}
          </div>
          <p className="mt-1 truncate text-[11px] text-[#647A87]" title={user.active_kitchen_name}>
            {user.active_kitchen_name}
          </p>
          {user.memberships.length > 1 && (
            <label className="mt-2 block text-xs font-semibold text-[#4A6170]">
              Ganti dapur
              <select value={user.active_kitchen_id} disabled={accountPending}
                onChange={(event) => void handleSwitchKitchen(event.target.value)}
                className="mt-1 min-h-[44px] w-full rounded-lg border border-[#DCE6DE] bg-white px-2 text-base sm:text-sm">
                {user.memberships.map((membership) => (
                  <option key={membership.kitchen_id} value={membership.kitchen_id}>{membership.kitchen_name}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <nav aria-label="Navigasi utama" className="space-y-1 p-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-[44px] items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-semibold transition-colors ${
                  active
                    ? "bg-[#EBF6F5] text-[#0F766E]"
                    : "text-[#4A6170] hover:bg-[#F5F8F5] hover:text-[#16354A]"
                }`}
              >
                <Icon
                  className={`h-4 w-4 shrink-0 ${active ? "text-[#0F766E]" : "text-[#647A87]"}`}
                  aria-hidden="true"
                />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="space-y-3 border-t border-[#DCE6DE] p-4">
        <div className="rounded-xl border border-[#DCE6DE] bg-[#F5F8F5] p-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#16354A]">
            <span
              className={`h-2 w-2 rounded-full ${
                healthError ? "bg-[#C43D3D]" : health ? "bg-[#15803D]" : "bg-[#E9A23B]"
              }`}
              aria-hidden="true"
            />
            <span>
              {healthError
                ? "Server Backend Terputus"
                : health
                ? "Server Backend Aktif"
                : "Memeriksa Koneksi..."}
            </span>
          </div>
        </div>
        <DatasetSimulationNotice compact simulationOnly={health?.simulation_only ?? true} />
        {accountError && <p role="alert" className="break-words text-xs text-[#991B1B]">{accountError}</p>}
        <ThemeToggle fullWidth />
        <button
          type="button"
          onClick={handleLogout}
          disabled={accountPending}
          className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-[#DCE6DE] bg-white px-3 py-2 text-xs font-semibold text-[#4A6170] hover:bg-[#FEF0F0] hover:text-[#991B1B] disabled:opacity-60"
        >
          <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Keluar Akun</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#F5F8F5] text-[#16354A]">
      <a
        href="#main-content"
        inert={drawerOpen}
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-xl focus:bg-[#0F766E] focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
      >
        Langsung ke konten utama
      </a>

      {/* Desktop Fixed Sidebar */}
      <aside inert={drawerOpen} className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-[#DCE6DE] bg-white lg:block">
        {sidebarContent(false)}
      </aside>

      {/* Mobile Slide-Over Drawer */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Menu navigasi"
        >
          <div
            className="fixed inset-0 bg-[#16354A]/40"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <aside className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] border-r border-[#DCE6DE] bg-white shadow-xl">
            {sidebarContent(true)}
          </aside>
        </div>
      )}

      {/* Main Column */}
      <div inert={drawerOpen} className="flex min-h-screen min-w-0 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-2 border-b border-[#DCE6DE] bg-white/95 px-3 backdrop-blur-xs sm:gap-3 sm:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-3">
            <button
              ref={drawerTrigger}
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[#DCE6DE] text-[#16354A] hover:bg-[#F5F8F5] lg:hidden"
              aria-expanded={drawerOpen}
              aria-label="Buka menu navigasi"
            >
              <Menu className="h-5 w-5" />
            </button>
            {user.active_role === "QC_OFFICER" && pathname !== "/menu-planning" ? (
              <div className="min-w-0 truncate text-xs font-semibold text-[#16354A] sm:text-sm">
                {user.active_kitchen_name}
              </div>
            ) : (
              <>
                <div className="hidden shrink-0 text-xs font-medium text-[#647A87] sm:block">
                  Rencana Aktif:
                </div>
                <ScenarioSelector />
              </>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <ThemeToggle compact />
            <button
              type="button"
              onClick={refreshAll}
              className="inline-flex h-11 min-w-[44px] items-center justify-center gap-1.5 rounded-xl border border-[#DCE6DE] bg-white px-2.5 text-xs font-semibold text-[#4A6170] hover:bg-[#F5F8F5] hover:text-[#16354A] sm:px-3"
              title="Muat ulang data dari server"
              aria-label="Muat ulang data dari server"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">Muat Ulang</span>
            </button>

            {user.active_role === "MENU_PLANNER" && (
              <Link
                href="/simulator"
                className="hidden h-10 items-center gap-1.5 rounded-xl bg-[#0F766E] px-3.5 text-xs font-semibold text-white hover:bg-[#0B5F58] sm:inline-flex sm:text-sm"
              >
                <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Simulasi Baru</span>
              </Link>
            )}

            {user.active_role === "QC_OFFICER" && (
              <Link
                href="/kitchen-qc"
                className="hidden h-10 items-center gap-1.5 rounded-xl bg-[#0F766E] px-3.5 text-xs font-semibold text-white hover:bg-[#0B5F58] sm:inline-flex sm:text-sm"
              >
                <Camera className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Periksa Menu</span>
              </Link>
            )}
          </div>
        </header>

        <main
          id="main-content"
          tabIndex={-1}
          className="mx-auto w-full min-w-0 max-w-7xl flex-1 px-4 py-5 [overflow-wrap:anywhere] sm:px-6 sm:py-6 lg:px-8"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
