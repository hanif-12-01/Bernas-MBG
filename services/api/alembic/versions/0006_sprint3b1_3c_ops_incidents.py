"""Sprint 3B.1 & 3C: Authoritative operational plan assignments and critical ingredient incident holds.

Revision ID: 0006_sprint3b1_3c_ops_incidents
Revises: 0005_sprint3b_recovery
Create Date: 2026-11-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_sprint3b1_3c_ops_incidents"
down_revision: Union[str, None] = "0005_sprint3b_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingredient_incidents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False, server_default="HIGH"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ON_HOLD"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reported_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("reporter_role", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("delivery_ref", sa.String(length=128), nullable=True),
        sa.Column("related_batch_code", sa.String(length=64), nullable=True),
        sa.Column(
            "exposure_status",
            sa.String(length=48),
            nullable=False,
            server_default="EXPOSURE_UNKNOWN",
        ),
        sa.Column("exposure_summary_json", sa.JSON(), nullable=False),
        sa.Column("affected_plans_json", sa.JSON(), nullable=False),
        sa.Column(
            "recovery_event_id",
            sa.String(length=36),
            sa.ForeignKey("recovery_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kitchen_id", "idempotency_key", name="uq_incident_kitchen_idemp"),
        sa.CheckConstraint(
            "category IN ('SPOILAGE','SUSPECTED_CONTAMINATION','DAMAGED_PACKAGING',"
            "'ABNORMAL_ODOR_APPEARANCE','SUPPLIER_RECALL','TEMPERATURE_EXCURSION','UNKNOWN_CONDITION')",
            name="ck_incident_category",
        ),
        sa.CheckConstraint(
            "severity IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_incident_severity",
        ),
        sa.CheckConstraint(
            "status IN ('REPORTED','ON_HOLD','UNDER_REVIEW','REJECTED','RESOLVED','CLOSED')",
            name="ck_incident_status",
        ),
        sa.CheckConstraint(
            "exposure_status IN ('NO_RECORDED_PRODUCTION_EXPOSURE','POTENTIAL_PRODUCTION_EXPOSURE','EXPOSURE_UNKNOWN')",
            name="ck_incident_exposure_status",
        ),
    )
    op.create_index(
        "ix_incidents_kitchen_status",
        "ingredient_incidents",
        ["kitchen_id", "status", "created_at"],
    )

    op.create_table(
        "incident_affected_lots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "incident_id",
            sa.String(length=36),
            sa.ForeignKey("ingredient_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lot_id",
            sa.String(length=36),
            sa.ForeignKey("inventory_lots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lot_code", sa.String(length=128), nullable=False),
        sa.Column("ingredient_code", sa.String(length=64), nullable=False),
        sa.Column("ingredient_name", sa.String(length=255), nullable=False),
        sa.Column(
            "lot_safety_status",
            sa.String(length=32),
            nullable=False,
            server_default="ON_HOLD",
        ),
        sa.Column("prior_lot_verification_status", sa.String(length=32), nullable=False),
        sa.Column("recorded_raw_g_snapshot", sa.Float(), nullable=False),
        sa.Column("usable_before_hold_raw_g", sa.Float(), nullable=False),
        sa.Column("usable_after_hold_raw_g", sa.Float(), nullable=False),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("external_release_reference", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("incident_id", "lot_id", name="uq_incident_lot"),
        sa.CheckConstraint(
            "lot_safety_status IN ('ON_HOLD','REJECTED_DISPOSED','RELEASED_EXTERNAL_AUTH')",
            name="ck_incident_lot_safety_status",
        ),
    )
    op.create_index(
        "ix_incident_lots_scope",
        "incident_affected_lots",
        ["kitchen_id", "dataset_version_id", "lot_id", "lot_safety_status"],
    )

    op.create_table(
        "incident_actions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "incident_id",
            sa.String(length=36),
            sa.ForeignKey("ingredient_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_incident_actions_incident",
        "incident_actions",
        ["incident_id", "created_at"],
    )

    op.create_table(
        "incident_images",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "incident_id",
            sa.String(length=36),
            sa.ForeignKey("ingredient_incidents.id", ondelete="CASCADE"),
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
            "uploaded_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_incident_image_size"),
    )
    op.create_index(
        "ix_incident_images_incident",
        "incident_images",
        ["incident_id"],
    )

    op.create_table(
        "operational_plan_assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "menu_review_id",
            sa.String(length=36),
            sa.ForeignKey("menu_review_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("production_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("meal_type", sa.String(length=64), nullable=False, server_default="lunch"),
        sa.Column("target_cohort", sa.String(length=128), nullable=False, server_default="DEFAULT"),
        sa.Column("batch_label", sa.String(length=64), nullable=False, server_default="DEFAULT"),
        sa.Column("operational_status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("active_scope_key", sa.String(length=255), nullable=True, unique=True),
        sa.Column(
            "supersedes_assignment_id",
            sa.String(length=36),
            sa.ForeignKey("operational_plan_assignments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "hold_incident_id",
            sa.String(length=36),
            sa.ForeignKey("ingredient_incidents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("hold_reason", sa.Text(), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "activated_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inventory_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kitchen_id", "idempotency_key", name="uq_op_plan_kitchen_idemp"),
        sa.CheckConstraint(
            "operational_status IN ('ACTIVE','ON_HOLD','SUPERSEDED')",
            name="ck_op_plan_status",
        ),
    )
    op.create_index(
        "ix_op_plans_kitchen_status",
        "operational_plan_assignments",
        ["kitchen_id", "operational_status"],
    )
    op.create_index(
        "ix_op_plans_review_id",
        "operational_plan_assignments",
        ["menu_review_id"],
    )

    with op.batch_alter_table("inventory_lots") as batch_op:
        batch_op.add_column(
            sa.Column(
                "safety_hold_status",
                sa.String(length=32),
                nullable=False,
                server_default="NONE",
            )
        )
        batch_op.create_check_constraint(
            "ck_inv_lot_safety_hold",
            "safety_hold_status IN ('NONE','ON_HOLD','REJECTED_DISPOSED')",
        )

    with op.batch_alter_table("recovery_events") as batch_op:
        batch_op.add_column(sa.Column("incident_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_recovery_events_incident",
            "ingredient_incidents",
            ["incident_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("recovery_events") as batch_op:
        batch_op.drop_constraint("fk_recovery_events_incident", type_="foreignkey")
        batch_op.drop_column("incident_id")

    with op.batch_alter_table("inventory_lots") as batch_op:
        batch_op.drop_constraint("ck_inv_lot_safety_hold", type_="check")
        batch_op.drop_column("safety_hold_status")

    op.drop_index("ix_op_plans_review_id", table_name="operational_plan_assignments")
    op.drop_index("ix_op_plans_kitchen_status", table_name="operational_plan_assignments")
    op.drop_table("operational_plan_assignments")

    op.drop_index("ix_incident_images_incident", table_name="incident_images")
    op.drop_table("incident_images")

    op.drop_index("ix_incident_actions_incident", table_name="incident_actions")
    op.drop_table("incident_actions")

    op.drop_index("ix_incident_lots_scope", table_name="incident_affected_lots")
    op.drop_table("incident_affected_lots")

    op.drop_index("ix_incidents_kitchen_status", table_name="ingredient_incidents")
    op.drop_table("ingredient_incidents")
