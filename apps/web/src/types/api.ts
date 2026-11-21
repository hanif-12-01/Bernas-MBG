export type SlotEnum = "staple" | "protein" | "vegetable" | "fruit";
export type ReviewStatusEnum = "draft" | "needs_review" | "reviewed" | "rejected";
export type SolverStatusEnum = "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "TIME_LIMIT" | "ERROR";
export type SourceTypeEnum = "official" | "uploaded" | "research" | "synthetic";

export interface VisionProviderStatus {
  configured: boolean;
  provider_name: string | null;
  provider_mode: "live" | "test_deterministic" | "unconfigured" | string;
  is_live_ai: boolean;
  model_identifier: string | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  model_version: string;
  simulation_only: boolean;
  persistence: string;
  vision_provider?: VisionProviderStatus;
}

export interface DatasetVersionItem {
  id: string;
  name: string;
  source_type: SourceTypeEnum;
  source_url: string | null;
  is_synthetic: boolean;
  is_active: boolean;
  review_status: ReviewStatusEnum;
  ingestion_metadata: Record<string, unknown>;
  created_at: string;
}

export interface IngredientNutrients {
  energy_kcal_100g: number | null;
  protein_g_100g: number | null;
  fat_g_100g: number | null;
  carb_g_100g: number | null;
  fiber_g_100g: number | null;
  iron_mg_100g: number | null;
}

export type PriceProvenanceEnum =
  | "ACTUAL_SUPPLIER"
  | "SYNTHETIC_EXAMPLE"
  | "OFFICIAL_MARKET_REFERENCE"
  | "UNKNOWN";

export interface MarketReferenceHint {
  commodity_name: string;
  region: string;
  observed_date: string;
  price_value: number;
  unit: string;
  source_name: string;
  price_provenance: PriceProvenanceEnum;
}

export interface ApprovedPlanInventoryAlert {
  menu_review_id: string;
  run_id: string;
  title: string;
  status: string;
  operational_status?: string | null;
  hold_incident_id?: string | null;
  hold_reason?: string | null;
  requires_inventory_review: boolean;
  affected_ingredients: string[];
  summary_message: string;
}

export interface IngredientCoverageForecast {
  coverage_status:
    | "SUFFICIENT"
    | "LOW_COVERAGE"
    | "EXPIRES_BEFORE_USE"
    | "NO_ACTIVE_PLAN"
    | "UNVERIFIED_OR_HELD"
    | string;
  planned_daily_usage_kg?: number | null;
  planned_total_horizon_kg?: number | null;
  estimated_coverage_days?: number | null;
  horizon_days?: number | null;
  covers_horizon_days?: boolean | null;
  first_shortage_day_index?: number | null;
  first_shortage_date?: string | null;
  expires_before_use_kg: number;
  plan_title?: string | null;
  human_summary_id: string;
  disclaimer: string;
}

export interface InventoryLotSummary {
  id: string;
  lot_code: string;
  recorded_raw_g: number;
  usable_raw_g: number;
  damaged_raw_g: number;
  expires_at?: string | null;
  expiry_known: boolean;
  received_at?: string | null;
  supplier_name?: string | null;
  purchase_document_id?: string | null;
  days_until_expiry?: number | null;
  verification_status: string;
  safety_hold_status: "NONE" | "ON_HOLD" | "REJECTED_DISPOSED" | string;
  notes?: string | null;
}

export interface InventoryLotCatalogEntry {
  ingredient_id: string;
  ingredient_code: string;
  ingredient_name: string;
  recorded_raw_g: number | null;
  usable_raw_g: number | null;
  safety_held_raw_g: number;
  rejected_disposed_raw_g: number;
  data_quality_status: string;
  held_lot_codes: string[];
  lots: InventoryLotSummary[];
}

export interface InventoryLotsResponse {
  kitchen_id: string;
  dataset_version_id: string;
  production_date: string;
  items: InventoryLotCatalogEntry[];
}

export interface InventoryCatalogItem {
  id: string;
  code: string;
  name: string;
  category: string;
  edible_fraction: number;
  allergens: string[];
  nutrients: IngredientNutrients;
  price_idr_per_g: number | null;
  original_price_value: number | null;
  original_price_unit: string | null;
  price_region: string | null;
  price_observed_at: string | null;
  price_source_type: SourceTypeEnum | null;
  price_provenance?: PriceProvenanceEnum | null;
  stock_raw_g: number | null;
  recorded_raw_g?: number | null;
  usable_raw_g?: number | null;
  physical_raw_g?: number | null;
  reserved_raw_g?: number;
  unavailable_raw_g?: number;
  expired_raw_g?: number;
  damaged_raw_g?: number;
  unverified_raw_g?: number;
  safety_held_raw_g?: number;
  rejected_disposed_raw_g?: number;
  held_lot_codes?: string[];
  lots?: InventoryLotSummary[];
  incoming_raw_g?: number;
  delivery_status?: string;
  quarantined_events_count?: number;
  latest_supplier_name?: string | null;
  latest_received_at?: string | null;
  nearest_expiry_at?: string | null;
  days_until_nearest_expiry?: number | null;
  coverage?: IngredientCoverageForecast | null;
  data_quality_status?: string;
  data_classification?: string;
  last_verified_at?: string | null;
  availability_explanation?: string | null;
  availability_warnings?: string[];
  market_references?: MarketReferenceHint[];
  source_type: SourceTypeEnum;
  source_ref: string;
  review_status: ReviewStatusEnum;
}

export interface InventoryCatalogResponse {
  dataset: DatasetVersionItem;
  uses_batch_ledger?: boolean;
  production_date?: string | null;
  verified_count?: number;
  warning_count?: number;
  unknown_count?: number;
  quarantined_events_count?: number;
  approved_plan_alerts?: ApprovedPlanInventoryAlert[];
  items: InventoryCatalogItem[];
}

export interface DatasetSourceItem {
  id: string;
  source_name: string;
  source_url: string | null;
  license: string;
  license_verified: boolean;
  dataset_type: string;
  retrieved_at: string;
  checksum: string | null;
  allowed_use: string;
  transformation_notes: string | null;
}

