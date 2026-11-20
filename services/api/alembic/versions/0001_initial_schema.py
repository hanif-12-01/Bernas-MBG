"""Initial persistent schema for GiziOptima Sprint 2A.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("ingestion_metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dataset_versions_is_active", "dataset_versions", ["is_active"])
    op.create_index("ix_dataset_versions_created_at", "dataset_versions", ["created_at"])

    op.create_table(
        "ingredients",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("edible_fraction", sa.Float(), nullable=False),
        sa.Column("allergens_json", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("dataset_version_id", "code", name="uq_ingredients_dataset_code"),
        sa.CheckConstraint("edible_fraction > 0 AND edible_fraction <= 1", name="ck_ing_edible"),
    )
    op.create_index("ix_ingredients_dataset_version", "ingredients", ["dataset_version_id"])

    op.create_table(
        "ingredient_nutrients",
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("energy_kcal_100g", sa.Float(), nullable=True),
        sa.Column("protein_g_100g", sa.Float(), nullable=True),
        sa.Column("fat_g_100g", sa.Float(), nullable=True),
        sa.Column("carb_g_100g", sa.Float(), nullable=True),
        sa.Column("fiber_g_100g", sa.Float(), nullable=True),
        sa.Column("iron_mg_100g", sa.Float(), nullable=True),
    )

    op.create_table(
        "ingredient_prices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price_idr_per_g", sa.Float(), nullable=False),
        sa.Column("original_value", sa.Float(), nullable=False),
        sa.Column("original_unit", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=False),
        sa.Column("observed_at", sa.Date(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.UniqueConstraint("dataset_version_id", "ingredient_id", name="uq_prices_dataset_ing"),
        sa.CheckConstraint("price_idr_per_g > 0", name="ck_price_positive"),
    )
    op.create_index("ix_prices_dataset_version", "ingredient_prices", ["dataset_version_id"])

    op.create_table(
        "dataset_stock_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stock_raw_g", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dataset_version_id", "ingredient_id", name="uq_stock_dataset_ing"),
        sa.CheckConstraint("stock_raw_g >= 0", name="ck_stock_nonneg"),
    )
    op.create_index("ix_stock_dataset_version", "dataset_stock_snapshots", ["dataset_version_id"])

    op.create_table(
        "recipe_variants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("reviewer", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allergen_tags_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("dataset_version_id", "code", name="uq_recipes_dataset_code"),
        sa.CheckConstraint(
            "slot IN ('staple','protein','vegetable','fruit')", name="ck_recipe_slot"
        ),
    )
    op.create_index("ix_recipes_dataset_version", "recipe_variants", ["dataset_version_id"])
    op.create_index("ix_recipes_review_status", "recipe_variants", ["review_status"])

    op.create_table(
        "recipe_ingredients",
        sa.Column(
            "recipe_id",
            sa.String(length=36),
            sa.ForeignKey("recipe_variants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("raw_g_per_serving", sa.Float(), nullable=False),
        sa.Column("retention_factor", sa.Float(), nullable=False),
        sa.CheckConstraint("raw_g_per_serving > 0", name="ck_ri_raw_g"),
        sa.CheckConstraint("retention_factor > 0 AND retention_factor <= 1", name="ck_ri_retention"),
    )

    op.create_table(
        "nutrition_targets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("cohort", sa.String(length=128), nullable=False),
        sa.Column("meal_type", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "nutrition_target_limits",
        sa.Column(
            "target_id",
            sa.String(length=36),
            sa.ForeignKey("nutrition_targets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("nutrient_key", sa.String(length=64), primary_key=True),
        sa.Column("min_per_serving", sa.Float(), nullable=True),
        sa.Column("max_per_serving", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "min_per_serving IS NULL OR max_per_serving IS NULL OR min_per_serving <= max_per_serving",
            name="ck_ntl_bounds",
        ),
    )

    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "parent_scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(length=36),
            sa.ForeignKey("nutrition_targets.id"),
            nullable=False,
        ),
        sa.Column("meal_type", sa.String(length=64), nullable=False),
        sa.Column("servings_per_day", sa.Integer(), nullable=False),
        sa.Column("budget_idr_per_serving", sa.Float(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("max_repeat_per_family", sa.Integer(), nullable=False),
        sa.Column("excluded_allergens_json", sa.JSON(), nullable=False),
        sa.Column("source_label", sa.String(length=32), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("servings_per_day > 0", name="ck_sc_servings"),
        sa.CheckConstraint("budget_idr_per_serving > 0", name="ck_sc_budget"),
        sa.CheckConstraint("days BETWEEN 1 AND 14", name="ck_sc_days"),
    )
    op.create_index("ix_scenarios_dataset_version", "scenarios", ["dataset_version_id"])
    op.create_index("ix_scenarios_parent", "scenarios", ["parent_scenario_id"])

    op.create_table(
        "scenario_price_overrides",
        sa.Column(
            "scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("price_idr_per_g", sa.Float(), nullable=False),
        sa.CheckConstraint("price_idr_per_g > 0", name="ck_spo_price"),
    )

    op.create_table(
        "scenario_stock_overrides",
        sa.Column(
            "scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("stock_raw_g", sa.Float(), nullable=False),
        sa.CheckConstraint("stock_raw_g >= 0", name="ck_sso_stock"),
    )

    op.create_table(
        "optimization_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id"),
            nullable=False,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column("price_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("solver_status", sa.String(length=32), nullable=False),
        sa.Column("validation_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("simulation_only", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("objective_total_idr", sa.Float(), nullable=True),
        sa.Column("cost_per_serving_average_idr", sa.Float(), nullable=True),
        sa.Column("best_bound", sa.Float(), nullable=True),
        sa.Column("gap_abs", sa.Float(), nullable=True),
        sa.Column("gap_rel", sa.Float(), nullable=True),
        sa.Column("solver_name", sa.String(length=64), nullable=True),
        sa.Column("solver_version", sa.String(length=64), nullable=True),
        sa.Column("raw_solver_status", sa.String(length=64), nullable=True),
        sa.Column("solver_seconds", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("constraint_audit_json", sa.JSON(), nullable=False),
        sa.Column("constraint_diagnostics_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runs_scenario_id", "optimization_runs", ["scenario_id"])
    op.create_index("ix_runs_input_sha256", "optimization_runs", ["input_sha256"])
    op.create_index("ix_runs_created_at", "optimization_runs", ["created_at"])

    op.create_table(
        "run_assignments",
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day_index", sa.Integer(), primary_key=True),
        sa.Column("slot", sa.String(length=32), primary_key=True),
        sa.Column(
            "recipe_id",
            sa.String(length=36),
            sa.ForeignKey("recipe_variants.id"),
            nullable=False,
        ),
        sa.Column("recipe_name", sa.String(length=255), nullable=False),
        sa.Column("daily_cost_idr_per_serving", sa.Float(), nullable=False),
    )

    op.create_table(
        "run_metrics",
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day_index", sa.Integer(), primary_key=True),
        sa.Column("nutrient_key", sa.String(length=64), primary_key=True),
        sa.Column("actual_value", sa.Float(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
    )

    op.create_table(
        "run_material_usage",
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id"),
            primary_key=True,
        ),
        sa.Column("ingredient_code", sa.String(length=64), nullable=False),
        sa.Column("ingredient_name", sa.String(length=255), nullable=False),
        sa.Column("used_raw_g", sa.Float(), nullable=False),
        sa.Column("available_raw_g", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("run_material_usage")
    op.drop_table("run_metrics")
    op.drop_table("run_assignments")
    op.drop_table("optimization_runs")
    op.drop_table("scenario_stock_overrides")
    op.drop_table("scenario_price_overrides")
    op.drop_table("scenarios")
    op.drop_table("nutrition_target_limits")
    op.drop_table("nutrition_targets")
    op.drop_table("recipe_ingredients")
    op.drop_table("recipe_variants")
    op.drop_table("dataset_stock_snapshots")
    op.drop_table("ingredient_prices")
    op.drop_table("ingredient_nutrients")
    op.drop_table("ingredients")
    op.drop_table("dataset_versions")
