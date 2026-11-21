import type {
  ActivateReplacementPlanRequest,
  AuditEventResponse,
  AuthUserResponse,
  CSVRowError,
  DatasetImportResponse,
  DatasetSourceItem,
  DatasetVersionItem,
  DisruptionConditionRequest,
  DisruptionImpactReport,
  EffectiveOperationalPlanResponse,
  GoodsReceiptCreateRequest,
  GoodsReceiptResponse,
  HealthResponse,
  HumanCorrectedComponent,
  IncidentActionResponse,
  IncidentCreateRequest,
  IncidentImageInfo,
  IncidentImpactSummaryResponse,
  IncidentStartRecoveryRequest,
  IngredientIncidentResponse,
  InventoryCatalogResponse,
  InventoryIngredientDetailResponse,
  InventoryLotsResponse,
  InventoryTransactionImportResponse,
  KitchenStockCustodianStatusResponse,
  ManagerDashboardSummary,
  ManualStockAdjustmentRequest,
  ManualStockAdjustmentResponse,
  MarketPriceReferenceItem,
  MarketReferenceImportResponse,
  MaterialUsage,
  MenuReviewDecisionEnum,
  MenuReviewResponse,
  MenuReviewStatusEnum,
  OperationalPlanAssignmentResponse,
  OptimizationRunResponse,
  PlannerDashboardSummary,
  PriceOverrideEntry,
  PurchaseDocumentCreateRequest,
  PurchaseDocumentResponse,
  QCDashboardSummary,
  QCImageInfo,
  QCInspectionResponse,
  QCInspectionStatusEnum,
  QCReviewOutcomeEnum,
  RecipeVariant,
  RecoveryEventResponse,
  RecoveryModeEnum,
  RecoverySubmitRequest,
  RecoverySubmitResponse,
  RunListItem,
  Scenario,
  ScenarioComparisonResponse,
  ScenarioCreateRequest,
  StockOverrideEntry,
} from "@/types/api";

// Default to same-origin relative path so Next.js rewrites proxy /api/v1/* to FastAPI,
// preserving HttpOnly SameSite=Lax cookies cleanly across localhost/127.0.0.1.
export const API_BASE_URL = process.env.NEXT_PUBLIC_DIRECT_API_URL?.replace(/\/$/, "") || "";

let activeCsrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  activeCsrfToken = token;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  rowErrors?: CSVRowError[];

  constructor(message: string, status: number, detail?: unknown, rowErrors?: CSVRowError[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.rowErrors = rowErrors;
  }
}

const MUTATING_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

async function requestJson<T>(path: string, init?: RequestInit, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const method = (init?.method ?? "GET").toUpperCase();

  try {
    const headers: Record<string, string> = {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    };
    if (MUTATING_METHODS.has(method) && activeCsrfToken) {
      headers["X-CSRF-Token"] = activeCsrfToken;
    }

    const res = await fetch(`${API_BASE_URL}/api/v1${path}`, {
      ...init,
      credentials: "include",
      signal: controller.signal,
      headers: {
        ...headers,
        ...(init?.headers as Record<string, string> | undefined),
      },
    });

    if (!res.ok) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        body = await res.text().catch(() => null);
      }

      let message = `Permintaan gagal (HTTP ${res.status}).`;
      let rowErrors: CSVRowError[] | undefined;

      if (body && typeof body === "object" && "detail" in body) {
        const detail = (body as { detail: unknown }).detail;
        if (typeof detail === "string") {
          message = detail;
        } else if (detail && typeof detail === "object") {
          const dObj = detail as { message?: string; errors?: CSVRowError[] };
          if (dObj.message) message = dObj.message;
          if (Array.isArray(dObj.errors)) rowErrors = dObj.errors;
        }
      }

      throw new ApiError(message, res.status, body, rowErrors);
    }

    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("Permintaan melebihi batas waktu koneksi ke server backend.", 408);
    }
    throw new ApiError(
      "Tidak dapat terhubung ke server backend GiziOptima. Pastikan layanan FastAPI berjalan.",
      0,
      err
    );
  } finally {
    clearTimeout(timer);
  }
}