export interface InventoryTransactionRowResult {
  row_number: number;
  idempotency_key: string;
  event_type: string;
  ingredient_code: string;
  status: string;
  normalized_raw_g: number | null;
  message: string;
}

export interface InventoryTransactionImportResponse {
  dataset_version_id: string;
  kitchen_id: string;
  dry_run: boolean;
  data_classification: string;
  total_rows: number;
  applied_count: number;
  duplicate_skipped_count: number;
  quarantined_count: number;
  error_count: number;
  results: InventoryTransactionRowResult[];
}

export interface MarketPriceReferenceItem {
  id: string;
  commodity_code: string;
  commodity_name: string;
  canonical_ingredient_code: string | null;
  region: string;
  observed_date: string;
  price_value: number;
  unit: string;
  price_idr_per_g: number | null;
  price_provenance: PriceProvenanceEnum;
  source_name: string;
  published_at: string | null;
  retrieved_at: string;
  imported_at: string;
  quality_status: string;
  notes: string | null;
}

export interface MarketReferenceImportResponse {
  imported_count: number;
  skipped_count: number;
  source_name: string;
  price_provenance: PriceProvenanceEnum;
  warnings: string[];
  items: MarketPriceReferenceItem[];
}

export interface RecipeIngredient {
  ingredient_code: string;
  raw_g_per_serving: number;
  retention_factor: number;
}

export interface RecipeVariant {
  id: string;
  code: string;
  name: string;
  slot: SlotEnum;
  family: string;
  review_status: ReviewStatusEnum;
  reviewer: string | null;
  reviewed_at: string | null;
  active: boolean;
  allergen_tags: string[];
  ingredients: RecipeIngredient[];
}

export interface Scenario {
  id: string;
  name: string;
  parent_scenario_id: string | null;
  dataset_version_id: string;
  nutrition_target_id: string;
  meal_type: string;
  servings_per_day: number;
  days: number;
  budget_idr_per_serving: number;
  max_repeat_per_family: number;
  excluded_allergens: string[];
  price_overrides_idr_per_g: Record<string, number>;
  stock_overrides_raw_g: Record<string, number>;
  source_label: SourceTypeEnum;
  production_date?: string | null;
  service_dates?: string[];
  continuation_of_run_id?: string | null;
  locked: boolean;
  created_at: string;
}

export interface ScenarioCreateRequest {
  name: string;
  dataset_version_id?: string;
  nutrition_target_id?: string;
  meal_type?: string;
  servings_per_day?: number;
  days?: number;
  budget_idr_per_serving?: number;
  max_repeat_per_family?: number;
  excluded_allergens?: string[];
  source_label?: SourceTypeEnum;
  production_date?: string | null;
  service_dates?: string[];
  continuation_of_run_id?: string | null;
}

export interface PriceOverrideEntry {
  ingredient_code: string;
  price_value: number;
  unit: string;
  density_g_per_ml?: number | null;
}

export interface StockOverrideEntry {
  ingredient_code: string;
  stock_raw_g: number;
}

export interface DayPlan {
  day_index: number;
  service_date?: string | null;
  recipes_by_slot: Record<SlotEnum, string>;
  recipe_names_by_slot: Record<SlotEnum, string>;
  daily_cost_idr_per_serving: number;
  nutrients_per_serving: Record<string, number>;
}

export interface CrossWeekHistoryDaySummary {
  service_date: string;
  source_type: "VERIFIED_EXECUTION" | "OPERATIONAL_PLAN" | string;
  plan_title: string;
  recipe_names_by_slot: Record<string, string>;
  families_by_slot: Record<string, string>;
}

export interface CrossWeekComparisonMetrics {
  previous_unique_recipes_count: number;
  new_unique_recipes_count: number;
  fresh_recipes_count: number;
  repeated_recipes_from_previous_week_count: number;
  boundary_day5_to_day1_repeat_count: number;
  max_boundary_5day_family_repeat: number;
  previous_cost_per_serving_idr: number | null;
  new_cost_per_serving_idr: number | null;
  cost_delta_per_serving_idr: number | null;
}

export interface CrossWeekHistoryContext {
  window_days: number;
  history_days_count: number;
  primary_source_type: "VERIFIED_EXECUTION" | "MIXED" | "OPERATIONAL_PLAN" | "NONE" | string;
  source_notice: string;
  previous_run_id: string | null;
  previous_plan_title: string | null;
  previous_cost_per_serving_idr: number | null;
  previous_period_dates: string[];
  history_days: CrossWeekHistoryDaySummary[];
  comparison?: CrossWeekComparisonMetrics | null;
}

export interface NextWeekDefaultsResponse {
  source_run_id: string | null;
  source_assignment_id: string | null;
  source_plan_title: string | null;
  source_service_dates: string[];
  suggested_name: string;
  suggested_service_dates: string[];
  dataset_version_id: string;
  nutrition_target_id: string;
  meal_type: string;
  servings_per_day: number;
  days: number;
  budget_idr_per_serving: number;
  max_repeat_per_family: number;
  excluded_allergens: string[];
  history_source_type: string;
  history_source_notice: string;
  stock_confirmation_required: boolean;
  stock_confirmation_reason: string | null;
}

export interface PrepareNextWeekRequest {
  source_run_id?: string | null;
  source_assignment_id?: string | null;
  name?: string | null;
  dataset_version_id?: string | null;
  service_dates?: string[] | null;
  servings_per_day?: number | null;
  budget_idr_per_serving?: number | null;
  max_repeat_per_family?: number | null;
  excluded_allergens?: string[] | null;
  planner_notes?: string | null;
}

export interface PrepareNextWeekResponse {
  scenario_id: string;
  run_id: string;
  menu_review_id: string | null;
  menu_review_status: string | null;
  service_dates: string[];
  solver_status: string;
  validation_passed: boolean;
  stock_confirmation_required: boolean;
  stock_confirmation_reason: string | null;
  history_context: CrossWeekHistoryContext | Record<string, unknown>;
  warnings: string[];
}

