"""device.vendor — access-driver selector (multi-vendor abstraction P1)

Revision ID: a7c8d9e0f1a2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-16 00:00:00.000000

Adds ``devices.vendor`` — picks the AccessDriver (dahua/leelen/...) the bridge
uses for open / enroll / event-stream. NULL falls back to the generic HTTP-unlock
driver (today's behaviour). Backfills existing Dahua-integrated rows (ANPR cameras
+ barriers, or an unlock_url hitting a Dahua ``/cgi-bin/`` path) to 'dahua' so the
upcoming dispatch routes them correctly; everything else stays NULL (generic).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c8d9e0f1a2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("vendor", sa.String(length=32), nullable=True))
    op.create_index("ix_devices_vendor", "devices", ["vendor"])
    # Backfill: anything we drive via Dahua CGI today is 'dahua'.
    op.execute(
        "UPDATE devices SET vendor = 'dahua' "
        "WHERE anpr_enabled = true OR unlock_url LIKE '%/cgi-bin/%'"
    )


def downgrade() -> None:
    op.drop_index("ix_devices_vendor", table_name="devices")
    op.drop_column("devices", "vendor")