export const apiClient = {
  getHealth: () => requestJson<HealthResponse>("/health", undefined, 5000),

  // ---- Authentication & RBAC ----
  login: async (username: string, password: string, kitchenId?: string) => {
    const data = await requestJson<AuthUserResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username,
        password,
        ...(kitchenId ? { kitchen_id: kitchenId } : {}),
      }),
    });
    setCsrfToken(data.csrf_token);
    return data;
  },

  logout: async () => {
    await requestJson<{ status: string }>("/auth/logout", { method: "POST" });
    setCsrfToken(null);
  },

  getMe: async () => {
    const data = await requestJson<AuthUserResponse>("/auth/me", undefined, 6000);
    setCsrfToken(data.csrf_token);
    return data;
  },

  switchKitchen: async (kitchenId: string) => {
    const data = await requestJson<AuthUserResponse>("/auth/switch-kitchen", {
      method: "POST",
      body: JSON.stringify({ kitchen_id: kitchenId }),
    });
    setCsrfToken(data.csrf_token);
    return data;
  },

  listAuditEvents: (limit = 30) =>
    requestJson<AuditEventResponse[]>(`/auth/audit-events?limit=${limit}`),

  // ---- Datasets, Inventory, Scenarios & Runs ----
  listDatasets: () => requestJson<DatasetVersionItem[]>("/datasets"),

  getInventory: (datasetVersionId?: string, productionDate?: string) => {
    const params = new URLSearchParams();
    if (datasetVersionId) params.set("dataset_version_id", datasetVersionId);
    if (productionDate) params.set("production_date", productionDate);
    const q = params.toString() ? `?${params.toString()}` : "";
    return requestJson<InventoryCatalogResponse>(`/inventory${q}`);
  },

  getInventoryDetail: (
    ingredientCode: string,
    datasetVersionId?: string,
    productionDate?: string
  ) => {
    const params = new URLSearchParams();
    if (datasetVersionId) params.set("dataset_version_id", datasetVersionId);
    if (productionDate) params.set("production_date", productionDate);
    const q = params.toString() ? `?${params.toString()}` : "";
    return requestJson<InventoryIngredientDetailResponse>(
      `/inventory/${encodeURIComponent(ingredientCode)}/detail${q}`
    );
  },

  recordInventoryAdjustment: (payload: ManualStockAdjustmentRequest) =>
    requestJson<ManualStockAdjustmentResponse>("/inventory/adjustments", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listInventorySources: () => requestJson<DatasetSourceItem[]>("/inventory/sources"),

  importInventoryTransactions: (formData: FormData) =>
    requestJson<InventoryTransactionImportResponse>(
      "/inventory/transactions/import",
      {
        method: "POST",
        body: formData,
      },
      30000
    ),

  listMarketReferences: () => requestJson<MarketPriceReferenceItem[]>("/market-references"),

  importMarketReferences: (formData: FormData) =>
    requestJson<MarketReferenceImportResponse>(
      "/market-references/import",
      {
        method: "POST",
        body: formData,
      },
      30000
    ),

  getInventoryTemplateUrl: (templateName: "pilot-transactions" | "market-references") =>
    `${API_BASE_URL}/api/v1/inventory/templates/${templateName}`,

  listRecipes: (datasetVersionId?: string, includeUnreviewed = true) => {
    const params = new URLSearchParams();
    if (datasetVersionId) params.set("dataset_version_id", datasetVersionId);
    params.set("include_unreviewed", String(includeUnreviewed));
    return requestJson<RecipeVariant[]>(`/recipes?${params.toString()}`);
  },

  listScenarios: () => requestJson<Scenario[]>("/scenarios"),

  getScenario: (scenarioId: string) => requestJson<Scenario>(`/scenarios/${scenarioId}`),

  createScenario: (payload: ScenarioCreateRequest) =>
    requestJson<Scenario>("/scenarios", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  cloneScenario: (scenarioId: string, name?: string) =>
    requestJson<Scenario>(`/scenarios/${scenarioId}/clone`, {
      method: "POST",
      body: JSON.stringify(name ? { name } : {}),
    }),

  patchPriceOverrides: (scenarioId: string, overrides: PriceOverrideEntry[]) =>
    requestJson<Scenario>(`/scenarios/${scenarioId}/price-overrides`, {
      method: "PATCH",
      body: JSON.stringify({ overrides }),
    }),

  patchStockOverrides: (scenarioId: string, overrides: StockOverrideEntry[]) =>
    requestJson<Scenario>(`/scenarios/${scenarioId}/stock-overrides`, {
      method: "PATCH",
      body: JSON.stringify({ overrides }),
    }),

  optimizeScenario: (scenarioId: string, timeLimitSeconds = 10) =>
    requestJson<OptimizationRunResponse>(
      `/scenarios/${scenarioId}/optimize`,
      {
        method: "POST",
        body: JSON.stringify({ time_limit_seconds: timeLimitSeconds }),
      },
      30000
    ),

  listRuns: (opts?: { scenarioId?: string; validatedOnly?: boolean }) => {
    const params = new URLSearchParams();
    if (opts?.scenarioId) params.set("scenario_id", opts.scenarioId);
    if (opts?.validatedOnly) params.set("validated_only", "true");
    const q = params.toString() ? `?${params.toString()}` : "";
    return requestJson<RunListItem[]>(`/runs${q}`);
  },

  getRun: (runId: string) => requestJson<OptimizationRunResponse>(`/runs/${runId}`),

  getShoppingList: (runId: string) =>
    requestJson<MaterialUsage[]>(`/runs/${runId}/shopping-list`),

  compareRuns: (baseId: string, candidateId: string) =>
    requestJson<ScenarioComparisonResponse>(
      `/comparisons?base_id=${encodeURIComponent(baseId)}&candidate_id=${encodeURIComponent(candidateId)}`
    ),

  importDatasetCsv: (formData: FormData) =>
    requestJson<DatasetImportResponse>(
      "/datasets/import",
      {
        method: "POST",
        body: formData,
      },
      30000
    ),

  downloadRunCsv: async (runId: string): Promise<{ blob: Blob; filename: string }> => {
    const res = await fetch(`${API_BASE_URL}/api/v1/runs/${runId}/export.csv`, {
      credentials: "include",
    });
    if (!res.ok) {
      let msg = `Gagal mengunduh CSV (HTTP ${res.status}).`;
      try {
        const j = (await res.json()) as { detail?: string };
        if (j.detail) msg = j.detail;
      } catch {
        // ignore parse errors
      }
      throw new ApiError(msg, res.status);
    }
    const blob = await res.blob();
    return { blob, filename: `gizioptima_run_${runId.slice(0, 8)}.csv` };
  },

  // ---- Menu Operational Review Workflow ----
  listMenuReviews: (status?: MenuReviewStatusEnum) => {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    return requestJson<MenuReviewResponse[]>(`/menu-reviews${q}`);
  },

  createMenuReview: (payload: { run_id: string; title?: string; planner_notes?: string }) =>
    requestJson<MenuReviewResponse>("/menu-reviews", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  submitMenuReview: (reviewId: string, plannerNotes?: string) =>
    requestJson<MenuReviewResponse>(`/menu-reviews/${reviewId}/submit`, {
      method: "POST",
      body: JSON.stringify(plannerNotes ? { planner_notes: plannerNotes } : {}),
    }),

  reviewMenuPlan: (
    reviewId: string,
    decision: MenuReviewDecisionEnum,
    reviewerNotes?: string
  ) =>
    requestJson<MenuReviewResponse>(`/menu-reviews/${reviewId}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, reviewer_notes: reviewerNotes || undefined }),
    }),

  // ---- AI Visual Kitchen QC ----
  listQCInspections: (status?: QCInspectionStatusEnum) => {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    return requestJson<QCInspectionResponse[]>(`/qc/inspections${q}`);
  },

  getQCInspection: (inspectionId: string) =>
    requestJson<QCInspectionResponse>(`/qc/inspections/${inspectionId}`),

  createQCInspection: (payload: {
    run_id: string;
    menu_review_id?: string | null;
    day_index: number;
    meal_batch_code?: string;
    qc_notes?: string;
    previous_inspection_id?: string;
  }) =>
    requestJson<QCInspectionResponse>("/qc/inspections", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  uploadQCImage: (inspectionId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return requestJson<QCImageInfo>(
      `/qc/inspections/${inspectionId}/images`,
      {
        method: "POST",
        body: fd,
      },
      30000
    );
  },

  analyzeQCInspection: (inspectionId: string, imageId?: string) => {
    const q = imageId ? `?image_id=${encodeURIComponent(imageId)}` : "";
    return requestJson<QCInspectionResponse>(
      `/qc/inspections/${inspectionId}/analyze${q}`,
      { method: "POST" },
      35000
    );
  },

  patchQCObservations: (
    inspectionId: string,
    payload: {
      corrected_components: HumanCorrectedComponent[];
      notes?: string;
      request_retake?: boolean;
      ai_observation_id?: string;
    }
  ) =>
    requestJson<QCInspectionResponse>(`/qc/inspections/${inspectionId}/observations`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  submitQCInspection: (inspectionId: string, qcNotes?: string) =>
    requestJson<QCInspectionResponse>(`/qc/inspections/${inspectionId}/submit`, {
      method: "POST",
      body: JSON.stringify(qcNotes ? { qc_notes: qcNotes } : {}),
    }),

  reviewQCInspection: (
    inspectionId: string,
    outcome: QCReviewOutcomeEnum,
    managerNotes?: string
  ) =>
    requestJson<QCInspectionResponse>(`/qc/inspections/${inspectionId}/review`, {
      method: "POST",
      body: JSON.stringify({ outcome, manager_notes: managerNotes || undefined }),
    }),

  getProtectedImageUrl: (relativePath: string) => `${API_BASE_URL}${relativePath}`,

  // ---- Role Summaries ----
  getManagerSummary: () => requestJson<ManagerDashboardSummary>("/dashboard/manager-summary"),
  getQCSummary: () => requestJson<QCDashboardSummary>("/dashboard/qc-summary"),
  getPlannerSummary: () => requestJson<PlannerDashboardSummary>("/dashboard/planner-summary"),

  // ---- Single Stock Custodian Delegation ----
  getStockCustodian: () =>
    requestJson<KitchenStockCustodianStatusResponse>("/stock-custodian"),

  assignStockCustodian: (payload: {
    custodian_user_id: string;
    effective_until?: string | null;
    notes?: string | null;
  }) =>
    requestJson<KitchenStockCustodianStatusResponse>("/stock-custodian/assign", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  revokeStockCustodian: (notes?: string | null) =>
    requestJson<KitchenStockCustodianStatusResponse>("/stock-custodian/revoke", {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null }),
    }),

  // ---- Procurement Evidence & Goods Receipts ----
  listPurchaseDocuments: (limit = 50) =>
    requestJson<PurchaseDocumentResponse[]>(`/procurement/documents?limit=${limit}`),

  createPurchaseDocument: (payload: PurchaseDocumentCreateRequest) =>
    requestJson<PurchaseDocumentResponse>("/procurement/documents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  uploadPurchaseEvidence: (documentId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return requestJson<PurchaseDocumentResponse>(
      `/procurement/documents/${documentId}/evidence`,
      {
        method: "POST",
        body: fd,
      },
      30000
    );
  },

  reviewPurchaseDocument: (
    documentId: string,
    payload: { decision: "VERIFIED_MATCH" | "DISCREPANCY_FLAGGED"; notes?: string | null }
  ) =>
    requestJson<PurchaseDocumentResponse>(`/procurement/documents/${documentId}/review`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  listGoodsReceipts: (limit = 50) =>
    requestJson<GoodsReceiptResponse[]>(`/procurement/receipts?limit=${limit}`),

  createGoodsReceipt: (payload: GoodsReceiptCreateRequest) =>
    requestJson<GoodsReceiptResponse>("/procurement/receipts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ---- Sprint 3B: Adaptive Procurement Recovery ----
  previewRecoveryImpact: (payload: DisruptionConditionRequest) =>
    requestJson<DisruptionImpactReport>(
      "/recovery/impact",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      25000
    ),

  createRecoveryEvent: (payload: DisruptionConditionRequest) =>
    requestJson<RecoveryEventResponse>(
      "/recovery/events",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      45000
    ),

  listRecoveryEvents: () => requestJson<RecoveryEventResponse[]>("/recovery/events"),

  getRecoveryEvent: (eventId: string) =>
    requestJson<RecoveryEventResponse>(`/recovery/events/${eventId}`),

  submitRecoveryEvent: (eventId: string, payload: RecoverySubmitRequest) =>
    requestJson<RecoverySubmitResponse>(`/recovery/events/${eventId}/submit`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getRecoveryProcurementCsvUrl: (eventId: string, mode: RecoveryModeEnum = "MIN_DISRUPTION") =>
    `${API_BASE_URL}/api/v1/recovery/events/${eventId}/procurement.csv?mode=${encodeURIComponent(mode)}`,

  // ---- Sprint 3B.1 & 3C: Operational Plans, Lots & Safety Incidents ----
  getInventoryLots: (datasetVersionId?: string, productionDate?: string) => {
    const sp = new URLSearchParams();
    if (datasetVersionId) sp.set("dataset_version_id", datasetVersionId);
    if (productionDate) sp.set("production_date", productionDate);
    const q = sp.toString();
    return requestJson<InventoryLotsResponse>(`/inventory/lots${q ? `?${q}` : ""}`);
  },

  getEffectiveOperationalPlan: (params?: {
    datasetVersionId?: string;
    productionDate?: string;
    mealType?: string;
    targetCohort?: string;
    batchLabel?: string;
  }) => {
    const sp = new URLSearchParams();
    if (params?.datasetVersionId) sp.set("dataset_version_id", params.datasetVersionId);
    if (params?.productionDate) sp.set("production_date", params.productionDate);
    if (params?.mealType) sp.set("meal_type", params.mealType);
    if (params?.targetCohort) sp.set("target_cohort", params.targetCohort);
    if (params?.batchLabel) sp.set("batch_label", params.batchLabel);
    const q = sp.toString();
    return requestJson<EffectiveOperationalPlanResponse>(
      `/operational-plans/effective${q ? `?${q}` : ""}`
    );
  },

  listOperationalPlans: (datasetVersionId?: string, includeSuperseded = true) => {
    const sp = new URLSearchParams();
    if (datasetVersionId) sp.set("dataset_version_id", datasetVersionId);
    sp.set("include_superseded", includeSuperseded ? "true" : "false");
    return requestJson<OperationalPlanAssignmentResponse[]>(`/operational-plans?${sp.toString()}`);
  },

  activateOperationalPlan: (payload: ActivateReplacementPlanRequest) =>
    requestJson<OperationalPlanAssignmentResponse>("/operational-plans/activate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listIncidents: () => requestJson<IngredientIncidentResponse[]>("/incidents"),

  getIncident: (incidentId: string) =>
    requestJson<IngredientIncidentResponse>(`/incidents/${incidentId}`),

  getIncidentImpact: (incidentId: string) =>
    requestJson<IncidentImpactSummaryResponse>(`/incidents/${incidentId}/impact`),

  createIncident: (payload: IncidentCreateRequest) =>
    requestJson<IngredientIncidentResponse>(
      "/incidents",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      25000
    ),

  updateIncidentStatus: (
    incidentId: string,
    payload: {
      status: string;
      notes?: string;
      dispose_held_lots?: boolean;
      disposal_notes?: string;
    }
  ) =>
    requestJson<IngredientIncidentResponse>(`/incidents/${incidentId}/status`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  recordIncidentDisposal: (
    incidentId: string,
    payload: { notes?: string; idempotency_key?: string } = {}
  ) =>
    requestJson<IngredientIncidentResponse>(`/incidents/${incidentId}/record-disposal`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  startIncidentRecovery: (incidentId: string, payload: IncidentStartRecoveryRequest = {}) =>
    requestJson<RecoveryEventResponse>(
      `/incidents/${incidentId}/start-recovery`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      45000
    ),

  uploadIncidentImage: (incidentId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return requestJson<IncidentImageInfo>(
      `/incidents/${incidentId}/images`,
      {
        method: "POST",
        body: fd,
      },
      30000
    );
  },

  getIncidentActions: (incidentId: string) =>
    requestJson<IncidentActionResponse[]>(`/incidents/${incidentId}/actions`),
};
