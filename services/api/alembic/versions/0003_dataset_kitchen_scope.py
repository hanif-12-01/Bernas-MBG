"""Assign private dataset versions to the kitchen that imported them."""

import sqlalchemy as sa
from alembic import op

revision = "0003_dataset_kitchen_scope"
down_revision = "0002_sprint3a_rbac_and_qc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().dialect.name == "sqlite":
        # SQLite supports adding a nullable reference inline without recreating the parent table.
        op.execute(
            "ALTER TABLE dataset_versions ADD COLUMN kitchen_id VARCHAR(36) "
            "CONSTRAINT fk_datasets_kitchen_id REFERENCES kitchens (id)"
        )
    else:
        op.add_column(
            "dataset_versions",
            sa.Column(
                "kitchen_id",
                sa.String(36),
                sa.ForeignKey("kitchens.id", name="fk_datasets_kitchen_id"),
                nullable=True,
            ),
        )
    op.create_index("ix_dataset_versions_kitchen_id", "dataset_versions", ["kitchen_id"])
    op.execute(
        """
        UPDATE dataset_versions
        SET kitchen_id = (
            SELECT MIN(event.kitchen_id)
            FROM audit_events AS event
            JOIN kitchens AS kitchen ON kitchen.id = event.kitchen_id
            WHERE event.action = 'dataset.imported'
              AND event.entity_type = 'dataset'
              AND event.entity_id = dataset_versions.id
            HAVING COUNT(DISTINCT event.kitchen_id) = 1
        )
        WHERE id <> '11111111-1111-1111-1111-111111111111'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_versions_kitchen_id", table_name="dataset_versions")
    if op.get_context().dialect.name != "sqlite":
        op.drop_constraint("fk_datasets_kitchen_id", "dataset_versions", type_="foreignkey")
    op.drop_column("dataset_versions", "kitchen_id")
