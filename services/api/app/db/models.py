from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DatasetVersionORM(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("kitchens.id", name="fk_datasets_kitchen_id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic")
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    ingestion_metadata_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    ingredients: Mapped[List["IngredientORM"]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )
    recipes: Mapped[List["RecipeVariantORM"]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_dataset_versions_kitchen_id", "kitchen_id"),
        Index("ix_dataset_versions_is_active", "is_active"),
        Index("ix_dataset_versions_created_at", "created_at"),
    )


class IngredientORM(Base):
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    edible_fraction: Mapped[float] = mapped_column(Float, nullable=False)
    allergens_json: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic")
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="DEMO_ONLY")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")

    dataset_version: Mapped["DatasetVersionORM"] = relationship(back_populates="ingredients")
    nutrients: Mapped[Optional["IngredientNutrientORM"]] = relationship(
        back_populates="ingredient", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_ingredients_dataset_code"),
        CheckConstraint("edible_fraction > 0 AND edible_fraction <= 1", name="ck_ing_edible"),
        Index("ix_ingredients_dataset_version", "dataset_version_id"),
    )


class IngredientNutrientORM(Base):
    __tablename__ = "ingredient_nutrients"

    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    energy_kcal_100g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    protein_g_100g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fat_g_100g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    carb_g_100g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fiber_g_100g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iron_mg_100g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    ingredient: Mapped["IngredientORM"] = relationship(back_populates="nutrients")


class IngredientPriceORM(Base):
    __tablename__ = "ingredient_prices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    price_idr_per_g: Mapped[float] = mapped_column(Float, nullable=False)
    original_value: Mapped[float] = mapped_column(Float, nullable=False)
    original_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(128), nullable=False, default="SIMULASI")
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic")

    __table_args__ = (
        UniqueConstraint("dataset_version_id", "ingredient_id", name="uq_prices_dataset_ing"),
        CheckConstraint("price_idr_per_g > 0", name="ck_price_positive"),
        Index("ix_prices_dataset_version", "dataset_version_id"),
    )


class DatasetStockSnapshotORM(Base):
    __tablename__ = "dataset_stock_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    stock_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("dataset_version_id", "ingredient_id", name="uq_stock_dataset_ing"),
        CheckConstraint("stock_raw_g >= 0", name="ck_stock_nonneg"),
        Index("ix_stock_dataset_version", "dataset_version_id"),
    )


class RecipeVariantORM(Base):
    __tablename__ = "recipe_variants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slot: Mapped[str] = mapped_column(String(32), nullable=False)
    family: Mapped[str] = mapped_column(String(64), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    reviewer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allergen_tags_json: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    dataset_version: Mapped["DatasetVersionORM"] = relationship(back_populates="recipes")
    ingredients: Mapped[List["RecipeIngredientORM"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_recipes_dataset_code"),
        CheckConstraint(
            "slot IN ('staple','protein','vegetable','fruit')", name="ck_recipe_slot"
        ),
        Index("ix_recipes_dataset_version", "dataset_version_id"),
        Index("ix_recipes_review_status", "review_status"),
    )


class RecipeIngredientORM(Base):
    __tablename__ = "recipe_ingredients"

    recipe_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recipe_variants.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    raw_g_per_serving: Mapped[float] = mapped_column(Float, nullable=False)
    retention_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    recipe: Mapped["RecipeVariantORM"] = relationship(back_populates="ingredients")

    __table_args__ = (
        CheckConstraint("raw_g_per_serving > 0", name="ck_ri_raw_g"),
        CheckConstraint("retention_factor > 0 AND retention_factor <= 1", name="ck_ri_retention"),
    )


class NutritionTargetORM(Base):
    __tablename__ = "nutrition_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cohort: Mapped[str] = mapped_column(String(128), nullable=False)
    meal_type: Mapped[str] = mapped_column(String(64), nullable=False, default="lunch")
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="DEMO_ONLY")
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="0.1-synthetic")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    limits: Mapped[List["NutritionTargetLimitORM"]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )


class NutritionTargetLimitORM(Base):
    __tablename__ = "nutrition_target_limits"

    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nutrition_targets.id", ondelete="CASCADE"), primary_key=True
    )
    nutrient_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    min_per_serving: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_per_serving: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    target: Mapped["NutritionTargetORM"] = relationship(back_populates="limits")

    __table_args__ = (
        CheckConstraint(
            "min_per_serving IS NULL OR max_per_serving IS NULL OR min_per_serving <= max_per_serving",
            name="ck_ntl_bounds",
        ),
    )


