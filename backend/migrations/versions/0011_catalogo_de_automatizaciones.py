"""catálogo propio del portal Low-Code (ADR-020, fase L3)

Escrita a mano a partir de los modelos y revisada:
- ``operations_db.automation_entries``: ficha de cada automatización (título, descripción,
  campos del formulario) con su revisión y publicación.
- ``automation_runs.entry_id``: la ficha desde la que se lanzó. Nula en las ejecuciones de
  la fase L2, que se lanzaban directamente con el id del flujo.
Solo se añade, así que la vuelta atrás es segura (ADR-016).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-11 14:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011'
down_revision = '0010'
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
    op.create_table('automation_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('fields', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('checks', sa.JSON(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_by', sa.Integer(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.String(length=1000), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('automation_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_automation_entries_workflow_id'), ['workflow_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_entries_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_entries_is_active'), ['is_active'], unique=False)
    with op.batch_alter_table('automation_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entry_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_automation_runs_entry_id'), ['entry_id'], unique=False)
        batch_op.create_foreign_key('fk_automation_runs_entry_id', 'automation_entries', ['entry_id'], ['id'])


def downgrade_operations():
    with op.batch_alter_table('automation_runs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_automation_runs_entry_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_automation_runs_entry_id'))
        batch_op.drop_column('entry_id')
    op.drop_table('automation_entries')


def upgrade_analytics():
    pass


def downgrade_analytics():
    pass
