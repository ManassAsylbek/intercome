"""plate whitelist for parking ANPR

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-21 00:00:00.000000

Adds the ``plate_whitelist`` table — the registry of car licence plates
allowed to open the parking barrier. Phase 1 of the parking/ANPR module.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plate_whitelist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plate", sa.String(length=16), nullable=False),
        sa.Column("owner_name", sa.String(length=128), nullable=True),
        sa.Column("apartment_id", sa.Integer(), nullable=True),
        sa.Column("entrance_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["apartment_id"], ["apartments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["entrance_id"], ["entrances.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plate_whitelist_id", "plate_whitelist", ["id"])
    op.create_index(
        "ix_plate_whitelist_plate", "plate_whitelist", ["plate"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_plate_whitelist_plate", table_name="plate_whitelist")
    op.drop_index("ix_plate_whitelist_id", table_name="plate_whitelist")
    op.drop_table("plate_whitelist")