class ScenarioORM(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_scenario_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nutrition_targets.id"), nullable=False
    )
    meal_type: Mapped[str] = mapped_column(String(64), nullable=False, default="lunch")
    servings_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_idr_per_serving: Mapped[float] = mapped_column(Float, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_repeat_per_family: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    excluded_allergens_json: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    source_label: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic")
    production_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    service_dates_json: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    continuation_of_run_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("optimization_runs.id", ondelete="SET NULL", use_alter=True, name="fk_scenarios_continuation_run"),
        nullable=True,
    )
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    price_overrides: Mapped[List["ScenarioPriceOverrideORM"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    stock_overrides: Mapped[List["ScenarioStockOverrideORM"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    runs: Mapped[List["OptimizationRunORM"]] = relationship(
        back_populates="scenario",
        foreign_keys="[OptimizationRunORM.scenario_id]",
    )

    __table_args__ = (
        CheckConstraint("servings_per_day > 0", name="ck_sc_servings"),
        CheckConstraint("budget_idr_per_serving > 0", name="ck_sc_budget"),
        CheckConstraint("days BETWEEN 1 AND 14", name="ck_sc_days"),
        Index("ix_scenarios_dataset_version", "dataset_version_id"),
        Index("ix_scenarios_parent", "parent_scenario_id"),
        Index("ix_scenarios_kitchen_id", "kitchen_id"),
    )


class ScenarioPriceOverrideORM(Base):
    __tablename__ = "scenario_price_overrides"

    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    price_idr_per_g: Mapped[float] = mapped_column(Float, nullable=False)

    scenario: Mapped["ScenarioORM"] = relationship(back_populates="price_overrides")

    __table_args__ = (CheckConstraint("price_idr_per_g > 0", name="ck_spo_price"),)


class ScenarioStockOverrideORM(Base):
    __tablename__ = "scenario_stock_overrides"

    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    stock_raw_g: Mapped[float] = mapped_column(Float, nullable=False)

    scenario: Mapped["ScenarioORM"] = relationship(back_populates="stock_overrides")

    __table_args__ = (CheckConstraint("stock_raw_g >= 0", name="ck_sso_stock"),)


class OptimizationRunORM(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    price_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    solver_status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    simulation_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    objective_total_idr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_per_serving_average_idr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_bound: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gap_abs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gap_rel: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    solver_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    solver_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_solver_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    solver_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    constraint_audit_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    constraint_diagnostics_json: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    warnings_json: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    scenario: Mapped["ScenarioORM"] = relationship(
        back_populates="runs",
        foreign_keys="[OptimizationRunORM.scenario_id]",
    )
    assignments: Mapped[List["RunAssignmentORM"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    metrics: Mapped[List["RunMetricORM"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    material_usage: Mapped[List["RunMaterialUsageORM"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_runs_scenario_id", "scenario_id"),
        Index("ix_runs_input_sha256", "input_sha256"),
        Index("ix_runs_created_at", "created_at"),
    )


class RunAssignmentORM(Base):
    __tablename__ = "run_assignments"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), primary_key=True
    )
    day_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot: Mapped[str] = mapped_column(String(32), primary_key=True)
    recipe_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recipe_variants.id"), nullable=False
    )
    recipe_name: Mapped[str] = mapped_column(String(255), nullable=False)
    daily_cost_idr_per_serving: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped["OptimizationRunORM"] = relationship(back_populates="assignments")


class RunMetricORM(Base):
    __tablename__ = "run_metrics"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), primary_key=True
    )
    day_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    nutrient_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    run: Mapped["OptimizationRunORM"] = relationship(back_populates="metrics")


class RunMaterialUsageORM(Base):
    __tablename__ = "run_material_usage"

    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id"), primary_key=True
    )
    ingredient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    ingredient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    used_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    available_raw_g: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped["OptimizationRunORM"] = relationship(back_populates="material_usage")


# =====================================================================
# Sprint 3A: Multi-Actor Auth, Kitchen Isolation, Menu Reviews & Vision QC
# =====================================================================


class KitchenORM(Base):
    __tablename__ = "kitchens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str] = mapped_column(String(128), nullable=False, default="SIMULASI")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    memberships: Mapped[List["KitchenMembershipORM"]] = relationship(
        back_populates="kitchen", cascade="all, delete-orphan"
    )


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    memberships: Mapped[List["KitchenMembershipORM"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[List["AuthSessionORM"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class KitchenMembershipORM(Base):
    __tablename__ = "kitchen_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    user: Mapped["UserORM"] = relationship(back_populates="memberships")
    kitchen: Mapped["KitchenORM"] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("user_id", "kitchen_id", name="uq_membership_user_kitchen"),
        CheckConstraint(
            "role IN ('KITCHEN_MANAGER','MENU_PLANNER','QC_OFFICER','NUTRITIONIST')",
            name="ck_membership_role",
        ),
        Index("ix_memberships_user_id", "user_id"),
        Index("ix_memberships_kitchen_id", "kitchen_id"),
    )


class AuthSessionORM(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    active_kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    user: Mapped["UserORM"] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_auth_sessions_token_hash", "token_hash"),
        Index("ix_auth_sessions_user_id", "user_id"),
    )


class AuditEventORM(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_audit_events_kitchen_created", "kitchen_id", "created_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )


class MenuReviewRecordORM(Base):
    __tablename__ = "menu_review_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    planner_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    submitted_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_event_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("recovery_events.id", ondelete="SET NULL"), nullable=True
    )
    inventory_snapshot_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','APPROVED','REVISION_REQUIRED')",
            name="ck_menu_review_status",
        ),
        Index("ix_menu_reviews_kitchen_status", "kitchen_id", "status"),
        Index("ix_menu_reviews_run_id", "run_id"),
    )


class MealBatchORM(Base):
    __tablename__ = "meal_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    menu_review_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("menu_review_records.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False
    )
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(64), nullable=False, default="lunch")
    batch_code: Mapped[str] = mapped_column(String(64), nullable=False)
    planned_servings: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("kitchen_id", "batch_code", name="uq_meal_batches_kitchen_code"),
        CheckConstraint("day_index >= 1", name="ck_meal_batch_day"),
        CheckConstraint("planned_servings > 0", name="ck_meal_batch_servings"),
    )


