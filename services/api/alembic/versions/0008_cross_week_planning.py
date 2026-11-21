"""Cross-week menu planning: explicit service dates, per-date overlap prevention, and week continuation lineage.

Revision ID: 0008_cross_week_planning
Revises: 0007_post3c_ops_custodian_evidence
Create Date: 2026-11-22
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0008_cross_week_planning"
down_revision = "0007_post3c_ops_custodian_evidence"
branch_labels = None
depends_on = None


def _default_weekdays(start: date, count: int) -> list[date]:
    out: list[date] = []
    curr = start
    while len(out) < max(1, count):
        if curr.weekday() < 5 or count > 5:
            out.append(curr)
        curr += timedelta(days=1)
    return out


def upgrade() -> None:
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.add_column(sa.Column("service_dates_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("continuation_of_run_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_scenarios_continuation_run",
            "optimization_runs",
            ["continuation_of_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("operational_plan_assignments") as batch_op:
        batch_op.add_column(sa.Column("service_dates_json", sa.JSON(), nullable=True))

    op.create_table(
        "operational_plan_service_dates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.String(length=36),
            sa.ForeignKey("operational_plan_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(length=64), nullable=False),
        sa.Column("target_cohort", sa.String(length=128), nullable=False),
        sa.Column("batch_label", sa.String(length=64), nullable=False),
        sa.Column("active_date_scope_key", sa.String(length=255), nullable=True, unique=True),
        sa.CheckConstraint("day_index BETWEEN 1 AND 14", name="ck_op_service_date_day_idx"),
        sa.UniqueConstraint("assignment_id", "service_date", name="uq_op_service_dates_assign_date"),
        sa.UniqueConstraint("assignment_id", "day_index", name="uq_op_service_dates_assign_day"),
    )
    op.create_index(
        "ix_op_service_dates_kitchen_date",
        "operational_plan_service_dates",
        ["kitchen_id", "service_date"],
    )
    op.create_index(
        "ix_op_service_dates_assignment",
        "operational_plan_service_dates",
        ["assignment_id"],
    )

    # Backfill existing operational_plan_assignments into operational_plan_service_dates
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, kitchen_id, production_date, horizon_days, meal_type, target_cohort, batch_label, operational_status "
            "FROM operational_plan_assignments"
        )
    ).fetchall()
    used_active_keys: set[str] = set()
    for row in rows:
        assign_id, kitchen_id, prod_raw, horizon_days, meal_type, cohort, batch_label, op_status = row
        if isinstance(prod_raw, str):
            start_d = date.fromisoformat(prod_raw[:10])
        elif isinstance(prod_raw, date):
            start_d = prod_raw
        else:
            continue
        dates = _default_weekdays(start_d, int(horizon_days or 5))
        iso_dates = [d.isoformat() for d in dates]
        conn.execute(
            sa.text(
                "UPDATE operational_plan_assignments SET service_dates_json = :sjson WHERE id = :aid"
            ),
            {"sjson": json.dumps(iso_dates), "aid": assign_id},
        )
        is_effective = op_status in ("ACTIVE", "ON_HOLD")
        for idx, svc_d in enumerate(dates, start=1):
            key = f"{kitchen_id}|{svc_d.isoformat()}|{meal_type}|{cohort}|{batch_label}"
            if is_effective and key not in used_active_keys:
                active_key = key
                used_active_keys.add(key)
            else:
                active_key = None
            conn.execute(
                sa.text(
                    "INSERT INTO operational_plan_service_dates "
                    "(id, assignment_id, kitchen_id, service_date, day_index, meal_type, target_cohort, batch_label, active_date_scope_key) "
                    "VALUES (:id, :aid, :kid, :sdate, :didx, :mtype, :cohort, :blabel, :akey)"
                ),
                {
                    "id": str(uuid4()),
                    "aid": assign_id,
                    "kid": kitchen_id,
                    "sdate": svc_d.isoformat(),
                    "didx": idx,
                    "mtype": meal_type,
                    "cohort": cohort,
                    "blabel": batch_label,
                    "akey": active_key,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_op_service_dates_assignment", table_name="operational_plan_service_dates")
    op.drop_index("ix_op_service_dates_kitchen_date", table_name="operational_plan_service_dates")
    op.drop_table("operational_plan_service_dates")

    with op.batch_alter_table("operational_plan_assignments") as batch_op:
        batch_op.drop_column("service_dates_json")

    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_constraint("fk_scenarios_continuation_run", type_="foreignkey")
        batch_op.drop_column("continuation_of_run_id")
        batch_op.drop_column("service_dates_json")
