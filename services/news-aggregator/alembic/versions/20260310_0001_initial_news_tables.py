"""initial news tables

Revision ID: 20260310_0001
Revises:
Create Date: 2026-03-10 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260310_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fetch_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("triggered_by", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("sources_used", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("keywords_used", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("total_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("after_dedup", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("after_enrich", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_fetch_jobs_status", "fetch_jobs", ["status", "started_at"], unique=False)

    op.create_table(
        "source_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("freshness", sa.String(length=20), nullable=False, server_default="oneDay"),
        sa.Column("max_results", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("extra_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=True),
        sa.Column("raw_snippet", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("ai_relevance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("is_starred", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="zh"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kb_doc_id", sa.String(length=100), nullable=True),
        sa.Column("fetch_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["fetch_job_id"], ["fetch_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_articles_url"),
    )
    op.create_index("idx_articles_status_fetched", "articles", ["status", "fetched_at"], unique=False)
    op.create_index("idx_articles_tags", "articles", ["ai_tags"], unique=False, postgresql_using="gin")
    op.create_index(
        "idx_articles_archived",
        "articles",
        ["archived_at"],
        unique=False,
        postgresql_where=sa.text("status = 'archived'"),
    )

    op.execute(
        """
        INSERT INTO source_configs (id, source_type, display_name, is_enabled, keywords, freshness, max_results, extra_params)
        VALUES
        ('00000000-0000-0000-0000-000000000501', 'serper', 'Serper', true, '["AI news today","LLM large language model","artificial intelligence breakthrough"]', 'oneDay', 10, '{}'),
        ('00000000-0000-0000-0000-000000000502', 'bocha', 'Bocha', true, '["AI 人工智能 最新","大模型 发布","AGI 智能体 Agent"]', 'oneDay', 10, '{}'),
        ('00000000-0000-0000-0000-000000000503', 'tianapi', 'Tianapi', true, '[]', 'oneDay', 10, '{}');
        """
    )


def downgrade() -> None:
    op.drop_index("idx_articles_archived", table_name="articles")
    op.drop_index("idx_articles_tags", table_name="articles")
    op.drop_index("idx_articles_status_fetched", table_name="articles")
    op.drop_table("articles")
    op.drop_table("source_configs")
    op.drop_index("idx_fetch_jobs_status", table_name="fetch_jobs")
    op.drop_table("fetch_jobs")