class QCInspectionORM(Base):
    __tablename__ = "qc_inspections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    menu_review_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("menu_review_records.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False
    )
    meal_batch_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("meal_batches.id", ondelete="SET NULL"), nullable=True
    )
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    review_outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    submitted_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    qc_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manager_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    images: Mapped[List["QCImageORM"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan"
    )
    ai_observations: Mapped[List["QCAIObservationORM"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan"
    )
    human_reviews: Mapped[List["QCHumanReviewORM"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED','AI_ANALYZED','HUMAN_REVIEWED','SUBMITTED','REVIEWED')",
            name="ck_qc_inspection_status",
        ),
        CheckConstraint(
            "review_outcome IS NULL OR review_outcome IN ('ACCEPTED_FOR_RECORD','REVISION_REQUIRED','RETAKE_REQUIRED')",
            name="ck_qc_review_outcome",
        ),
        CheckConstraint("day_index >= 1", name="ck_qc_day_index"),
        Index("ix_qc_inspections_kitchen_status", "kitchen_id", "status"),
        Index("ix_qc_inspections_run_id", "run_id"),
    )


class QCImageORM(Base):
    __tablename__ = "qc_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inspection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("qc_inspections.id", ondelete="CASCADE"), nullable=False
    )
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    original_filename_sanitized: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    exif_stripped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    inspection: Mapped["QCInspectionORM"] = relationship(back_populates="images")

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_qc_image_size"),
        Index("ix_qc_images_inspection", "inspection_id"),
    )


class QCAIObservationORM(Base):
    """Immutable original AI Vision analysis record (never overwritten by human corrections)."""

    __tablename__ = "qc_ai_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inspection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("qc_inspections.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("qc_images.id", ondelete="CASCADE"), nullable=False
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    is_live_ai: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_identifier: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="qc-vision-v1")
    raw_response_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validated_output_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    comparison_findings_json: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    inspection: Mapped["QCInspectionORM"] = relationship(back_populates="ai_observations")

    __table_args__ = (Index("ix_qc_ai_obs_inspection", "inspection_id"),)


