"""Sprint 3B: Adaptive procurement recovery events and review snapshot guard.

Revision ID: 0005_sprint3b_recovery
Revises: 0004_sprint3a6_inv_foundation
Create Date: 2026-11-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_sprint3b_recovery"
down_revision: Union[str, None] = "0004_sprint3a6_inv_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recovery_events",
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
            "baseline_menu_review_id",
            sa.String(length=36),
            sa.ForeignKey("menu_review_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "baseline_run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "baseline_scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("disruption_types_json", sa.JSON(), nullable=False),
        sa.Column("disruption_summary", sa.Text(), nullable=False),
        sa.Column("disruption_input_json", sa.JSON(), nullable=False),
        sa.Column("affected_slots_json", sa.JSON(), nullable=False),
        sa.Column("impact_analysis_json", sa.JSON(), nullable=False),
        sa.Column(
            "min_disruption_scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "min_disruption_run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "min_cost_scenario_id",
            sa.String(length=36),
            sa.ForeignKey("scenarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "min_cost_run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("selected_mode", sa.String(length=32), nullable=True),
        sa.Column(
            "selected_run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "submitted_review_id",
            sa.String(length=36),
            sa.ForeignKey("menu_review_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("inventory_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("comparison_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ANALYZED"),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ANALYZED','SUBMITTED','APPROVED','REVISION_REQUIRED','INFEASIBLE')",
            name="ck_recovery_event_status",
        ),
        sa.CheckConstraint(
            "selected_mode IS NULL OR selected_mode IN ('MIN_DISRUPTION','MIN_COST')",
            name="ck_recovery_selected_mode",
        ),
    )
    op.create_index(
        "ix_recovery_events_kitchen_created",
        "recovery_events",
        ["kitchen_id", "created_at"],
    )
    op.create_index(
        "ix_recovery_events_baseline_run",
        "recovery_events",
        ["baseline_run_id"],
    )

    with op.batch_alter_table("menu_review_records") as batch_op:
        batch_op.add_column(sa.Column("recovery_event_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("inventory_snapshot_sha256", sa.String(length=64), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_menu_reviews_recovery_event",
            "recovery_events",
            ["recovery_event_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("menu_review_records") as batch_op:
        batch_op.drop_constraint("fk_menu_reviews_recovery_event", type_="foreignkey")
        batch_op.drop_column("inventory_snapshot_sha256")
        batch_op.drop_column("recovery_event_id")

    op.drop_index("ix_recovery_events_baseline_run", table_name="recovery_events")
    op.drop_index("ix_recovery_events_kitchen_created", table_name="recovery_events")
    op.drop_table("recovery_events")
