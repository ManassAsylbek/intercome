"""cloud bi-directional mirror: entrances + cloud_id / mac_address / cloud_synced

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-12 00:00:00.000000

Adds the columns and table needed for bridge → cloud upsert of apartments and
devices, mirroring what cloud → bridge already does via create_apartment /
provision_webrtc_endpoint.

  • New ``entrances`` table — cached locally from cloud's bootstrap_snapshot.
  • ``apartments.entrance_id``, ``cloud_id``, ``floor``,
    ``cloud_synced``, ``last_cloud_sync_error``.
  • ``devices.mac_address``, ``model``, ``entrance_id``, ``cloud_id``,
    ``cloud_synced``, ``last_cloud_sync_error``.
  • ``apartment_monitors.mac_address``, ``model``, ``name``, ``cloud_id``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── entrances (cloud-defined, mirrored locally) ──────────────────────────
    op.create_table(
        "entrances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cloud_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=True),
        sa.Column("building_address", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cloud_id", name="uq_entrances_cloud_id"),
    )
    op.create_index("ix_entrances_cloud_id", "entrances", ["cloud_id"], unique=True)

    # ── apartments ───────────────────────────────────────────────────────────
    with op.batch_alter_table("apartments") as batch:
        batch.add_column(
            sa.Column("entrance_id", sa.Integer(), nullable=True)
        )
        batch.add_column(sa.Column("cloud_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("floor", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "cloud_synced",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch.add_column(
            sa.Column("last_cloud_sync_error", sa.Text(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_apartments_entrance_id",
            "entrances",
            ["entrance_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_apartments_cloud_id", ["cloud_id"])
    op.create_index(
        "ix_apartments_entrance_id", "apartments", ["entrance_id"]
    )

    # ── devices ──────────────────────────────────────────────────────────────
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("mac_address", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("model", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("entrance_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cloud_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "cloud_synced",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch.add_column(
            sa.Column("last_cloud_sync_error", sa.Text(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_devices_entrance_id",
            "entrances",
            ["entrance_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_devices_cloud_id", ["cloud_id"])
    op.create_index("ix_devices_mac_address", "devices", ["mac_address"])
    op.create_index("ix_devices_entrance_id", "devices", ["entrance_id"])

    # ── apartment_monitors ───────────────────────────────────────────────────
    with op.batch_alter_table("apartment_monitors") as batch:
        batch.add_column(sa.Column("mac_address", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("model", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("name", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("cloud_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_apartment_monitors_mac_address", "apartment_monitors", ["mac_address"]
    )


def downgrade() -> None:
    with op.batch_alter_table("apartment_monitors") as batch:
        batch.drop_index("ix_apartment_monitors_mac_address")
        batch.drop_column("cloud_id")
        batch.drop_column("name")
        batch.drop_column("model")
        batch.drop_column("mac_address")

    with op.batch_alter_table("devices") as batch:
        batch.drop_index("ix_devices_entrance_id")
        batch.drop_index("ix_devices_mac_address")
        batch.drop_constraint("uq_devices_cloud_id", type_="unique")
        batch.drop_constraint("fk_devices_entrance_id", type_="foreignkey")
        batch.drop_column("last_cloud_sync_error")
        batch.drop_column("cloud_synced")
        batch.drop_column("cloud_id")
        batch.drop_column("entrance_id")
        batch.drop_column("model")
        batch.drop_column("mac_address")

    with op.batch_alter_table("apartments") as batch:
        batch.drop_index("ix_apartments_entrance_id")
        batch.drop_constraint("uq_apartments_cloud_id", type_="unique")
        batch.drop_constraint("fk_apartments_entrance_id", type_="foreignkey")
        batch.drop_column("last_cloud_sync_error")
        batch.drop_column("cloud_synced")
        batch.drop_column("floor")
        batch.drop_column("cloud_id")
        batch.drop_column("entrance_id")

    op.drop_index("ix_entrances_cloud_id", table_name="entrances")
    op.drop_table("entrances")