export interface ConstraintViolation {
  constraint_family: string;
  detail: string;
  expected: number | null;
  actual: number | null;
}

export interface ConstraintAudit {
  all_hard_constraints_pass: boolean;
  tolerance: number;
  violations: ConstraintViolation[];
}

export interface DiagnosticHint {
  family: string;
  message: string;
}

export interface MaterialUsage {
  ingredient_code: string;
  ingredient_name: string;
  used_raw_g: number;
  available_raw_g: number;
}

export interface SnapshotTargetLimit {
  nutrient_key: string;
  min_per_serving: number | null;
  max_per_serving: number | null;
  unit: string;
}

export interface InputSnapshot {
  model_version?: string;
  dataset_version_id?: string;
  nutrition_target?: {
    id: string;
    cohort: string;
    meal_type: string;
    version: string;
    source_ref: string;
    limits: SnapshotTargetLimit[];
  };
  scenario_params?: {
    meal_type: string;
    servings_per_day: number;
    days: number;
    budget_idr_per_serving: number;
    max_repeat_per_family: number;
    excluded_allergens: string[];
    source_label: string;
  };
  prices_idr_per_g?: Record<string, number>;
  stock_raw_g?: Record<string, number>;
}

export interface OptimizationRunResponse {
  run_id: string;
  scenario_id: string;
  dataset_version_id: string;
  price_snapshot_id: string;
  solver_status: SolverStatusEnum;
  validation_passed: boolean;
  simulation_only: boolean;
  objective_total_idr: number | null;
  cost_per_serving_average_idr: number | null;
  days_count?: number | null;
  service_dates?: string[];
  servings_per_day?: number | null;
  total_servings?: number | null;
  total_menu_slots?: number | null;
  cost_per_day_average_idr?: number | null;
  best_bound: number | null;
  gap_abs: number | null;
  gap_rel: number | null;
  solver_name: string | null;
  solver_version: string | null;
  raw_solver_status: string | null;
  solver_seconds: number;
  input_sha256: string;
  model_version: string;
  input_snapshot: InputSnapshot;
  stock_confirmation_required?: boolean;
  stock_confirmation_reason?: string | null;
  history_context?: CrossWeekHistoryContext | null;
  days: DayPlan[];
  material_usage: MaterialUsage[];
  constraint_audit: ConstraintAudit;
  constraint_diagnostics: DiagnosticHint[];
  warnings: string[];
  created_at: string;
}

export interface RunListItem {
  run_id: string;
  scenario_id: string;
  dataset_version_id: string;
  solver_status: SolverStatusEnum;
  validation_passed: boolean;
  simulation_only: boolean;
  objective_total_idr: number | null;
  cost_per_serving_average_idr: number | null;
  solver_seconds: number;
  model_version: string;
  input_sha256: string;
  created_at: string;
}

export interface ScenarioComparisonResponse {
  base: {
    run_id: string;
    scenario_id: string;
    dataset_version_id: string;
    solver_status: SolverStatusEnum;
    validation_passed: boolean;
    simulation_only: boolean;
    objective_total_idr: number | null;
    cost_per_serving_average_idr: number | null;
    input_sha256: string;
    model_version: string;
    solver_name: string | null;
    solver_version: string | null;
  };
  candidate: {
    run_id: string;
    scenario_id: string;
    dataset_version_id: string;
    solver_status: SolverStatusEnum;
    validation_passed: boolean;
    simulation_only: boolean;
    objective_total_idr: number | null;
    cost_per_serving_average_idr: number | null;
    input_sha256: string;
    model_version: string;
    solver_name: string | null;
    solver_version: string | null;
  };
  compatibility: {
    same_dataset_version: boolean;
    same_nutrition_target: boolean;
    same_horizon_and_servings: boolean;
    same_prices: boolean;
    same_stock: boolean;
    same_constraints: boolean;
    changed_prices: Array<{
      ingredient_code: string;
      base_price_idr_per_g: number | null;
      candidate_price_idr_per_g: number | null;
      delta_pct: number | null;
    }>;
    changed_stock: Array<{
      ingredient_code: string;
      base_stock_raw_g: number | null;
      candidate_stock_raw_g: number | null;
    }>;
    constraint_differences: string[];
    apples_to_apples_comparable: boolean;
    comparison_basis:
      | "apples_to_apples_optimization"
      | "input_price_or_constraint_change"
      | "not_comparable_infeasible"
      | string;
  };
  cost_comparison: {
    base_total_idr: number | null;
    candidate_total_idr: number | null;
    delta_total_idr: number | null;
    base_cost_per_serving_idr: number | null;
    candidate_cost_per_serving_idr: number | null;
    delta_cost_per_serving_idr: number | null;
    delta_cost_pct: number | null;
    cost_savings_achieved_idr: number | null;
    cost_savings_pct: number | null;
    interpretation: string;
  };
  nutrient_comparison: Array<{
    nutrient_key: string;
    unit: string;
    min_per_serving: number | null;
    max_per_serving: number | null;
    base_avg_per_serving: number | null;
    candidate_avg_per_serving: number | null;
    delta_avg_per_serving: number | null;
    base_min_margin_above_floor: number | null;
    candidate_min_margin_above_floor: number | null;
    base_min_margin_below_ceiling: number | null;
    candidate_min_margin_below_ceiling: number | null;
  }>;
  recipe_changes: Array<{
    day_index: number;
    slot: SlotEnum;
    base_recipe_name: string | null;
    candidate_recipe_name: string | null;
    changed: boolean;
  }>;
  total_slot_swaps: number;
  ingredient_usage_comparison: Array<{
    ingredient_code: string;
    ingredient_name: string;
    base_used_raw_g: number;
    candidate_used_raw_g: number;
    delta_raw_g: number;
    base_available_raw_g: number | null;
    candidate_available_raw_g: number | null;
    base_utilization_pct: number | null;
    candidate_utilization_pct: number | null;
  }>;
  warnings: string[];
}

export interface CSVRowError {
  file: string;
  row: number;
  field: string;
  message: string;
}

