"""screening pipeline: screen_candidates table + watchlist lifecycle columns

Revision ID: 002
Revises: 001
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    # -- New table: screen_candidates --
    op.create_table(
        "screen_candidates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), unique=True, nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("screen_score", sa.Numeric(5, 1), nullable=False),
        sa.Column("qual_score", sa.Numeric(5, 1), nullable=True),
        sa.Column("short_interest_pct", MONEY, nullable=False),
        sa.Column("market_cap", sa.BigInteger, nullable=True),
        sa.Column("avg_volume", sa.BigInteger, nullable=True),
        sa.Column("pe_ratio", MONEY, nullable=True),
        sa.Column("momentum_20d", MONEY, nullable=True),
        sa.Column("analyst_consensus", sa.String(20), nullable=True),
        sa.Column("insider_sentiment", MONEY, nullable=True),
        sa.Column("eps_revision_pct", MONEY, nullable=True),
        sa.Column("downgrade_count_90d", sa.Integer, nullable=True),
        sa.Column("price_target_gap_pct", MONEY, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="screened"),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_screen_candidates_status", "screen_candidates", ["status"])
    op.create_index("ix_screen_candidates_screen_score", "screen_candidates", ["screen_score"])

    # -- Watchlist lifecycle columns --
    op.add_column("watchlist", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("watchlist", sa.Column("removal_reason", sa.Text, nullable=True))
    op.add_column("watchlist", sa.Column("source", sa.String(50), nullable=True, server_default="manual"))
    op.add_column(
        "watchlist",
        sa.Column("screen_candidate_id", sa.Integer, sa.ForeignKey("screen_candidates.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("watchlist", "screen_candidate_id")
    op.drop_column("watchlist", "source")
    op.drop_column("watchlist", "removal_reason")
    op.drop_column("watchlist", "removed_at")

    op.drop_index("ix_screen_candidates_screen_score", table_name="screen_candidates")
    op.drop_index("ix_screen_candidates_status", table_name="screen_candidates")
    op.drop_table("screen_candidates")
