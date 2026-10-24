"""historial de estados de las oportunidades y versión de los roles (fase 6b)

Escrita a mano a partir de ``flask db migrate`` y revisada:
- ``app_roles.row_version`` (bloqueo optimista al editar permisos desde Admin).
- Tabla de solo inserción ``opportunity_status_changes`` en operations_db.
- Relleno inicial: una fila por oportunidad con su estado actual. Para las cerradas
  (ganada, perdida, descartada) se toma ``updated_at`` como fecha de cierre, que es
  la mejor aproximación que hay; para el resto, ``created_at``. Estas filas llevan
  el comentario «Estado al crear el historial» para distinguirlas.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24 15:45:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

BACKFILL_NOTE = "Estado al crear el historial"


def upgrade(engine_name):
    globals()["upgrade_%s" % engine_name]()


def downgrade(engine_name):
    globals()["downgrade_%s" % engine_name]()


def upgrade_core():
    with op.batch_alter_table('app_roles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False))


def downgrade_core():
    with op.batch_alter_table('app_roles', schema=None) as batch_op:
        batch_op.drop_column('row_version')


def upgrade_operations():
    op.create_table('opportunity_status_changes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('opportunity_id', sa.Integer(), nullable=False),
    sa.Column('from_status', sa.String(length=30), nullable=True),
    sa.Column('to_status', sa.String(length=30), nullable=False),
    sa.Column('comment', sa.String(length=500), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id'],
                            name=op.f('fk_opportunity_status_changes_opportunity_id_opportunities')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_opportunity_status_changes'))
    )
    with op.batch_alter_table('opportunity_status_changes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_opportunity_status_changes_opportunity_id'), ['opportunity_id'],
                              unique=False)
        batch_op.create_index(batch_op.f('ix_opportunity_status_changes_is_active'), ['is_active'], unique=False)
        batch_op.create_index('ix_opportunity_status_changes_to_created', ['to_status', 'created_at'], unique=False)

    op.execute(sa.text(
        "INSERT INTO opportunity_status_changes "
        "(opportunity_id, from_status, to_status, comment, created_by, created_at, updated_at, is_active) "
        "SELECT id, NULL, status, :note, NULL, "
        "CASE WHEN status IN ('won', 'lost', 'discarded') THEN updated_at ELSE created_at END, "
        "updated_at, 1 FROM opportunities"
    ).bindparams(note=BACKFILL_NOTE))


def downgrade_operations():
    op.drop_table('opportunity_status_changes')


def upgrade_analytics():
    pass


def downgrade_analytics():
    pass
