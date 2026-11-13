"""incidencias de las automatizaciones (ADR-020, fase L4)

Escrita a mano a partir de los modelos y revisada:
- ``operations_db.automation_incidents``: fallo de un flujo de n8n que avisa el flujo de
  errores común, con la ejecución de PLATIA a la que corresponde si la hay.
Solo se añade, así que la vuelta atrás es segura (ADR-016).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-13 15:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0013'
down_revision = '0012'
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
    op.create_table('automation_incidents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.String(length=64), nullable=False),
        sa.Column('workflow_name', sa.String(length=255), nullable=True),
        sa.Column('execution_id', sa.String(length=64), nullable=True),
        sa.Column('mode', sa.String(length=20), nullable=True),
        sa.Column('node', sa.String(length=255), nullable=True),
        sa.Column('message', sa.String(length=500), nullable=True),
        sa.Column('run_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolution_note', sa.String(length=1000), nullable=True),
        sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['automation_runs.id'], name='fk_automation_incidents_run_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'execution_id', name='uq_automation_incidents_execution'),
    )
    with op.batch_alter_table('automation_incidents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_automation_incidents_workflow_id'), ['workflow_id'], unique=False)
        batch_op.create_index('ix_automation_incidents_status_created', ['status', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_incidents_is_active'), ['is_active'], unique=False)


def downgrade_operations():
    op.drop_table('automation_incidents')


def upgrade_analytics():
    pass


def downgrade_analytics():
    pass
