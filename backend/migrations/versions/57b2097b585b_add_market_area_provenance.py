"""add market area provenance

Revision ID: 57b2097b585b
Revises: 9c6fdf6cba65
Create Date: 2026-09-19 20:22:13.696416
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '57b2097b585b'
down_revision: Union[str, None] = '9c6fdf6cba65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('market_area') as batch_op:
        batch_op.add_column(sa.Column('source_id', sa.String(length=32), nullable=False))
        batch_op.create_foreign_key(
            'fk_market_area_source_id_data_source',
            'data_source',
            ['source_id'],
            ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('market_area') as batch_op:
        batch_op.drop_constraint('fk_market_area_source_id_data_source', type_='foreignkey')
        batch_op.drop_column('source_id')
