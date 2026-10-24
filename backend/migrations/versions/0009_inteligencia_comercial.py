"""inteligencia comercial: mapa de oportunidad, competidores y objetivos (fase 9a)

Escrita a mano a partir de los modelos y revisada:
- analytics_db: ``heatmap_config`` (pesos), ``heatmap_scores`` (puntuación por mes,
  sector y línea), ``competitor_profiles`` (DAFO) y ``business_targets`` (objetivos).
- platform_core: el rol de serie «analyst» de la app analytics recibe el módulo de IA
  ``analytics_assistant``, una sola vez (si un administrador lo quita después, no
  vuelve). En una instalación nueva lo pone ``flask seed``.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24 19:30:00

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

AI_MODULE = "analytics_assistant"


def upgrade(engine_name):
    globals()["upgrade_%s" % engine_name]()


def downgrade(engine_name):
    globals()["downgrade_%s" % engine_name]()


def _analyst_role(conn):
    return conn.execute(sa.text(
        "SELECT r.id, r.permissions FROM app_roles r JOIN apps a ON a.id = r.app_id "
        "WHERE a.code = 'analytics' AND r.code = 'analyst'")).first()


def _save(conn, role_id, permissions):
    conn.execute(sa.text("UPDATE app_roles SET permissions = :p WHERE id = :id"),
                 {"p": json.dumps(permissions), "id": role_id})


def upgrade_core():
    conn = op.get_bind()
    row = _analyst_role(conn)
    if row is None:
        return
    permissions = row.permissions if isinstance(row.permissions, dict) else json.loads(row.permissions or "{}")
    modules = list(permissions.get("ai_modules_access") or [])
    if AI_MODULE not in modules:
        permissions["ai_modules_access"] = modules + [AI_MODULE]
        _save(conn, row.id, permissions)


def downgrade_core():
    conn = op.get_bind()
    row = _analyst_role(conn)
    if row is None:
        return
    permissions = row.permissions if isinstance(row.permissions, dict) else json.loads(row.permissions or "{}")
    modules = list(permissions.get("ai_modules_access") or [])
    if AI_MODULE in modules:
        permissions["ai_modules_access"] = [m for m in modules if m != AI_MODULE]
        _save(conn, row.id, permissions)


def upgrade_operations():
    pass


def downgrade_operations():
    pass


def _audit_columns():
    return [
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    ]


def _business_columns():
    return _audit_columns() + [
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    ]


def upgrade_analytics():
    op.create_table('heatmap_config',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('weight_demand', sa.Integer(), nullable=False),
    sa.Column('weight_traction', sa.Integer(), nullable=False),
    sa.Column('weight_economic', sa.Integer(), nullable=False),
    sa.Column('weight_right_to_win', sa.Integer(), nullable=False),
    sa.Column('lookback_months', sa.Integer(), nullable=False),
    *_audit_columns(),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_heatmap_config'))
    )
    op.create_table('heatmap_scores',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('sector', sa.String(length=100), nullable=False),
    sa.Column('service_line', sa.String(length=50), nullable=False),
    sa.Column('total_score', sa.Float(), nullable=False),
    sa.Column('score_demand', sa.Float(), nullable=False),
    sa.Column('score_traction', sa.Float(), nullable=False),
    sa.Column('score_economic', sa.Float(), nullable=False),
    sa.Column('score_right_to_win', sa.Float(), nullable=False),
    sa.Column('opportunities_count', sa.Integer(), nullable=False),
    sa.Column('recent_count', sa.Integer(), nullable=False),
    sa.Column('prior_count', sa.Integer(), nullable=False),
    sa.Column('won_count', sa.Integer(), nullable=False),
    sa.Column('lost_count', sa.Integer(), nullable=False),
    sa.Column('avg_value_eur', sa.Numeric(precision=16, scale=2), nullable=True),
    sa.Column('pipeline_eur', sa.Numeric(precision=16, scale=2), nullable=False),
    sa.Column('weights', sa.JSON(), nullable=False),
    sa.Column('calculated_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_heatmap_scores')),
    sa.UniqueConstraint('period', 'sector', 'service_line', name='uq_heatmap_cell')
    )
    with op.batch_alter_table('heatmap_scores', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_heatmap_scores_period'), ['period'], unique=False)

    op.create_table('competitor_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('competitor_type', sa.String(length=20), nullable=False),
    sa.Column('website', sa.String(length=255), nullable=True),
    sa.Column('description', sa.String(length=2000), nullable=True),
    sa.Column('strengths', sa.JSON(), nullable=False),
    sa.Column('weaknesses', sa.JSON(), nullable=False),
    sa.Column('opportunities', sa.JSON(), nullable=False),
    sa.Column('threats', sa.JSON(), nullable=False),
    sa.Column('service_lines', sa.JSON(), nullable=False),
    sa.Column('sectors', sa.JSON(), nullable=False),
    sa.Column('price_positioning', sa.Integer(), nullable=False),
    *_business_columns(),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_competitor_profiles')),
    sa.UniqueConstraint('name', name=op.f('uq_competitor_profiles_name'))
    )
    with op.batch_alter_table('competitor_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_competitor_profiles_is_active'), ['is_active'], unique=False)

    op.create_table('business_targets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.String(length=30), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('service_line', sa.String(length=50), nullable=False),
    sa.Column('target_value', sa.Numeric(precision=16, scale=2), nullable=False),
    *_business_columns(),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_targets')),
    sa.UniqueConstraint('metric', 'period', 'service_line', name='uq_target_metric_period_line')
    )
    with op.batch_alter_table('business_targets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_business_targets_is_active'), ['is_active'], unique=False)


def downgrade_analytics():
    op.drop_table('business_targets')
    op.drop_table('competitor_profiles')
    op.drop_table('heatmap_scores')
    op.drop_table('heatmap_config')
