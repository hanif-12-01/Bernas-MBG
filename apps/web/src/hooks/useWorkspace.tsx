"use client";

import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { ThemeProvider } from "@/hooks/useTheme";
import { apiClient } from "@/lib/api/client";
import type {
  DatasetVersionItem,
  HealthResponse,
  OptimizationRunResponse,
  RunListItem,
  Scenario,
  ScenarioCreateRequest,
} from "@/types/api";

const STORAGE_RUN_KEY = "gizioptima_selected_run_id";

interface WorkspaceContextValue {
  health: HealthResponse | undefined;
  healthError: Error | null;
  datasets: DatasetVersionItem[];
  activeDataset: DatasetVersionItem | undefined;
  scenarios: Scenario[];
  runs: RunListItem[];
  selectedRunId: string | null;
  setSelectedRunId: (runId: string | null) => void;
  selectedRun: OptimizationRunResponse | undefined;
  selectedScenario: Scenario | undefined;
  isLoadingList: boolean;
  isLoadingRun: boolean;
  listError: Error | null;
  runError: Error | null;
  createScenario: (payload: ScenarioCreateRequest) => Promise<Scenario>;
  optimizeScenario: (scenarioId: string) => Promise<OptimizationRunResponse>;
  isOptimizingScenario: boolean;
  refreshAll: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function WorkspaceStateProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const { user, isAuthenticated, refreshAuth } = useAuth();
  const [selectedRunId, setSelectedRunIdState] = useState<string | null>(null);

