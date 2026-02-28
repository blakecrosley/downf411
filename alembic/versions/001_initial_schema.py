"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 4)


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cash", MONEY, nullable=False, server_default="10000.0000"),
        sa.Column("highest_milestone_reached", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), unique=True, nullable=False),
        sa.Column("thesis_category", sa.String(100), nullable=False),
        sa.Column("thesis_text", sa.Text, nullable=False),
        sa.Column("short_interest_pct", MONEY, nullable=False),
        sa.Column("days_to_cover", MONEY, nullable=False),
        sa.Column("borrow_rate_annual", MONEY, nullable=False),
        sa.Column("prev_borrow_rate", MONEY, nullable=False),
        sa.Column("si_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("si_source", sa.String(50), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("portfolio_id", sa.Integer, sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("watchlist_id", sa.Integer, sa.ForeignKey("watchlist.id"), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("shares", sa.Integer, nullable=False),
        sa.Column("entry_price", MONEY, nullable=False),
        sa.Column("current_price", MONEY, nullable=False),
        sa.Column("stop_loss", MONEY, nullable=False),
        sa.Column("take_profit", MONEY, nullable=False),
        sa.Column("borrow_rate", MONEY, nullable=False),
        sa.Column("margin_deposited", MONEY, nullable=False),
        sa.Column("accrued_borrow_fees", MONEY, nullable=False, server_default="0.0000"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_price", MONEY, nullable=True),
        sa.Column("realized_pnl", MONEY, nullable=True),
    )
    op.create_index("ix_positions_portfolio_status", "positions", ["portfolio_id", "status"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("portfolio_id", sa.Integer, sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("position_id", sa.Integer, sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("side", sa.String(20), nullable=False),
        sa.Column("shares", sa.Integer, nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("position_id", sa.Integer, sa.ForeignKey("positions.id"), nullable=False),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("shares", sa.Integer, nullable=False),
        sa.Column("entry_price", MONEY, nullable=False),
        sa.Column("exit_price", MONEY, nullable=True),
        sa.Column("gross_pnl", MONEY, nullable=True),
        sa.Column("fees_total", MONEY, nullable=False, server_default="0.0000"),
        sa.Column("net_pnl", MONEY, nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("signal_type", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Integer, nullable=False),
        sa.Column("entry_price", MONEY, nullable=False),
        sa.Column("stop_loss", MONEY, nullable=False),
        sa.Column("target", MONEY, nullable=False),
        sa.Column("time_horizon_days", sa.Integer, nullable=False),
        sa.Column("reasoning", sa.JSON, nullable=False),
        sa.Column("catalyst", sa.Text, nullable=False),
        sa.Column("schema_version", sa.String(10), nullable=False),
        sa.Column("data_quality", sa.String(20), nullable=False),
        sa.Column("engine_source", sa.String(20), nullable=False, server_default="ensemble"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_signals_created_at", "signals", ["created_at"])

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("signal_id", sa.Integer, sa.ForeignKey("signals.id"), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("predicted_direction", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Integer, nullable=False),
        sa.Column("outcome_pnl", MONEY, nullable=True),
        sa.Column("outcome_correct", sa.Boolean, nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("engine_source", sa.String(20), nullable=False, server_default="ensemble"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_predictions_outcome", "predictions", ["outcome_correct"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("alert_type", sa.String(30), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("ticker", sa.String(10), nullable=True),
        sa.Column("acknowledged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_unacknowledged", "alerts", ["acknowledged", "created_at"])

    op.create_table(
        "day_trade_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("portfolio_id", sa.Integer, sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_day_trade_log_date", "day_trade_logs", ["portfolio_id", "trade_date"])

    op.create_table(
        "briefings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("headline", sa.String(120), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("top_3", sa.JSON, nullable=False),
        sa.Column("avoid_list", sa.JSON, nullable=False),
        sa.Column("market_context", sa.Text, nullable=False),
        sa.Column("signal_ids", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("portfolio_id", sa.Integer, sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("equity", MONEY, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("unrealized_pnl", MONEY, nullable=False),
        sa.Column("open_position_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("portfolio_id", "date", name="uq_portfolio_snapshot_date"),
    )
    op.create_index("ix_portfolio_snapshots_portfolio_date", "portfolio_snapshots", ["portfolio_id", "date"])

    # Seed default portfolio
    op.execute("INSERT INTO portfolios (cash, highest_milestone_reached) VALUES (10000.0000, 0)")


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("briefings")
    op.drop_table("day_trade_logs")
    op.drop_table("alerts")
    op.drop_table("predictions")
    op.drop_table("signals")
    op.drop_table("trades")
    op.drop_table("orders")
    op.drop_table("positions")
    op.drop_table("watchlist")
    op.drop_table("portfolios")
