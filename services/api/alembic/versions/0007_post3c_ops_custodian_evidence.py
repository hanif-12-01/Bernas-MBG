"""Post-Sprint 3C: Single stock custodian delegation, purchase evidence, goods receipts, and two-step incident disposal.

Revision ID: 0007_post3c_ops_custodian_evidence
Revises: 0006_sprint3b1_3c_ops_incidents
Create Date: 2026-11-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_post3c_ops_custodian_evidence"
down_revision = "0006_sprint3b1_3c_ops_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kitchen_stock_custodian_assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "custodian_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
        sa.Column("active_kitchen_key", sa.String(length=64), nullable=True, unique=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE','REVOKED','EXPIRED')",
            name="ck_custodian_status",
        ),
    )
    op.create_index(
        "ix_custodian_kitchen_status",
        "kitchen_stock_custodian_assignments",
        ["kitchen_id", "status"],
    )
    op.create_index(
        "ix_custodian_user_status",
        "kitchen_stock_custodian_assignments",
        ["custodian_user_id", "status"],
    )

    op.create_table(
        "purchase_documents",
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
            "linked_run_id",
            sa.String(length=36),
            sa.ForeignKey("optimization_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "linked_recovery_event_id",
            sa.String(length=36),
            sa.ForeignKey("recovery_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("supplier_name", sa.String(length=255), nullable=False),
        sa.Column("supplier_contact", sa.String(length=255), nullable=True),
        sa.Column("invoice_number", sa.String(length=128), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("total_amount_idr", sa.Float(), nullable=True),
        sa.Column(
            "evidence_status",
            sa.String(length=32),
            nullable=False,
            server_default="NO_EVIDENCE",
        ),
        sa.Column("document_storage_key", sa.String(length=255), nullable=True),
        sa.Column("document_mime_type", sa.String(length=64), nullable=True),
        sa.Column("document_sha256", sa.String(length=64), nullable=True),
        sa.Column("document_size_bytes", sa.Integer(), nullable=True),
        sa.Column("document_original_filename", sa.String(length=255), nullable=True),
        sa.Column("exif_stripped", sa.Boolean(), nullable=True),
        sa.Column(
            "recorded_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_status IN ('NO_EVIDENCE','RECEIPT_UPLOADED','GOODS_RECEIVED','VERIFIED_MATCH','DISCREPANCY_FLAGGED')",
            name="ck_purchase_doc_evidence_status",
        ),
    )
    op.create_index(
        "ix_purchase_docs_kitchen_date",
        "purchase_documents",
        ["kitchen_id", "purchase_date"],
    )
    op.create_index(
        "ix_purchase_docs_kitchen_status",
        "purchase_documents",
        ["kitchen_id", "evidence_status"],
    )

    op.create_table(
        "purchase_document_lines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "purchase_document_id",
            sa.String(length=36),
            sa.ForeignKey("purchase_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ingredient_code", sa.String(length=64), nullable=True),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("quantity_raw_g", sa.Float(), nullable=False),
        sa.Column("unit_label", sa.String(length=32), nullable=False, server_default="kg"),
        sa.Column("unit_price_idr", sa.Float(), nullable=True),
        sa.Column("line_total_idr", sa.Float(), nullable=True),
        sa.Column("lot_code_hint", sa.String(length=128), nullable=True),
        sa.Column("expiry_date_hint", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity_raw_g > 0", name="ck_purchase_line_qty_positive"),
    )
    op.create_index(
        "ix_purchase_lines_doc",
        "purchase_document_lines",
        ["purchase_document_id"],
    )

    op.create_table(
        "goods_receipt_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_document_id",
            sa.String(length=36),
            sa.ForeignKey("purchase_documents.id", ondelete="SET NULL"),
            nullable=True,
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
            sa.ForeignKey("ingredients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ingredient_code", sa.String(length=64), nullable=False),
        sa.Column(
            "lot_id",
            sa.String(length=36),
            sa.ForeignKey("inventory_lots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("lot_code", sa.String(length=128), nullable=False),
        sa.Column("received_raw_g", sa.Float(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("condition_status", sa.String(length=32), nullable=False, server_default="GOOD"),
        sa.Column(
            "received_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("received_raw_g > 0", name="ck_goods_receipt_qty_positive"),
        sa.CheckConstraint(
            "condition_status IN ('GOOD','DAMAGED','QUARANTINED','REJECTED')",
            name="ck_goods_receipt_condition",
        ),
    )
    op.create_index(
        "ix_goods_receipts_kitchen_date",
        "goods_receipt_records",
        ["kitchen_id", "received_at"],
    )
    op.create_index(
        "ix_goods_receipts_purchase_doc",
        "goods_receipt_records",
        ["purchase_document_id"],
    )

    with op.batch_alter_table("inventory_lots") as batch_op:
        batch_op.add_column(sa.Column("supplier_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("purchase_document_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_inv_lots_purchase_doc",
            "purchase_documents",
            ["purchase_document_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("ingredient_incidents") as batch_op:
        batch_op.add_column(
            sa.Column("disposal_authorized", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("disposal_authorized_by_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("disposal_authorized_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("disposal_executed_by_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("disposal_executed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_incident_disposal_auth_user",
            "users",
            ["disposal_authorized_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_incident_disposal_exec_user",
            "users",
            ["disposal_executed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("ingredient_incidents") as batch_op:
        batch_op.drop_constraint("fk_incident_disposal_exec_user", type_="foreignkey")
        batch_op.drop_constraint("fk_incident_disposal_auth_user", type_="foreignkey")
        batch_op.drop_column("disposal_executed_at")
        batch_op.drop_column("disposal_executed_by_user_id")
        batch_op.drop_column("disposal_authorized_at")
        batch_op.drop_column("disposal_authorized_by_user_id")
        batch_op.drop_column("disposal_authorized")

    with op.batch_alter_table("inventory_lots") as batch_op:
        batch_op.drop_constraint("fk_inv_lots_purchase_doc", type_="foreignkey")
        batch_op.drop_column("purchase_document_id")
        batch_op.drop_column("supplier_name")

    op.drop_index("ix_goods_receipts_purchase_doc", table_name="goods_receipt_records")
    op.drop_index("ix_goods_receipts_kitchen_date", table_name="goods_receipt_records")
    op.drop_table("goods_receipt_records")

    op.drop_index("ix_purchase_lines_doc", table_name="purchase_document_lines")
    op.drop_table("purchase_document_lines")

    op.drop_index("ix_purchase_docs_kitchen_status", table_name="purchase_documents")
    op.drop_index("ix_purchase_docs_kitchen_date", table_name="purchase_documents")
    op.drop_table("purchase_documents")

    op.drop_index("ix_custodian_user_status", table_name="kitchen_stock_custodian_assignments")
    op.drop_index("ix_custodian_kitchen_status", table_name="kitchen_stock_custodian_assignments")
    op.drop_table("kitchen_stock_custodian_assignments")