class QCHumanReviewORM(Base):
    """Human-in-the-loop confirmation/correction linked to immutable AI observations."""

    __tablename__ = "qc_human_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inspection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("qc_inspections.id", ondelete="CASCADE"), nullable=False
    )
    ai_observation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("qc_ai_observations.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    corrected_components_json: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    request_retake: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    inspection: Mapped["QCInspectionORM"] = relationship(back_populates="human_reviews")

    __table_args__ = (Index("ix_qc_human_reviews_inspection", "inspection_id"),)


# =====================================================================
# Sprint 3A.6: Inventory Data Quality, Lot Availability & Market Context
# =====================================================================


class DatasetSourceORM(Base):
    __tablename__ = "dataset_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="SET NULL"), nullable=True
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    license: Mapped[str] = mapped_column(String(128), nullable=False)
    license_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dataset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    allowed_use: Mapped[str] = mapped_column(String(128), nullable=False)
    transformation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_dataset_sources_name", "source_name"),)


class IngredientMappingORM(Base):
    __tablename__ = "ingredient_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=True
    )
    dataset_version_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=True
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("dataset_sources.id", ondelete="SET NULL"), nullable=True
    )
    external_product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    external_product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ingredient_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True
    )
    ingredient_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    standard_unit: Mapped[str] = mapped_column(String(32), nullable=False, default="kg")
    conversion_factor_to_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    density_g_per_ml: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_weight_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNMAPPED")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    reviewer_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "mapping_status IN ('MAPPED','UNMAPPED','AMBIGUOUS','REJECTED','UNIT_ERROR')",
            name="ck_ing_mapping_status",
        ),
        Index(
            "ix_ing_mappings_scope",
            "kitchen_id",
            "dataset_version_id",
            "external_product_code",
        ),
    )


class InventoryLotORM(Base):
    __tablename__ = "inventory_lots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    lot_code: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("dataset_sources.id", ondelete="SET NULL"), nullable=True
    )
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic")
    recorded_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    damaged_raw_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purchase_document_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("purchase_documents.id", ondelete="SET NULL"), nullable=True
    )
    verified_physical_raw_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="VERIFIED")
    safety_hold_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    unit_original: Mapped[str] = mapped_column(String(32), nullable=False, default="g")
    quantity_original: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("kitchen_id", "dataset_version_id", "lot_code", name="uq_inv_lot_code"),
        CheckConstraint("recorded_raw_g >= 0", name="ck_inv_lot_recorded_nonneg"),
        CheckConstraint("damaged_raw_g >= 0", name="ck_inv_lot_damaged_nonneg"),
        CheckConstraint(
            "verification_status IN ('VERIFIED','UNVERIFIED','UNKNOWN','DISCREPANCY','QUARANTINED')",
            name="ck_inv_lot_verif_status",
        ),
        CheckConstraint(
            "safety_hold_status IN ('NONE','ON_HOLD','REJECTED_DISPOSED')",
            name="ck_inv_lot_safety_hold",
        ),
        Index("ix_inv_lots_scope", "kitchen_id", "dataset_version_id", "ingredient_id"),
    )


class InventoryMovementORM(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    lot_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity_delta_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    original_value: Mapped[float] = mapped_column(Float, nullable=False)
    original_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_document_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("dataset_sources.id", ondelete="SET NULL"), nullable=True
    )
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quarantined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quarantine_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("kitchen_id", "dataset_version_id", "idempotency_key", name="uq_inv_mov_idemp"),
        CheckConstraint(
            "movement_type IN ('OPENING_BALANCE','GOODS_RECEIPT','PRODUCTION_CONSUMPTION','RESERVATION','RESERVATION_RELEASE','ADJUSTMENT','DAMAGE','DISPOSAL','PHYSICAL_COUNT_RECONCILIATION')",
            name="ck_inv_mov_type",
        ),
        Index("ix_inv_mov_scope_time", "kitchen_id", "dataset_version_id", "event_at"),
    )


class StockReservationORM(Base):
    __tablename__ = "stock_reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    lot_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    menu_review_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("menu_review_records.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="SET NULL"), nullable=True
    )
    reserved_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    production_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("kitchen_id", "dataset_version_id", "idempotency_key", name="uq_stock_res_idemp"),
        CheckConstraint("reserved_raw_g > 0", name="ck_stock_res_pos"),
        CheckConstraint("status IN ('ACTIVE','RELEASED','CONSUMED')", name="ck_stock_res_status"),
        Index("ix_stock_res_scope", "kitchen_id", "dataset_version_id", "ingredient_id"),
    )