  const kitchenScopeKey = user?.active_kitchen_id ?? "anon";

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(`${STORAGE_RUN_KEY}_${kitchenScopeKey}`);
      if (saved) setSelectedRunIdState(saved);
      else setSelectedRunIdState(null);
    } catch {
      // ignore storage errors
    }
  }, [kitchenScopeKey]);

  const setSelectedRunId = (id: string | null) => {
    setSelectedRunIdState(id);
    try {
      const key = `${STORAGE_RUN_KEY}_${kitchenScopeKey}`;
      if (id) window.localStorage.setItem(key, id);
      else window.localStorage.removeItem(key);
    } catch {
      // ignore storage errors
    }
  };

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: apiClient.getHealth,
    retry: 1,
    staleTime: 30_000,
  });

  const datasetsQuery = useQuery({
    queryKey: ["datasets", kitchenScopeKey],
    queryFn: apiClient.listDatasets,
    enabled: isAuthenticated,
    retry: 1,
  });

  const scenariosQuery = useQuery({
    queryKey: ["scenarios", kitchenScopeKey],
    queryFn: apiClient.listScenarios,
    enabled: isAuthenticated,
    retry: 1,
  });

  const runsQuery = useQuery({
    queryKey: ["runs", kitchenScopeKey],
    queryFn: () => apiClient.listRuns(),
    enabled: isAuthenticated,
    retry: 1,
  });

  const runs = runsQuery.data ?? [];
  const scenarios = scenariosQuery.data ?? [];
  const datasets = datasetsQuery.data ?? [];

  // Auto-select latest validated run (or latest run) when selection is empty or stale
  useEffect(() => {
    if (!isAuthenticated || !runsQuery.isSuccess || runsQuery.isFetching) return;
    if (runs.length === 0) {
      if (selectedRunId !== null) setSelectedRunId(null);
      return;
    }
    const stillExists = selectedRunId && runs.some((r) => r.run_id === selectedRunId);
    if (!stillExists) {
      const preferred = runs.find((r) => r.validation_passed) ?? runs[0];
      setSelectedRunId(preferred.run_id);
    }
  }, [isAuthenticated, runs, runsQuery.isFetching, runsQuery.isSuccess, selectedRunId]);

  const selectedRunQuery = useQuery({
    queryKey: ["run", kitchenScopeKey, selectedRunId],
    queryFn: () => apiClient.getRun(selectedRunId!),
    enabled: isAuthenticated && Boolean(selectedRunId),
    retry: 1,
  });

  const scenarioMutation = useMutation({
    mutationFn: (scenarioId: string) => apiClient.optimizeScenario(scenarioId),
    onSuccess: async (run) => {
      qc.setQueryData(["run", kitchenScopeKey, run.run_id], run);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["scenarios", kitchenScopeKey] }),
        qc.invalidateQueries({ queryKey: ["runs", kitchenScopeKey] }),
      ]);
      setSelectedRunId(run.run_id);
    },
  });

  const activeDataset = useMemo(
    () => datasets.find((d) => d.is_active) ?? datasets[0],
    [datasets]
  );

  const selectedScenario = useMemo(() => {
    const scId = selectedRunQuery.data?.scenario_id;
    if (!scId) return scenarios[0];
    return scenarios.find((s) => s.id === scId);
  }, [scenarios, selectedRunQuery.data]);

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["health"] });
    if (!isAuthenticated) return;
    void refreshAuth(true);
    qc.invalidateQueries({ queryKey: ["datasets"] });
    qc.invalidateQueries({ queryKey: ["scenarios"] });
    qc.invalidateQueries({ queryKey: ["runs"] });
    qc.invalidateQueries({ queryKey: ["menu-reviews"] });
    qc.invalidateQueries({ queryKey: ["qc-inspections"] });
    qc.invalidateQueries({ queryKey: ["manager-summary"] });
    qc.invalidateQueries({ queryKey: ["qc-summary"] });
    qc.invalidateQueries({ queryKey: ["planner-summary"] });
    qc.invalidateQueries({ queryKey: ["incidents"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
    qc.invalidateQueries({ queryKey: ["stock-custodian"] });
    qc.invalidateQueries({ queryKey: ["purchase-documents"] });
    qc.invalidateQueries({ queryKey: ["goods-receipts"] });
    qc.invalidateQueries({ queryKey: ["effective-operational-plan"] });
    qc.invalidateQueries({ queryKey: ["operational-plans"] });
    if (selectedRunId) {
      qc.invalidateQueries({ queryKey: ["run", kitchenScopeKey, selectedRunId] });
    }
  };

  useEffect(() => {
    if (!isAuthenticated) return;
    const syncOperationalState = () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        return;
      }
      void refreshAuth(true);
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["stock-custodian"] });
      qc.invalidateQueries({ queryKey: ["effective-operational-plan"] });
      qc.invalidateQueries({ queryKey: ["operational-plans"] });
      qc.invalidateQueries({ queryKey: ["manager-summary"] });
      qc.invalidateQueries({ queryKey: ["qc-summary"] });
      qc.invalidateQueries({ queryKey: ["planner-summary"] });
      qc.invalidateQueries({ queryKey: ["purchase-documents"] });
      qc.invalidateQueries({ queryKey: ["goods-receipts"] });
    };
    const timerId = window.setInterval(syncOperationalState, 4000);
    window.addEventListener("focus", syncOperationalState);
    document.addEventListener("visibilitychange", syncOperationalState);
    return () => {
      window.clearInterval(timerId);
      window.removeEventListener("focus", syncOperationalState);
      document.removeEventListener("visibilitychange", syncOperationalState);
    };
  }, [isAuthenticated, qc, refreshAuth]);

  const value: WorkspaceContextValue = {
    health: healthQuery.data,
    healthError: (healthQuery.error as Error | null) ?? null,
    datasets,
    activeDataset,
    scenarios,
    runs,
    selectedRunId,
    setSelectedRunId,
    selectedRun: selectedRunQuery.data,
    selectedScenario,
    isLoadingList:
      isAuthenticated &&
      (datasetsQuery.isLoading || scenariosQuery.isLoading || runsQuery.isLoading),
    isLoadingRun: isAuthenticated && selectedRunQuery.isLoading,
    listError:
      ((datasetsQuery.error || scenariosQuery.error || runsQuery.error) as Error | null) ?? null,
    runError: (selectedRunQuery.error as Error | null) ?? null,
    createScenario: async (payload) => {
      const scenario = await apiClient.createScenario(payload);
      qc.setQueryData<Scenario[]>(["scenarios", kitchenScopeKey], (previous) => [
        scenario,
        ...(previous ?? []).filter((item) => item.id !== scenario.id),
      ]);
      return scenario;
    },
    optimizeScenario: (scenarioId) => scenarioMutation.mutateAsync(scenarioId),
    isOptimizingScenario: scenarioMutation.isPending,
    refreshAll,
  };

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            staleTime: 15_000,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <WorkspaceStateProvider>{children}</WorkspaceStateProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error("useWorkspace must be used inside AppProviders");
  }
  return ctx;
}
