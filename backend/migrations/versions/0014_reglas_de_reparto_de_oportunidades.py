"""reglas de reparto de oportunidades (ADR-020, caso P18)

Escrita a mano a partir de los modelos y revisada:
- ``operations_db.opportunity_routing_rules``: a quién se asigna una oportunidad que llega sin
  responsable (feeds, TED, buzón de pliegos), según fuente, línea, sector, importe y plazo.
Solo se añade, así que la vuelta atrás es segura (ADR-016).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13 21:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade(engine_name):
    globals()["upgrade_%s" % engine_name]()


def downgrade(engine_name):
    globals()["downgrade_%s" % engine_name]()


def upgrade_core():
    pass


def downgrade_core():
    pass


def upgrade_operations():
    op.create_table('opportunity_routing_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=True),
        sa.Column('service_lines', sa.JSON(), nullable=True),
        sa.Column('sectors', sa.JSON(), nullable=True),
        sa.Column('min_value_eur', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('max_value_eur', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('max_days_to_deadline', sa.Integer(), nullable=True),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade_operations():
    op.drop_table('opportunity_routing_rules')


def upgrade_analytics():
    pass


def downgrade_analytics():
    pass