class SupplierDeliveryORM(Base):
    __tablename__ = "supplier_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("dataset_sources.id", ondelete="SET NULL"), nullable=True
    )
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    received_raw_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    original_value: Mapped[float] = mapped_column(Float, nullable=False)
    original_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROMISED")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("kitchen_id", "dataset_version_id", "idempotency_key", name="uq_sup_deliv_idemp"),
        CheckConstraint("expected_raw_g > 0", name="ck_sup_deliv_exp_pos"),
        CheckConstraint("received_raw_g >= 0", name="ck_sup_deliv_rec_nonneg"),
        CheckConstraint(
            "status IN ('PROMISED','DELAYED','PARTIAL','RECEIVED','CANCELLED')",
            name="ck_sup_deliv_status",
        ),
        Index("ix_sup_deliv_scope", "kitchen_id", "dataset_version_id", "ingredient_id"),
    )


class InventoryReconciliationORM(Base):
    __tablename__ = "inventory_reconciliations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    lot_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    recorded_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    physical_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    discrepancy_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCREPANCY_DETECTED")
    counted_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint("recorded_raw_g >= 0", name="ck_inv_rec_recorded_nonneg"),
        CheckConstraint("physical_raw_g >= 0", name="ck_inv_rec_physical_nonneg"),
        CheckConstraint(
            "status IN ('MATCHED','DISCREPANCY_DETECTED','RECONCILED')",
            name="ck_inv_rec_status",
        ),
        Index("ix_inv_recon_scope", "kitchen_id", "dataset_version_id", "ingredient_id"),
    )


class MarketPriceReferenceORM(Base):
    __tablename__ = "market_price_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("dataset_sources.id", ondelete="SET NULL"), nullable=True
    )
    commodity_code: Mapped[str] = mapped_column(String(64), nullable=False)
    commodity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_ingredient_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    region: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="IDR/kg")
    price_idr_per_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_provenance: Mapped[str] = mapped_column(
        String(40), nullable=False, default="OFFICIAL_MARKET_REFERENCE"
    )
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    quality_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="REFERENCE_ONLY"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("price_value > 0", name="ck_market_price_pos"),
        CheckConstraint(
            "price_provenance IN ('OFFICIAL_MARKET_REFERENCE','ACTUAL_SUPPLIER','SYNTHETIC_EXAMPLE','UNKNOWN')",
            name="ck_market_provenance",
        ),
        Index(
            "ix_market_ref_commodity_date",
            "canonical_ingredient_code",
            "region",
            "observed_date",
        ),
    )


class RecoveryEventORM(Base):
    __tablename__ = "recovery_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    baseline_menu_review_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("menu_review_records.id", ondelete="SET NULL"), nullable=True
    )
    baseline_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False
    )
    baseline_scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    disruption_types_json: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    disruption_summary: Mapped[str] = mapped_column(Text, nullable=False)
    disruption_input_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    affected_slots_json: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    impact_analysis_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    min_disruption_scenario_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    min_disruption_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="SET NULL"), nullable=True
    )
    min_cost_scenario_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    min_cost_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="SET NULL"), nullable=True
    )
    selected_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    selected_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="SET NULL"), nullable=True
    )
    submitted_review_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("menu_review_records.id", ondelete="SET NULL"), nullable=True
    )
    inventory_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    comparison_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ANALYZED")
    incident_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ingredient_incidents.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ANALYZED','SUBMITTED','APPROVED','REVISION_REQUIRED','INFEASIBLE')",
            name="ck_recovery_event_status",
        ),
        CheckConstraint(
            "selected_mode IS NULL OR selected_mode IN ('MIN_DISRUPTION','MIN_COST')",
            name="ck_recovery_selected_mode",
        ),
        Index("ix_recovery_events_kitchen_created", "kitchen_id", "created_at"),
        Index("ix_recovery_events_baseline_run", "baseline_run_id"),
    )


# =====================================================================
# Sprint 3B.1 & 3C: Authoritative Operational Plans & Critical Incidents
# =====================================================================


