"""apartment cloud relay and device apartment_id

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add cloud relay fields to apartments
    with op.batch_alter_table('apartments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cloud_relay_enabled', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('cloud_sip_account', sa.String(length=128), nullable=True))

    # Add apartment_id FK to devices (source device → apartment it calls)
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('apartment_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_devices_apartment_id', 'apartments', ['apartment_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_constraint('fk_devices_apartment_id', type_='foreignkey')
        batch_op.drop_column('apartment_id')

    with op.batch_alter_table('apartments', schema=None) as batch_op:
        batch_op.drop_column('cloud_sip_account')
        batch_op.drop_column('cloud_relay_enabled')