export interface DatasetImportResponse {
  dataset_version_id: string;
  name: string;
  source_type: SourceTypeEnum;
  is_synthetic: boolean;
  is_active: boolean;
  ingredients_imported: number;
  prices_imported: number;
  stock_items_imported: number;
  recipes_imported: number;
  reviewed_recipes_count: number;
  warnings: string[];
}

// =====================================================================
// Sprint 3A: Auth, RBAC, Menu Reviews, Vision QC & Role Dashboards
// =====================================================================

export type RoleEnum = "KITCHEN_MANAGER" | "MENU_PLANNER" | "QC_OFFICER" | "NUTRITIONIST";

export interface KitchenMembershipInfo {
  kitchen_id: string;
  kitchen_code: string;
  kitchen_name: string;
  kitchen_region: string;
  role: RoleEnum;
  is_default: boolean;
}

export interface StockCustodianSummary {
  is_assigned: boolean;
  custodian_user_id?: string | null;
  custodian_username?: string | null;
  custodian_full_name?: string | null;
  effective_until?: string | null;
}

export interface AuthUserResponse {
  user_id: string;
  username: string;
  email: string;
  full_name: string;
  active_kitchen_id: string;
  active_kitchen_code: string;
  active_kitchen_name: string;
  active_role: RoleEnum;
  csrf_token: string;
  is_active_stock_custodian?: boolean;
  stock_custodian?: StockCustodianSummary | null;
  memberships: KitchenMembershipInfo[];
}

