"""Sprint 3A: Multi-actor RBAC, kitchen isolation, menu reviews, and AI Vision QC tables.

Revision ID: 0002_sprint3a_rbac_and_qc
Revises: 0001_initial_schema
Create Date: 2026-11-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sprint3a_rbac_and_qc"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kitchens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=False, server_default="SIMULASI"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "kitchen_memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "kitchen_id", name="uq_membership_user_kitchen"),
        sa.CheckConstraint(
            "role IN ('KITCHEN_MANAGER','MENU_PLANNER','QC_OFFICER','NUTRITIONIST')",
            name="ck_membership_role",
        ),
    )
    op.create_index("ix_memberships_user_id", "kitchen_memberships", ["user_id"])
    op.create_index("ix_memberships_kitchen_id", "kitchen_memberships", ["kitchen_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "active_kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_audit_events_kitchen_created", "audit_events", ["kitchen_id", "created_at"]
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])

    # Non-destructive addition of kitchen_id on existing scenarios table
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.add_column(sa.Column("kitchen_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_scenarios_kitchen_id",
            "kitchens",
            ["kitchen_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_scenarios_kitchen_id", ["kitchen_id"])

    op.create_table(
        "menu_review_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("planner_notes", sa.Text(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "submitted_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "reviewed_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','APPROVED','REVISION_REQUIRED')",
            name="ck_menu_review_status",
        ),
    )
    op.create_index(
        "ix_menu_reviews_kitchen_status", "menu_review_records", ["kitchen_id", "status"]
    )
    op.create_index("ix_menu_reviews_run_id", "menu_review_records", ["run_id"])

    op.create_table(
        "meal_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "menu_review_id",
            sa.String(length=36),
            sa.ForeignKey("menu_review_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(length=64), nullable=False, server_default="lunch"),
        sa.Column("batch_code", sa.String(length=64), nullable=False),
        sa.Column("planned_servings", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kitchen_id", "batch_code", name="uq_meal_batches_kitchen_code"),
        sa.CheckConstraint("day_index >= 1", name="ck_meal_batch_day"),
        sa.CheckConstraint("planned_servings > 0", name="ck_meal_batch_servings"),
    )

    op.create_table(
        "qc_inspections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "menu_review_id",
            sa.String(length=36),
            sa.ForeignKey("menu_review_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meal_batch_id",
            sa.String(length=36),
            sa.ForeignKey("meal_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="CREATED"),
        sa.Column("review_outcome", sa.String(length=32), nullable=True),
        sa.Column(
            "created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "submitted_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "reviewed_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("qc_notes", sa.Text(), nullable=True),
        sa.Column("manager_notes", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('CREATED','AI_ANALYZED','HUMAN_REVIEWED','SUBMITTED','REVIEWED')",
            name="ck_qc_inspection_status",
        ),
        sa.CheckConstraint(
            "review_outcome IS NULL OR review_outcome IN ('ACCEPTED_FOR_RECORD','REVISION_REQUIRED','RETAKE_REQUIRED')",
            name="ck_qc_review_outcome",
        ),
        sa.CheckConstraint("day_index >= 1", name="ck_qc_day_index"),
    )
    op.create_index("ix_qc_inspections_kitchen_status", "qc_inspections", ["kitchen_id", "status"])
    op.create_index("ix_qc_inspections_run_id", "qc_inspections", ["run_id"])

    op.create_table(
        "qc_images",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "inspection_id",
            sa.String(length=36),
            sa.ForeignKey("qc_inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("original_filename_sanitized", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("exif_stripped", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column(
            "uploaded_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_qc_image_size"),
    )
    op.create_index("ix_qc_images_inspection", "qc_images", ["inspection_id"])

    op.create_table(
        "qc_ai_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "inspection_id",
            sa.String(length=36),
            sa.ForeignKey("qc_inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "image_id",
            sa.String(length=36),
            sa.ForeignKey("qc_images.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_mode", sa.String(length=32), nullable=False),
        sa.Column("is_live_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_identifier", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False, server_default="qc-vision-v1"),
        sa.Column("raw_response_json", sa.JSON(), nullable=False),
        sa.Column("validated_output_json", sa.JSON(), nullable=False),
        sa.Column("comparison_findings_json", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qc_ai_obs_inspection", "qc_ai_observations", ["inspection_id"])

    op.create_table(
        "qc_human_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "inspection_id",
            sa.String(length=36),
            sa.ForeignKey("qc_inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ai_observation_id",
            sa.String(length=36),
            sa.ForeignKey("qc_ai_observations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewer_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("corrected_components_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("request_retake", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_qc_human_reviews_inspection", "qc_human_reviews", ["inspection_id"])


def downgrade() -> None:
    op.drop_table("qc_human_reviews")
    op.drop_table("qc_ai_observations")
    op.drop_table("qc_images")
    op.drop_table("qc_inspections")
    op.drop_table("meal_batches")
    op.drop_table("menu_review_records")

    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_index("ix_scenarios_kitchen_id")
        batch_op.drop_constraint("fk_scenarios_kitchen_id", type_="foreignkey")
        batch_op.drop_column("kitchen_id")

    op.drop_table("audit_events")
    op.drop_table("auth_sessions")
    op.drop_table("kitchen_memberships")
    op.drop_table("users")
    op.drop_table("kitchens")