class IngredientIncidentORM(Base):
    __tablename__ = "ingredient_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="HIGH")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ON_HOLD")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    reporter_role: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivery_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    related_batch_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    exposure_status: Mapped[str] = mapped_column(
        String(48), nullable=False, default="EXPOSURE_UNKNOWN"
    )
    exposure_summary_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    affected_plans_json: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    recovery_event_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("recovery_events.id", ondelete="SET NULL"), nullable=True
    )
    disposal_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disposal_authorized_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    disposal_authorized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disposal_executed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    disposal_executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    affected_lots: Mapped[List["IncidentAffectedLotORM"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    actions: Mapped[List["IncidentActionORM"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    images: Mapped[List["IncidentImageORM"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("kitchen_id", "idempotency_key", name="uq_incident_kitchen_idemp"),
        CheckConstraint(
            "category IN ('SPOILAGE','SUSPECTED_CONTAMINATION','DAMAGED_PACKAGING',"
            "'ABNORMAL_ODOR_APPEARANCE','SUPPLIER_RECALL','TEMPERATURE_EXCURSION','UNKNOWN_CONDITION')",
            name="ck_incident_category",
        ),
        CheckConstraint(
            "severity IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_incident_severity",
        ),
        CheckConstraint(
            "status IN ('REPORTED','ON_HOLD','UNDER_REVIEW','REJECTED','RESOLVED','CLOSED')",
            name="ck_incident_status",
        ),
        CheckConstraint(
            "exposure_status IN ('NO_RECORDED_PRODUCTION_EXPOSURE','POTENTIAL_PRODUCTION_EXPOSURE','EXPOSURE_UNKNOWN')",
            name="ck_incident_exposure_status",
        ),
        Index("ix_incidents_kitchen_status", "kitchen_id", "status", "created_at"),
    )


class IncidentAffectedLotORM(Base):
    __tablename__ = "incident_affected_lots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredient_incidents.id", ondelete="CASCADE"), nullable=False
    )
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    ingredient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    lot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_lots.id", ondelete="CASCADE"), nullable=False
    )
    lot_code: Mapped[str] = mapped_column(String(128), nullable=False)
    ingredient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    ingredient_name: Mapped[str] = mapped_column(String(255), nullable=False)
    lot_safety_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ON_HOLD"
    )
    prior_lot_verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_raw_g_snapshot: Mapped[float] = mapped_column(Float, nullable=False)
    usable_before_hold_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    usable_after_hold_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    reason_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_release_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    incident: Mapped["IngredientIncidentORM"] = relationship(back_populates="affected_lots")

    __table_args__ = (
        UniqueConstraint("incident_id", "lot_id", name="uq_incident_lot"),
        CheckConstraint(
            "lot_safety_status IN ('ON_HOLD','REJECTED_DISPOSED','RELEASED_EXTERNAL_AUTH')",
            name="ck_incident_lot_safety_status",
        ),
        Index(
            "ix_incident_lots_scope",
            "kitchen_id",
            "dataset_version_id",
            "lot_id",
            "lot_safety_status",
        ),
    )


class IncidentActionORM(Base):
    __tablename__ = "incident_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredient_incidents.id", ondelete="CASCADE"), nullable=False
    )
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    incident: Mapped["IngredientIncidentORM"] = relationship(back_populates="actions")

    __table_args__ = (Index("ix_incident_actions_incident", "incident_id", "created_at"),)


class IncidentImageORM(Base):
    __tablename__ = "incident_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingredient_incidents.id", ondelete="CASCADE"), nullable=False
    )
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    original_filename_sanitized: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    exif_stripped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    incident: Mapped["IngredientIncidentORM"] = relationship(back_populates="images")

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_incident_image_size"),
        Index("ix_incident_images_incident", "incident_id"),
    )


