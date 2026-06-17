"""ANPR phase 2: devices.anpr_enabled + plate_access_log

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-21 00:00:00.000000

Phase 2 of the parking/ANPR module:
  • ``devices.anpr_enabled`` — flags a Dahua ITC ANPR camera that the
    anpr_service should subscribe to for plate-recognition events.
  • ``plate_access_log`` — журнал проездов, one row per recognition.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "anpr_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "plate_access_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("plate", sa.String(length=16), nullable=False),
        sa.Column("plate_raw", sa.String(length=32), nullable=True),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("whitelist_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["whitelist_id"], ["plate_whitelist.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plate_access_log_id", "plate_access_log", ["id"])
    op.create_index("ix_plate_access_log_plate", "plate_access_log", ["plate"])
    op.create_index(
        "ix_plate_access_log_created_at", "plate_access_log", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_plate_access_log_created_at", table_name="plate_access_log")
    op.drop_index("ix_plate_access_log_plate", table_name="plate_access_log")
    op.drop_index("ix_plate_access_log_id", table_name="plate_access_log")
    op.drop_table("plate_access_log")
    op.drop_column("devices", "anpr_enabled")
