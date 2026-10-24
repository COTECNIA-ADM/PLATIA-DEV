"""núcleo de IA (fase 5a): gobernanza de LLM, RAG, análisis GO/NO-GO y ROI

Generada con ``flask db migrate`` y revisada a mano:
- Columnas nuevas con valor por defecto en servidor (index_status, generation_status,
  is_fallback) para las filas existentes.
- Sin índice explícito en llm_quality_scores.usage_log_id: la clave foránea ya
  tiene el suyo en MySQL y borrarlo en el downgrade daría el error 1553.
- En el downgrade no se borran índices antes de su tabla.
- Los prompts, presupuestos y tiempos de referencia los crea ``flask seed``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24 08:03:11.242005

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade(engine_name):
    globals()["upgrade_%s" % engine_name]()


def downgrade(engine_name):
    globals()["downgrade_%s" % engine_name]()


def upgrade_core():
    op.create_table('budget_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('scope_id', sa.String(length=64), nullable=False),
    sa.Column('daily_limit_usd', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('monthly_limit_usd', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('alert_threshold_pct', sa.Integer(), nullable=False),
    sa.Column('throttle_threshold_pct', sa.Integer(), nullable=False),
    sa.Column('block_threshold_pct', sa.Integer(), nullable=False),
    sa.Column('throttle_delay_seconds', sa.Float(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budget_configs')),
    sa.UniqueConstraint('scope', 'scope_id', name='uq_budget_scope')
    )
    with op.batch_alter_table('llm_model_pricing', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cache_read_usd_per_mtok', sa.Numeric(precision=10, scale=4), nullable=True))
        batch_op.add_column(sa.Column('cache_write_usd_per_mtok', sa.Numeric(precision=10, scale=4), nullable=True))

    with op.batch_alter_table('llm_quality_scores', schema=None) as batch_op:
        batch_op.add_column(sa.Column('service_type', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('completeness_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('faithfulness_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('composite_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('user_rating', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_llm_quality_scores_service_type'), ['service_type'], unique=False)

    with op.batch_alter_table('llm_service_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('effort', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('prompt_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('description', sa.String(length=255), nullable=True))

    with op.batch_alter_table('llm_usage_log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stop_reason', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('is_fallback', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('correlation_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('output_sample', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('contained_pii', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('pii_types', sa.JSON(), nullable=True))
        batch_op.create_index('ix_llm_usage_correlation', ['correlation_id'], unique=False)

    with op.batch_alter_table('prompts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('archived_at', sa.DateTime(), nullable=True))



def downgrade_core():
    with op.batch_alter_table('prompts', schema=None) as batch_op:
        batch_op.drop_column('archived_at')
        batch_op.drop_column('notes')
        batch_op.drop_column('content_hash')

    with op.batch_alter_table('llm_usage_log', schema=None) as batch_op:
        batch_op.drop_index('ix_llm_usage_correlation')
        batch_op.drop_column('pii_types')
        batch_op.drop_column('contained_pii')
        batch_op.drop_column('output_sample')
        batch_op.drop_column('correlation_id')
        batch_op.drop_column('is_fallback')
        batch_op.drop_column('stop_reason')

    with op.batch_alter_table('llm_service_config', schema=None) as batch_op:
        batch_op.drop_column('description')
        batch_op.drop_column('prompt_name')
        batch_op.drop_column('effort')

    with op.batch_alter_table('llm_quality_scores', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_quality_scores_service_type'))
        batch_op.drop_column('user_rating')
        batch_op.drop_column('composite_score')
        batch_op.drop_column('faithfulness_score')
        batch_op.drop_column('completeness_score')
        batch_op.drop_column('service_type')

    with op.batch_alter_table('llm_model_pricing', schema=None) as batch_op:
        batch_op.drop_column('cache_write_usd_per_mtok')
        batch_op.drop_column('cache_read_usd_per_mtok')

    op.drop_table('budget_configs')


def upgrade_operations():
    op.create_table('ai_analyses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_type', sa.String(length=20), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('verdict', sa.String(length=12), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('model_name', sa.String(length=100), nullable=True),
    sa.Column('prompt_version', sa.Integer(), nullable=True),
    sa.Column('llm_usage_log_id', sa.BigInteger(), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=True),
    sa.Column('truncated', sa.Boolean(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_analyses'))
    )
    with op.batch_alter_table('ai_analyses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_analyses_is_active'), ['is_active'], unique=False)
        batch_op.create_index('ix_ai_analyses_subject', ['subject_type', 'subject_id', 'created_at'], unique=False)

    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_enriched_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('allowed_roles', sa.JSON(none_as_null=True), nullable=True))
        batch_op.add_column(sa.Column('index_status', sa.String(length=10), server_default='none', nullable=False))
        batch_op.add_column(sa.Column('vector_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('embedding_model', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('indexed_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('generation_status', sa.String(length=10), server_default='idle', nullable=False))
        batch_op.add_column(sa.Column('generation_error', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('generated_at', sa.DateTime(), nullable=True))



def downgrade_operations():
    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.drop_column('generated_at')
        batch_op.drop_column('generation_error')
        batch_op.drop_column('generation_status')

    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('indexed_at')
        batch_op.drop_column('embedding_model')
        batch_op.drop_column('vector_count')
        batch_op.drop_column('index_status')
        batch_op.drop_column('allowed_roles')
        batch_op.drop_column('ai_enriched_at')

    op.drop_table('ai_analyses')


def upgrade_analytics():
    op.create_table('human_baseline_config',
    sa.Column('service_type', sa.String(length=50), nullable=False),
    sa.Column('task_name', sa.String(length=128), nullable=False),
    sa.Column('human_time_minutes', sa.Float(), nullable=False),
    sa.Column('human_hourly_cost_eur', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('service_type', name=op.f('pk_human_baseline_config'))
    )
    op.create_table('task_completion_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('service_type', sa.String(length=50), nullable=False),
    sa.Column('subject_type', sa.String(length=30), nullable=True),
    sa.Column('subject_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=True),
    sa.Column('ai_duration_seconds', sa.Float(), nullable=True),
    sa.Column('llm_cost_usd', sa.Numeric(precision=12, scale=6), nullable=True),
    sa.Column('human_time_baseline_minutes', sa.Float(), nullable=True),
    sa.Column('time_saved_minutes', sa.Float(), nullable=True),
    sa.Column('money_saved_eur', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('quality_score', sa.Float(), nullable=True),
    sa.Column('user_rating', sa.Integer(), nullable=True),
    sa.Column('was_accepted', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_completion_log'))
    )
    with op.batch_alter_table('task_completion_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_task_completion_log_user_id'), ['user_id'], unique=False)
        batch_op.create_index('ix_task_completion_service_created', ['service_type', 'created_at'], unique=False)



def downgrade_analytics():
    op.drop_table('task_completion_log')
    op.drop_table('human_baseline_config')

