"""Sprint 3A.6: Inventory data quality, lot availability, provenance, mapping, and market reference tables.

Revision ID: 0004_sprint3a6_inv_foundation
Revises: 0003_dataset_kitchen_scope
Create Date: 2026-11-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_sprint3a6_inv_foundation"
down_revision: Union[str, None] = "0003_dataset_kitchen_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_context().dialect.name == "sqlite":
        op.execute("ALTER TABLE scenarios ADD COLUMN production_date DATETIME")
    else:
        op.add_column(
            "scenarios",
            sa.Column("production_date", sa.DateTime(timezone=True), nullable=True),
        )

    op.create_table(
        "dataset_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license", sa.String(length=128), nullable=False),
        sa.Column("license_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dataset_type", sa.String(length=64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("allowed_use", sa.String(length=128), nullable=False),
        sa.Column("transformation_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dataset_sources_name", "dataset_sources", ["source_name"])

    op.create_table(
        "ingredient_mappings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "kitchen_id",
            sa.String(length=36),
            sa.ForeignKey("kitchens.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "dataset_version_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_product_code", sa.String(length=128), nullable=False),
        sa.Column("external_product_name", sa.String(length=255), nullable=False),
        sa.Column("external_unit", sa.String(length=32), nullable=False),
        sa.Column("canonical_category", sa.String(length=64), nullable=True),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ingredient_code", sa.String(length=64), nullable=True),
        sa.Column("standard_unit", sa.String(length=32), nullable=False, server_default="kg"),
        sa.Column("conversion_factor_to_g", sa.Float(), nullable=True),
        sa.Column("density_g_per_ml", sa.Float(), nullable=True),
        sa.Column("unit_weight_g", sa.Float(), nullable=True),
        sa.Column("mapping_status", sa.String(length=32), nullable=False, server_default="UNMAPPED"),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="needs_review"),
        sa.Column(
            "reviewer_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mapping_status IN ('MAPPED','UNMAPPED','AMBIGUOUS','REJECTED','UNIT_ERROR')",
            name="ck_ing_mapping_status",
        ),
    )
    op.create_index(
        "ix_ing_mappings_scope",
        "ingredient_mappings",
        ["kitchen_id", "dataset_version_id", "external_product_code"],
    )

    op.create_table(
        "inventory_lots",
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
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lot_code", sa.String(length=128), nullable=False),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("data_classification", sa.String(length=32), nullable=False, server_default="synthetic"),
        sa.Column("recorded_raw_g", sa.Float(), nullable=False),
        sa.Column("damaged_raw_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_known", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_physical_raw_g", sa.Float(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="VERIFIED"),
        sa.Column("unit_original", sa.String(length=32), nullable=False, server_default="g"),
        sa.Column("quantity_original", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kitchen_id", "dataset_version_id", "lot_code", name="uq_inv_lot_code"),
        sa.CheckConstraint("recorded_raw_g >= 0", name="ck_inv_lot_recorded_nonneg"),
        sa.CheckConstraint("damaged_raw_g >= 0", name="ck_inv_lot_damaged_nonneg"),
        sa.CheckConstraint(
            "verification_status IN ('VERIFIED','UNVERIFIED','UNKNOWN','DISCREPANCY','QUARANTINED')",
            name="ck_inv_lot_verif_status",
        ),
    )
    op.create_index("ix_inv_lots_scope", "inventory_lots", ["kitchen_id", "dataset_version_id", "ingredient_id"])

    op.create_table(
        "inventory_movements",
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
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
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
            sa.ForeignKey("inventory_lots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("movement_type", sa.String(length=40), nullable=False),
        sa.Column("quantity_delta_raw_g", sa.Float(), nullable=False),
        sa.Column("original_value", sa.Float(), nullable=False),
        sa.Column("original_unit", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("source_document_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kitchen_id", "dataset_version_id", "idempotency_key", name="uq_inv_mov_idemp"),
        sa.CheckConstraint(
            "movement_type IN ('OPENING_BALANCE','GOODS_RECEIPT','PRODUCTION_CONSUMPTION','RESERVATION','RESERVATION_RELEASE','ADJUSTMENT','DAMAGE','DISPOSAL','PHYSICAL_COUNT_RECONCILIATION')",
            name="ck_inv_mov_type",
        ),
    )
    op.create_index("ix_inv_mov_scope_time", "inventory_movements", ["kitchen_id", "dataset_version_id", "event_at"])

    op.create_table(
        "stock_reservations",
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
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
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
            sa.ForeignKey("inventory_lots.id", ondelete="SET NULL"),
            nullable=True,
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
            sa.ForeignKey("optimization_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reserved_raw_g", sa.Float(), nullable=False),
        sa.Column("production_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kitchen_id", "dataset_version_id", "idempotency_key", name="uq_stock_res_idemp"),
        sa.CheckConstraint("reserved_raw_g > 0", name="ck_stock_res_pos"),
        sa.CheckConstraint("status IN ('ACTIVE','RELEASED','CONSUMED')", name="ck_stock_res_status"),
    )
    op.create_index("ix_stock_res_scope", "stock_reservations", ["kitchen_id", "dataset_version_id", "ingredient_id"])

    op.create_table(
        "supplier_deliveries",
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
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingredient_id",
            sa.String(length=36),
            sa.ForeignKey("ingredients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("supplier_name", sa.String(length=255), nullable=False),
        sa.Column("delivery_ref", sa.String(length=128), nullable=False),
        sa.Column("expected_raw_g", sa.Float(), nullable=False),
        sa.Column("received_raw_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column("original_value", sa.Float(), nullable=False),
        sa.Column("original_unit", sa.String(length=32), nullable=False),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PROMISED"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kitchen_id", "dataset_version_id", "idempotency_key", name="uq_sup_deliv_idemp"),
        sa.CheckConstraint("expected_raw_g > 0", name="ck_sup_deliv_exp_pos"),
        sa.CheckConstraint("received_raw_g >= 0", name="ck_sup_deliv_rec_nonneg"),
        sa.CheckConstraint(
            "status IN ('PROMISED','DELAYED','PARTIAL','RECEIVED','CANCELLED')",
            name="ck_sup_deliv_status",
        ),
    )
    op.create_index("ix_sup_deliv_scope", "supplier_deliveries", ["kitchen_id", "dataset_version_id", "ingredient_id"])

    op.create_table(
        "inventory_reconciliations",
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
            sa.ForeignKey("dataset_versions.id", ondelete="CASCADE"),
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
            sa.ForeignKey("inventory_lots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recorded_raw_g", sa.Float(), nullable=False),
        sa.Column("physical_raw_g", sa.Float(), nullable=False),
        sa.Column("discrepancy_raw_g", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DISCREPANCY_DETECTED"),
        sa.Column("counted_by", sa.String(length=128), nullable=True),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("recorded_raw_g >= 0", name="ck_inv_rec_recorded_nonneg"),
        sa.CheckConstraint("physical_raw_g >= 0", name="ck_inv_rec_physical_nonneg"),
        sa.CheckConstraint(
            "status IN ('MATCHED','DISCREPANCY_DETECTED','RECONCILED')",
            name="ck_inv_rec_status",
        ),
    )
    op.create_index("ix_inv_recon_scope", "inventory_reconciliations", ["kitchen_id", "dataset_version_id", "ingredient_id"])

    op.create_table(
        "market_price_references",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(length=36),
            sa.ForeignKey("dataset_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("commodity_code", sa.String(length=64), nullable=False),
        sa.Column("commodity_name", sa.String(length=255), nullable=False),
        sa.Column("canonical_ingredient_code", sa.String(length=64), nullable=True),
        sa.Column("region", sa.String(length=128), nullable=False),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("price_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False, server_default="IDR/kg"),
        sa.Column("price_idr_per_g", sa.Float(), nullable=True),
        sa.Column(
            "price_provenance",
            sa.String(length=40),
            nullable=False,
            server_default="OFFICIAL_MARKET_REFERENCE",
        ),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(length=40), nullable=False, server_default="REFERENCE_ONLY"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("price_value > 0", name="ck_market_price_pos"),
        sa.CheckConstraint(
            "price_provenance IN ('OFFICIAL_MARKET_REFERENCE','ACTUAL_SUPPLIER','SYNTHETIC_EXAMPLE','UNKNOWN')",
            name="ck_market_provenance",
        ),
    )
    op.create_index(
        "ix_market_ref_commodity_date",
        "market_price_references",
        ["canonical_ingredient_code", "region", "observed_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_ref_commodity_date", table_name="market_price_references")
    op.drop_table("market_price_references")
    op.drop_index("ix_inv_recon_scope", table_name="inventory_reconciliations")
    op.drop_table("inventory_reconciliations")
    op.drop_index("ix_sup_deliv_scope", table_name="supplier_deliveries")
    op.drop_table("supplier_deliveries")
    op.drop_index("ix_stock_res_scope", table_name="stock_reservations")
    op.drop_table("stock_reservations")
    op.drop_index("ix_inv_mov_scope_time", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_index("ix_inv_lots_scope", table_name="inventory_lots")
    op.drop_table("inventory_lots")
    op.drop_index("ix_ing_mappings_scope", table_name="ingredient_mappings")
    op.drop_table("ingredient_mappings")
    op.drop_index("ix_dataset_sources_name", table_name="dataset_sources")
    op.drop_table("dataset_sources")
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_column("production_date")
