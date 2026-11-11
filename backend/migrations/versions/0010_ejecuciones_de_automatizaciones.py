"""ejecuciones del portal Low-Code (ADR-020, fase L2)

Escrita a mano a partir del modelo y revisada: ``operations_db.automation_runs`` guarda
cada flujo de n8n lanzado desde PLATIA, con su estado y el resultado que devuelve n8n.
Solo se añade una tabla, así que la vuelta atrás es segura (ADR-016).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010'
down_revision = '0009'
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
    op.create_table('automation_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.String(length=64), nullable=False),
        sa.Column('workflow_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('input_data', sa.JSON(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('automation_runs', schema=None) as batch_op:
        batch_op.create_index('ix_automation_runs_creator_created', ['created_by', 'created_at'], unique=False)
        batch_op.create_index('ix_automation_runs_status', ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_runs_workflow_id'), ['workflow_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_runs_is_active'), ['is_active'], unique=False)


def downgrade_operations():
    op.drop_table('automation_runs')


def upgrade_analytics():
    pass


def downgrade_analytics():
    pass
