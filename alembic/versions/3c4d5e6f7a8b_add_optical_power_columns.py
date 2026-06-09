"""add optical power columns to telemetry_events

Revision ID: 3c4d5e6f7a8b
Revises: 8f4c2a1b9e3d
Create Date: 2026-06-09

Agrega rx_power_dbm, tx_power_dbm, optical_status a telemetry_events.
Datos provenientes del CLI oculto del firmware GPON: laser power --rxread / --txread
"""
from alembic import op
import sqlalchemy as sa

revision = '3c4d5e6f7a8b'
down_revision = '8f4c2a1b9e3d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('telemetry_events', sa.Column('rx_power_dbm', sa.Float(), nullable=True))
    op.add_column('telemetry_events', sa.Column('tx_power_dbm', sa.Float(), nullable=True))
    op.add_column('telemetry_events', sa.Column('optical_status', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('telemetry_events', 'optical_status')
    op.drop_column('telemetry_events', 'tx_power_dbm')
    op.drop_column('telemetry_events', 'rx_power_dbm')
