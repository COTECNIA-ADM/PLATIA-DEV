"""correo de los avisos de prioridad alta (fase 8)

Escrita a mano y revisada: ``notifications.emailed_at`` marca los avisos ya enviados
por correo, para que la tarea programada no los repita.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24 19:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
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
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('emailed_at', sa.DateTime(), nullable=True))


def downgrade_operations():
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_column('emailed_at')


def upgrade_analytics():
    pass


def downgrade_analytics():
    pass
