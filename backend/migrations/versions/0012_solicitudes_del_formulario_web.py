"""solicitudes del formulario web (ADR-020, caso P2)

Escrita a mano a partir de los modelos y revisada:
- ``operations_db.inbound_leads``: solicitud que entrega n8n desde el formulario web, pendiente
  hasta que una persona la convierte en contacto u oportunidad, o la descarta.
Solo se añade, así que la vuelta atrás es segura (ADR-016). Los roles de serie reciben el
módulo ``leads`` con ``flask seed`` (LATER_MODULES), no aquí.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-13 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0012'
down_revision = '0011'
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
    op.create_table('inbound_leads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('external_ref', sa.String(length=100), nullable=True),
        sa.Column('workflow_id', sa.String(length=64), nullable=True),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('company', sa.String(length=255), nullable=True),
        sa.Column('tax_id', sa.String(length=32), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('ack_sent', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('resolution', sa.String(length=12), nullable=True),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('opportunity_id', sa.Integer(), nullable=True),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolution_note', sa.String(length=1000), nullable=True),
        sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], name='fk_inbound_leads_client_id'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name='fk_inbound_leads_contact_id'),
        sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id'], name='fk_inbound_leads_opportunity_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'external_ref', name='uq_inbound_leads_source_ref'),
    )
    with op.batch_alter_table('inbound_leads', schema=None) as batch_op:
        batch_op.create_index('ix_inbound_leads_status_created', ['status', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_inbound_leads_is_active'), ['is_active'], unique=False)


def downgrade_operations():
    op.drop_table('inbound_leads')


def upgrade_analytics():
    pass


def downgrade_analytics():
    pass