export interface AuditEventResponse {
  id: string;
  kitchen_id: string | null;
  actor_user_id: string | null;
  actor_username: string | null;
  actor_full_name: string | null;
  actor_role: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export type MenuReviewStatusEnum = "DRAFT" | "SUBMITTED" | "APPROVED" | "REVISION_REQUIRED";
export type MenuReviewDecisionEnum = "APPROVED" | "REVISION_REQUIRED";

export interface MenuReviewResponse {
  id: string;
  kitchen_id: string;
  scenario_id: string;
  scenario_name: string;
  run_id: string;
  dataset_version_id: string;
  version_number: number;
  status: MenuReviewStatusEnum;
  title: string;
  planner_notes: string | null;
  reviewer_notes: string | null;
  created_by_user_id: string;
  created_by_name: string;
  submitted_by_user_id: string | null;
  submitted_by_name: string | null;
  reviewed_by_user_id: string | null;
  reviewed_by_name: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  cost_per_serving_average_idr: number | null;
  objective_total_idr: number | null;
  days_count: number;
  servings_per_day?: number | null;
  total_servings?: number | null;
  cost_per_day_average_idr?: number | null;
  simulation_only: boolean;
  recovery_event_id?: string | null;
  inventory_snapshot_sha256?: string | null;
  is_stale_inventory?: boolean;
  recovery_selected_mode?: string | null;
  recovery_changed_slots_count?: number | null;
  operational_status?: string | null;
  operational_assignment_id?: string | null;
  production_scope_label?: string | null;
  service_dates?: string[];
  period_start_date?: string | null;
  period_end_date?: string | null;
  derived_period_phase?: "IN_PROGRESS" | "UPCOMING" | "COMPLETED" | string | null;
  continuation_of_run_id?: string | null;
  stock_confirmation_required?: boolean;
  stock_confirmation_reason?: string | null;
  hold_incident_id?: string | null;
  hold_reason?: string | null;
  approval_scope_notice: string;
}

export type FoodCategoryEnum = "staple" | "protein" | "vegetable" | "fruit" | "other";
export type ObservationStatusEnum = "visible" | "uncertain" | "not_visible" | "needs_review";
export type ComparisonStatusEnum =
  | "visual_match"
  | "missing_expected"
  | "uncertain"
  | "needs_manual_check";
export type QCInspectionStatusEnum =
  | "CREATED"
  | "AI_ANALYZED"
  | "HUMAN_REVIEWED"
  | "SUBMITTED"
  | "REVIEWED";
export type QCReviewOutcomeEnum =
  | "ACCEPTED_FOR_RECORD"
  | "REVISION_REQUIRED"
  | "RETAKE_REQUIRED";

export interface ObservedComponent {
  category: FoodCategoryEnum;
  possible_food_name: string;
  observation_status: ObservationStatusEnum;
  explanation: string;
}

export interface VisionAnalysisOutput {
  observed_components: ObservedComponent[];
  uncertain_components: string[];
  limitations: string[];
}

export interface ExpectedMenuSlot {
  slot: string;
  recipe_id: string;
  recipe_name: string;
  ingredient_names: string[];
}

export interface ExpectedVsObservedFinding {
  slot: string;
  expected_recipe_name: string;
  status: ComparisonStatusEnum;
  finding_label: string;
  matched_observation: string | null;
  explanation: string;
}

export interface HumanCorrectedComponent {
  slot: string;
  confirmed_status: ObservationStatusEnum;
  observed_food_name: string;
  officer_note?: string | null;
}

export interface QCImageInfo {
  id: string;
  original_filename_sanitized: string;
  mime_type: string;
  size_bytes: number;
  width_px: number;
  height_px: number;
  sha256: string;
  exif_stripped: boolean;
  retention_days: number;
  uploaded_by_user_id: string;
  created_at: string;
  image_url: string;
  expires_at?: string | null;
}

export interface QCAIObservationInfo {
  id: string;
  image_id: string;
  provider_name: string;
  provider_mode: string;
  is_live_ai: boolean;
  model_identifier: string;
  prompt_version: string;
  validated_output: VisionAnalysisOutput;
  comparison_findings: ExpectedVsObservedFinding[];
  latency_ms: number;
  created_at: string;
}

export interface QCHumanReviewInfo {
  id: string;
  ai_observation_id: string | null;
  reviewer_user_id: string;
  reviewer_name: string;
  corrected_components: HumanCorrectedComponent[];
  notes: string | null;
  request_retake: boolean;
  created_at: string;
}

export interface QCInspectionResponse {
  id: string;
  kitchen_id: string;
  menu_review_id: string | null;
  run_id: string;
  scenario_name: string;
  day_index: number;
  service_date?: string | null;
  status: QCInspectionStatusEnum;
  review_outcome: QCReviewOutcomeEnum | null;
  plan_operational_status?: string | null;
  plan_hold_reason?: string | null;
  created_by_user_id: string;
  created_by_name: string;
  submitted_by_user_id: string | null;
  submitted_by_name: string | null;
  reviewed_by_user_id: string | null;
  reviewed_by_name: string | null;
  qc_notes: string | null;
  manager_notes: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  expected_menu: ExpectedMenuSlot[];
  images: QCImageInfo[];
  ai_observations: QCAIObservationInfo[];
  human_reviews: QCHumanReviewInfo[];
  food_safety_disclaimer: string;
}

export interface LowStockAlert {
  ingredient_code: string;
  ingredient_name: string;
  stock_raw_g: number;
}

export interface ManagerDashboardSummary {
  kitchen_id: string;
  kitchen_name: string;
  simulation_only: boolean;
  total_validated_runs: number;
  latest_run_id: string | null;
  latest_cost_per_serving_idr: number | null;
  latest_total_cost_idr: number | null;
  pending_menu_reviews: MenuReviewResponse[];
  approved_menu_reviews_count: number;
  pending_qc_inspections: QCInspectionResponse[];
  qc_discrepancies_count: number;
  low_stock_alerts: LowStockAlert[];
  approved_plan_inventory_alerts?: ApprovedPlanInventoryAlert[];
  effective_operational_plans?: OperationalPlanAssignmentResponse[];
  approved_awaiting_activation?: MenuReviewResponse[];
  active_incidents_count?: number;
  pending_disposal_authorizations_count?: number;
  pending_purchase_evidence_count?: number;
  pending_purchase_documents?: PurchaseDocumentResponse[];
  stock_custodian?: StockCustodianSummary | null;
  inventory_dataset_name?: string | null;
  inventory_dataset_is_synthetic?: boolean | null;
  recent_audit_events: AuditEventResponse[];
  vision_provider_status: VisionProviderStatus;
}

export interface QCDashboardSummary {
  kitchen_id: string;
  kitchen_name: string;
  simulation_only: boolean;
  is_active_stock_custodian?: boolean;
  stock_custodian?: StockCustodianSummary | null;
  available_menu_plans: MenuReviewResponse[];
  effective_operational_plans?: OperationalPlanAssignmentResponse[];
  held_operational_plans?: OperationalPlanAssignmentResponse[];
  active_incidents_count?: number;
  pending_disposal_executions_count?: number;
  pending_disposal_incidents?: IngredientIncidentResponse[];
  action_required_inspections: QCInspectionResponse[];
  submitted_or_reviewed_inspections: QCInspectionResponse[];
  total_inspections_count: number;
  vision_provider_status: VisionProviderStatus;
}

export interface PlannerDashboardSummary {
  kitchen_id: string;
  kitchen_name: string;
  simulation_only: boolean;
  stock_custodian?: StockCustodianSummary | null;
  effective_operational_plans: OperationalPlanAssignmentResponse[];
  held_operational_plans: OperationalPlanAssignmentResponse[];
  open_incidents_requiring_recovery: IngredientIncidentResponse[];
  draft_or_revision_reviews: MenuReviewResponse[];
  submitted_reviews_count: number;
  approved_reviews_count: number;
  approved_plan_inventory_alerts: ApprovedPlanInventoryAlert[];
  low_stock_alerts: LowStockAlert[];
}

export type DisruptionTypeEnum =
  | "PRICE_CHANGE"
  | "STOCK_SHORTAGE"
  | "SUPPLIER_DELAY"
  | "PARTIAL_DELIVERY"
  | "INGREDIENT_UNAVAILABLE"
  | "SERVING_COUNT_CHANGE"
  | "SAFETY_HOLD";

export type RecoveryModeEnum = "MIN_DISRUPTION" | "MIN_COST";

export type RecoveryStatusEnum =
  | "ANALYZED"
  | "SUBMITTED"
  | "APPROVED"
  | "REVISION_REQUIRED"
  | "INFEASIBLE";

export interface PriceDisruptionInput {
  ingredient_code: string;
  new_price_idr_per_kg: number;
}

export interface StockDisruptionInput {
  ingredient_code: string;
  new_usable_kg?: number | null;
  expected_delivery_kg?: number | null;
  received_delivery_kg?: number | null;
  unavailable?: boolean;
  delivery_status?: string | null;
  reason?: string | null;
}

export interface DisruptionConditionRequest {
  baseline_run_id?: string | null;
  baseline_menu_review_id?: string | null;
  incident_id?: string | null;
  title?: string | null;
  disruption_summary?: string | null;
  disruption_types?: DisruptionTypeEnum[];
  production_date?: string | null;
  use_latest_verified_inventory?: boolean;
  new_servings_per_day?: number | null;
  new_budget_idr_per_serving?: number | null;
  price_changes?: PriceDisruptionInput[];
  stock_changes?: StockDisruptionInput[];
  time_limit_seconds?: number;
}

export interface AffectedIngredientItem {
  ingredient_code: string;
  ingredient_name: string;
  baseline_required_kg: number;
  previous_usable_kg: number | null;
  current_usable_kg: number | null;
  shortfall_kg: number;
  previous_price_idr_per_kg: number;
  current_price_idr_per_kg: number;
  price_delta_pct: number | null;
  delivery_status: string;
  incoming_kg: number;
  data_quality_status: string;
  causes: string[];
}

export interface AffectedSlotItem {
  day_index: number;
  slot: SlotEnum;
  original_recipe_id: string;
  original_recipe_name: string;
  affected_ingredients: string[];
  reasons: string[];
}

export interface DisruptionImpactReport {
  baseline_run_id: string;
  baseline_menu_review_id: string | null;
  baseline_title: string;
  baseline_status: string;
  dataset_version_id: string;
  dataset_name: string;
  production_date: string;
  days: number;
  baseline_servings_per_day: number;
  servings_per_day: number;
  baseline_budget_idr_per_serving: number;
  budget_idr_per_serving: number;
  inventory_snapshot_sha256: string;
  is_disrupted: boolean;
  baseline_still_feasible_at_new_conditions: boolean;
  disruption_types: DisruptionTypeEnum[];
  affected_ingredients: AffectedIngredientItem[];
  affected_slots: AffectedSlotItem[];
  budget_violations: string[];
  stock_shortages: string[];
  nutrition_or_other_issues: string[];
  summary_message: string;
  warnings: string[];
}

export interface SlotSwapDetail {
  day_index: number;
  slot: SlotEnum;
  original_recipe_id: string;
  original_recipe_name: string;
  new_recipe_id: string;
  new_recipe_name: string;
  reason: string;
}

export interface CandidatePlanSummary {
  mode: RecoveryModeEnum;
  scenario_id: string | null;
  run_id: string | null;
  solver_status: SolverStatusEnum;
  validation_passed: boolean;
  changed_slots_count: number;
  unchanged_slots_count: number;
  total_slots_count: number;
  changed_slots: SlotSwapDetail[];
  total_cost_idr: number | null;
  cost_per_serving_idr: number | null;
  days_count?: number | null;
  servings_per_day?: number | null;
  total_servings?: number | null;
  total_menu_slots?: number | null;
  cost_per_day_average_idr?: number | null;
  delta_vs_original_historical_idr: number | null;
  delta_vs_original_at_new_conditions_idr: number | null;
  delta_vs_min_disruption_idr: number | null;
  constraint_diagnostics: DiagnosticHint[];
  warnings: string[];
  run_detail: OptimizationRunResponse | null;
}

export interface CounterfactualBaselineSnapshot {
  label: string;
  feasible: boolean;
  total_cost_idr: number | null;
  cost_per_serving_idr: number | null;
  days_count?: number | null;
  servings_per_day?: number | null;
  total_servings?: number | null;
  cost_per_day_average_idr?: number | null;
  notes: string;
  budget_violations: string[];
  stock_shortages: string[];
  nutrition_or_other_issues: string[];
}

export interface FairComparisonBundle {
  original_historical: CounterfactualBaselineSnapshot;
  original_under_new_conditions: CounterfactualBaselineSnapshot;
  same_conditions_comparison_valid: boolean;
  historical_price_comparison_allowed: boolean;
  cost_savings_claimed_idr: number | null;
  comparison_notice: string;
  min_disruption_vs_min_cost_identical: boolean;
  extra_slots_changed_for_min_cost: number | null;
  savings_by_choosing_min_cost_over_min_disruption_idr: number | null;
}

export interface ProcurementDeltaItem {
  ingredient_code: string;
  ingredient_name: string;
  baseline_required_kg: number;
  required_kg: number;
  delta_vs_baseline_required_kg: number;
  usable_on_hand_kg: number;
  incoming_kg: number;
  delivery_status: string;
  net_to_buy_kg: number;
  unit_price_idr_per_kg: number;
  estimated_net_purchase_cost_idr: number;
  reason: string;
}

export interface RecoveryEventResponse {
  id: string;
  kitchen_id: string;
  dataset_version_id: string;
  baseline_menu_review_id: string | null;
  baseline_run_id: string;
  baseline_scenario_id: string;
  incident_id?: string | null;
  title: string;
  status: RecoveryStatusEnum;
  disruption_types: DisruptionTypeEnum[];
  disruption_summary: string;
  impact: DisruptionImpactReport;
  min_disruption: CandidatePlanSummary;
  min_cost: CandidatePlanSummary;
  comparison: FairComparisonBundle;
  procurement_delta_by_mode: Record<string, ProcurementDeltaItem[]>;
  selected_mode: RecoveryModeEnum | null;
  selected_run_id: string | null;
  submitted_review_id: string | null;
  inventory_snapshot_sha256: string;
  is_stale_inventory: boolean;
  simulation_only: boolean;
  created_at: string;
  updated_at: string;
}

export interface RecoverySubmitRequest {
  mode: RecoveryModeEnum;
  title?: string | null;
  planner_notes?: string | null;
  submit_for_review?: boolean;
}

export interface RecoverySubmitResponse {
  recovery_event: RecoveryEventResponse;
  review: MenuReviewResponse;
}

// =====================================================================
// Sprint 3B.1 & 3C: Operational Plan Lifecycle & Critical Incidents
// =====================================================================

export type OperationalPlanStatusEnum = "ACTIVE" | "ON_HOLD" | "SUPERSEDED";

export type OperationalPlanStateEnum =
  | "NO_PLAN"
  | "DRAFT"
  | "APPROVED_NOT_ACTIVE"
  | "ACTIVE"
  | "ACTIVE_ON_HOLD"
  | "SUPERSEDED"
  | "HISTORICAL";

export interface OperationalPlanAssignmentResponse {
  id: string;
  kitchen_id: string;
  dataset_version_id: string;
  menu_review_id: string;
  run_id: string;
  scenario_id: string;
  plan_title: string;
  scenario_name: string;
  review_version_number: number;
  historical_review_status: string;
  operational_status: OperationalPlanStatusEnum;
  production_date: string;
  horizon_days: number;
  service_dates?: string[];
  period_start_date?: string | null;
  period_end_date?: string | null;
  derived_period_phase?: "IN_PROGRESS" | "UPCOMING" | "COMPLETED" | string | null;
  meal_type: string;
  target_cohort: string;
  batch_label: string;
  scope_key: string;
  scope_label: string;
  supersedes_assignment_id: string | null;
  hold_incident_id: string | null;
  hold_reason: string | null;
  held_at: string | null;
  activated_by_user_id: string | null;
  activated_by_name: string | null;
  activated_at: string;
  superseded_at: string | null;
  inventory_snapshot_sha256: string | null;
  is_stale_inventory: boolean;
  is_ready_for_execution: boolean;
  servings_per_day: number;
  total_servings: number;
  total_menu_slots: number;
  total_cost_idr: number | null;
  cost_per_serving_idr: number | null;
  cost_per_day_average_idr: number | null;
  simulation_only: boolean;
}

export interface EffectiveOperationalPlanResponse {
  kitchen_id: string;
  state: OperationalPlanStateEnum;
  is_ready_for_execution: boolean;
  status_message: string;
  queried_service_date?: string | null;
  matched_day_index?: number | null;
  active_plan: OperationalPlanAssignmentResponse | null;
  held_plan: OperationalPlanAssignmentResponse | null;
  approved_pending_activation: string[];
  superseded_plans_count: number;
  draft_plans_count: number;
  historical_approved_count: number;
}

export interface ActivateReplacementPlanRequest {
  menu_review_id: string;
  batch_label?: string | null;
  expected_active_assignment_id?: string | null;
  notes?: string | null;
  idempotency_key?: string | null;
}

export type IncidentCategoryEnum =
  | "SPOILAGE"
  | "SUSPECTED_CONTAMINATION"
  | "DAMAGED_PACKAGING"
  | "ABNORMAL_ODOR_APPEARANCE"
  | "SUPPLIER_RECALL"
  | "TEMPERATURE_EXCURSION"
  | "UNKNOWN_CONDITION";

export type IncidentSeverityEnum = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type IncidentStatusEnum =
  | "REPORTED"
  | "ON_HOLD"
  | "UNDER_REVIEW"
  | "REJECTED"
  | "RESOLVED"
  | "CLOSED";

export interface IncidentAffectedLotInput {
  lot_id?: string | null;
  lot_code?: string | null;
  ingredient_code?: string | null;
  reason_detail?: string | null;
}

export interface IncidentCreateRequest {
  title?: string | null;
  category: IncidentCategoryEnum;
  severity?: IncidentSeverityEnum;
  notes?: string | null;
  dataset_version_id?: string | null;
  observed_at?: string | null;
  supplier_name?: string | null;
  delivery_ref?: string | null;
  related_batch_code?: string | null;
  ingredient_codes?: string[];
  affected_lots?: IncidentAffectedLotInput[];
  auto_hold_matching_lots?: boolean;
  idempotency_key?: string | null;
}

export interface IncidentAffectedLotResponse {
  id: string;
  incident_id: string;
  lot_id: string;
  lot_code: string;
  ingredient_id: string;
  ingredient_code: string;
  ingredient_name: string;
  lot_safety_status: string;
  prior_lot_verification_status: string;
  recorded_raw_g_snapshot: number;
  usable_before_hold_raw_g: number;
  usable_after_hold_raw_g: number;
  clean_remaining_raw_g: number;
  reason_detail: string | null;
  updated_at: string;
}

export interface ProductionExposureItem {
  exposure_status: string;
  summary: string;
  lot_id?: string | null;
  lot_code?: string | null;
  ingredient_code?: string | null;
  ingredient_name?: string | null;
  quantity_kg?: number | null;
  meal_batch_code?: string | null;
  run_id?: string | null;
  day_index?: number | null;
  recorded_at?: string | null;
}

export interface AffectedPlanSlotReference {
  menu_review_id?: string | null;
  run_id: string;
  plan_title: string;
  operational_status?: string | null;
  day_index: number;
  slot: string;
  recipe_id: string;
  recipe_name: string;
  affected_ingredients: string[];
}

export interface IncidentActionResponse {
  id: string;
  incident_id: string;
  action_type: string;
  actor_user_id?: string | null;
  actor_name?: string | null;
  actor_role?: string | null;
  notes?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface IncidentImageInfo {
  id: string;
  incident_id: string;
  original_filename_sanitized: string;
  mime_type: string;
  size_bytes: number;
  width_px: number;
  height_px: number;
  sha256: string;
  exif_stripped: boolean;
  uploaded_by_user_id: string;
  created_at: string;
  expires_at: string;
  image_url: string;
}

export interface IncidentImpactSummaryResponse {
  incident_id: string;
  affected_ingredient_codes: string[];
  affected_ingredient_names: string[];
  held_lots_count: number;
  total_held_kg: number;
  total_clean_remaining_kg: number;
  affected_plan_ids: string[];
  affected_slots: AffectedPlanSlotReference[];
  exposure_status: string;
  production_exposures: ProductionExposureItem[];
  summary_message: string;
  safety_notice: string;
}

export interface IngredientIncidentResponse {
  id: string;
  kitchen_id: string;
  dataset_version_id: string;
  title: string;
  category: IncidentCategoryEnum;
  severity: IncidentSeverityEnum;
  status: IncidentStatusEnum;
  notes: string | null;
  supplier_name: string | null;
  delivery_ref: string | null;
  related_batch_code: string | null;
  observed_at: string;
  reported_by_user_id: string;
  reported_by_name: string;
  reporter_role: string;
  created_at: string;
  updated_at: string;
  affected_lots: IncidentAffectedLotResponse[];
  affected_ingredient_codes: string[];
  affected_ingredient_names: string[];
  total_held_kg: number;
  total_clean_remaining_kg: number;
  affected_plans: AffectedPlanSlotReference[];
  exposure_status: string;
  production_exposures: ProductionExposureItem[];
  recovery_event_id: string | null;
  disposal_authorized?: boolean;
  disposal_authorized_by_name?: string | null;
  disposal_authorized_at?: string | null;
  disposal_executed_by_name?: string | null;
  disposal_executed_at?: string | null;
  images: IncidentImageInfo[];
  actions: IncidentActionResponse[];
  safety_notice: string;
  simulation_only: boolean;
}

// ---- Post-Sprint 3C: Stock Custodian, Manual Adjustment, Detail & Procurement ----

export interface EligibleCustodianCandidate {
  user_id: string;
  username: string;
  full_name: string;
  email: string;
  is_active_custodian: boolean;
}

export interface CustodianAssignmentResponse {
  id: string;
  kitchen_id: string;
  custodian_user_id: string;
  custodian_username: string;
  custodian_full_name: string;
  assigned_by_user_id?: string | null;
  assigned_by_name?: string | null;
  status: "ACTIVE" | "REVOKED" | "EXPIRED" | string;
  effective_from: string;
  effective_until?: string | null;
  revoked_at?: string | null;
  revoked_by_user_id?: string | null;
  notes?: string | null;
  created_at: string;
}

export interface KitchenStockCustodianStatusResponse {
  kitchen_id: string;
  kitchen_code: string;
  kitchen_name: string;
  active_assignment?: CustodianAssignmentResponse | null;
  eligible_qc_candidates: EligibleCustodianCandidate[];
  history: CustodianAssignmentResponse[];
}

export type ManualStockAdjustmentTypeEnum =
  | "PURCHASE_RECEIPT"
  | "USAGE_CONSUMPTION"
  | "SPOILAGE_DAMAGE"
  | "STOCK_OPNAME_COUNT"
  | "STOCK_CORRECTION";

export interface ManualStockAdjustmentRequest {
  dataset_version_id?: string | null;
  ingredient_code: string;
  lot_code?: string | null;
  adjustment_type: ManualStockAdjustmentTypeEnum;
  quantity: number;
  unit?: string;
  expires_at?: string | null;
  supplier_name?: string | null;
  source_document_ref?: string | null;
  notes?: string | null;
  idempotency_key?: string | null;
}

export interface ManualStockAdjustmentResponse {
  movement_id: string;
  lot_id: string;
  lot_code: string;
  ingredient_code: string;
  ingredient_name: string;
  adjustment_type: ManualStockAdjustmentTypeEnum;
  recorded_raw_g: number;
  damaged_raw_g: number;
  verified_physical_raw_g?: number | null;
  verification_status: string;
  safety_hold_status: string;
  supplier_name?: string | null;
  duplicate_skipped: boolean;
  message: string;
}

export interface InventoryMovementSummaryItem {
  id: string;
  movement_type: string;
  quantity_delta_raw_g: number;
  original_value: number;
  original_unit: string;
  lot_code?: string | null;
  source_document_ref?: string | null;
  event_at: string;
  quarantined: boolean;
  quarantine_reason?: string | null;
  actor_name?: string | null;
}

export interface InventoryActiveIncidentHint {
  id: string;
  title: string;
  category: string;
  severity: string;
  status: string;
  observed_at: string;
  total_held_kg: number;
}

export interface InventoryIngredientDetailResponse {
  ingredient: InventoryCatalogItem;
  recent_movements: InventoryMovementSummaryItem[];
  active_incidents: InventoryActiveIncidentHint[];
}

export type EvidenceStatusEnum =
  | "NO_EVIDENCE"
  | "RECEIPT_UPLOADED"
  | "GOODS_RECEIVED"
  | "VERIFIED_MATCH"
  | "DISCREPANCY_FLAGGED";

export type GoodsConditionEnum = "GOOD" | "DAMAGED" | "QUARANTINED" | "REJECTED";

export interface PurchaseDocumentLineInput {
  ingredient_code?: string | null;
  item_name: string;
  quantity: number;
  unit?: string;
  unit_price_idr?: number | null;
  line_total_idr?: number | null;
  lot_code_hint?: string | null;
  expiry_date_hint?: string | null;
}

export interface PurchaseDocumentCreateRequest {
  dataset_version_id?: string | null;
  linked_run_id?: string | null;
  linked_recovery_event_id?: string | null;
  supplier_name: string;
  supplier_contact?: string | null;
  invoice_number?: string | null;
  purchase_date?: string | null;
  total_amount_idr?: number | null;
  notes?: string | null;
  lines?: PurchaseDocumentLineInput[];
}

export interface PurchaseDocumentLineResponse {
  id: string;
  ingredient_id?: string | null;
  ingredient_code?: string | null;
  item_name: string;
  quantity_raw_g: number;
  unit_label: string;
  unit_price_idr?: number | null;
  line_total_idr?: number | null;
  lot_code_hint?: string | null;
  expiry_date_hint?: string | null;
}

export interface PurchaseDocumentResponse {
  id: string;
  kitchen_id: string;
  dataset_version_id: string;
  linked_run_id?: string | null;
  linked_recovery_event_id?: string | null;
  supplier_name: string;
  supplier_contact?: string | null;
  invoice_number?: string | null;
  purchase_date: string;
  total_amount_idr?: number | null;
  evidence_status: EvidenceStatusEnum;
  has_evidence_file: boolean;
  document_mime_type?: string | null;
  document_sha256?: string | null;
  document_size_bytes?: number | null;
  document_original_filename?: string | null;
  exif_stripped?: boolean | null;
  evidence_url?: string | null;
  recorded_by_user_id?: string | null;
  recorded_by_name?: string | null;
  reviewed_by_user_id?: string | null;
  reviewed_by_name?: string | null;
  reviewed_at?: string | null;
  notes?: string | null;
  lines: PurchaseDocumentLineResponse[];
  created_at: string;
  updated_at: string;
}

export interface GoodsReceiptCreateRequest {
  dataset_version_id?: string | null;
  purchase_document_id?: string | null;
  ingredient_code: string;
  lot_code?: string | null;
  received_quantity: number;
  unit?: string;
  expiry_date?: string | null;
  supplier_name?: string | null;
  condition_status?: GoodsConditionEnum;
  notes?: string | null;
  idempotency_key?: string | null;
}

export interface GoodsReceiptResponse {
  id: string;
  kitchen_id: string;
  purchase_document_id?: string | null;
  dataset_version_id: string;
  ingredient_id?: string | null;
  ingredient_code: string;
  ingredient_name: string;
  lot_id?: string | null;
  lot_code: string;
  received_raw_g: number;
  expiry_date?: string | null;
  supplier_name?: string | null;
  condition_status: GoodsConditionEnum;
  lot_verification_status: string;
  lot_safety_hold_status: string;
  usable_added_raw_g: number;
  received_by_user_id?: string | null;
  received_by_name?: string | null;
  received_at: string;
  notes?: string | null;
  created_at: string;
}

export interface IncidentStartRecoveryRequest {
  baseline_menu_review_id?: string | null;
  baseline_run_id?: string | null;
  production_date?: string | null;
  new_servings_per_day?: number | null;
  new_budget_idr_per_serving?: number | null;
  title?: string | null;
  time_limit_seconds?: number;
}