class OperationalPlanAssignmentORM(Base):
    __tablename__ = "operational_plan_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    menu_review_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("menu_review_records.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False
    )
    production_date: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    service_dates_json: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    meal_type: Mapped[str] = mapped_column(String(64), nullable=False, default="lunch")
    target_cohort: Mapped[str] = mapped_column(String(128), nullable=False, default="DEFAULT")
    batch_label: Mapped[str] = mapped_column(String(64), nullable=False, default="DEFAULT")
    operational_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE"
    )
    # Non-null ONLY when operational_status IN ('ACTIVE','ON_HOLD'), enforcing <= 1 effective plan per scope at DB level.
    active_scope_key: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True
    )
    supersedes_assignment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("operational_plan_assignments.id", ondelete="SET NULL"), nullable=True
    )
    hold_incident_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ingredient_incidents.id", ondelete="SET NULL"), nullable=True
    )
    hold_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    held_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inventory_snapshot_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("kitchen_id", "idempotency_key", name="uq_op_plan_kitchen_idemp"),
        CheckConstraint(
            "operational_status IN ('ACTIVE','ON_HOLD','SUPERSEDED')",
            name="ck_op_plan_status",
        ),
        Index("ix_op_plans_kitchen_status", "kitchen_id", "operational_status"),
        Index("ix_op_plans_review_id", "menu_review_id"),
    )

    service_date_rows: Mapped[List["OperationalPlanServiceDateORM"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class OperationalPlanServiceDateORM(Base):
    __tablename__ = "operational_plan_service_dates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("operational_plan_assignments.id", ondelete="CASCADE"), nullable=False
    )
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_cohort: Mapped[str] = mapped_column(String(128), nullable=False)
    batch_label: Mapped[str] = mapped_column(String(64), nullable=False)
    active_date_scope_key: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True
    )

    assignment: Mapped["OperationalPlanAssignmentORM"] = relationship(
        back_populates="service_date_rows"
    )

    __table_args__ = (
        CheckConstraint("day_index BETWEEN 1 AND 14", name="ck_op_service_date_day_idx"),
        UniqueConstraint("assignment_id", "service_date", name="uq_op_service_dates_assign_date"),
        UniqueConstraint("assignment_id", "day_index", name="uq_op_service_dates_assign_day"),
        Index("ix_op_service_dates_kitchen_date", "kitchen_id", "service_date"),
        Index("ix_op_service_dates_assignment", "assignment_id"),
    )


class KitchenStockCustodianAssignmentORM(Base):
    __tablename__ = "kitchen_stock_custodian_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    custodian_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    # Non-null ONLY when status == 'ACTIVE', enforcing <= 1 active stock custodian per kitchen at DB level.
    active_kitchen_key: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    effective_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')", name="ck_custodian_status"),
        Index("ix_custodian_kitchen_status", "kitchen_id", "status"),
        Index("ix_custodian_user_status", "custodian_user_id", "status"),
    )


class PurchaseDocumentORM(Base):
    __tablename__ = "purchase_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    linked_run_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("optimization_runs.id", ondelete="SET NULL"), nullable=True
    )
    linked_recovery_event_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("recovery_events.id", ondelete="SET NULL"), nullable=True
    )
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_amount_idr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="NO_EVIDENCE"
    )
    document_storage_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    document_mime_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    document_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    document_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    document_original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    exif_stripped: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    recorded_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    lines: Mapped[List["PurchaseDocumentLineORM"]] = relationship(
        back_populates="purchase_document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "evidence_status IN ('NO_EVIDENCE','RECEIPT_UPLOADED','GOODS_RECEIVED','VERIFIED_MATCH','DISCREPANCY_FLAGGED')",
            name="ck_purchase_doc_evidence_status",
        ),
        Index("ix_purchase_docs_kitchen_date", "kitchen_id", "purchase_date"),
        Index("ix_purchase_docs_kitchen_status", "kitchen_id", "evidence_status"),
    )


class PurchaseDocumentLineORM(Base):
    __tablename__ = "purchase_document_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purchase_document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_documents.id", ondelete="CASCADE"), nullable=False
    )
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True
    )
    ingredient_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    unit_label: Mapped[str] = mapped_column(String(32), nullable=False, default="kg")
    unit_price_idr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    line_total_idr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lot_code_hint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    expiry_date_hint: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    purchase_document: Mapped["PurchaseDocumentORM"] = relationship(back_populates="lines")

    __table_args__ = (
        CheckConstraint("quantity_raw_g > 0", name="ck_purchase_line_qty_positive"),
        Index("ix_purchase_lines_doc", "purchase_document_id"),
    )


class GoodsReceiptRecordORM(Base):
    __tablename__ = "goods_receipt_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kitchen_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False
    )
    purchase_document_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("purchase_documents.id", ondelete="SET NULL"), nullable=True
    )
    dataset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dataset_versions.id"), nullable=False
    )
    ingredient_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True
    )
    ingredient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    lot_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    lot_code: Mapped[str] = mapped_column(String(128), nullable=False)
    received_raw_g: Mapped[float] = mapped_column(Float, nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    condition_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="GOOD"
    )
    received_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        CheckConstraint("received_raw_g > 0", name="ck_goods_receipt_qty_positive"),
        CheckConstraint(
            "condition_status IN ('GOOD','DAMAGED','QUARANTINED','REJECTED')",
            name="ck_goods_receipt_condition",
        ),
        Index("ix_goods_receipts_kitchen_date", "kitchen_id", "received_at"),
        Index("ix_goods_receipts_purchase_doc", "purchase_document_id"),
    )
