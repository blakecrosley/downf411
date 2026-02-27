# Short Game

AI-powered paper trading simulator focused on short selling. Single-player game for Blake.
Domain: downf411.com (Cloudflare Access).

## Stack
- **Backend:** FastAPI + SQLAlchemy 2.0 async + asyncpg + Pydantic v2
- **Frontend:** HTMX + Alpine.js + Bootstrap 5 + plain CSS (NO Tailwind, NO React, NO build tools)
- **Database:** PostgreSQL on Railway, NUMERIC(18,4) for ALL money, Python Decimal throughout
- **Scheduler:** APScheduler in-process (NOT Celery, NOT Redis)
- **AI:** Claude Opus (claude-opus-4-6) via Anthropic SDK — NEVER OpenAI, NEVER Sonnet/Haiku
- **Market Data:** Finnhub via finnhub-python (60 calls/min free tier)
- **Auth:** Cloudflare Access (zero application-level auth code)

## Architecture: Multi-Engine Prediction
Three prediction engines + risk veto:
1. **Claude Engine** — fundamental analysis, news sentiment, AI disruption thesis (app/domain/prediction/engines/claude_engine.py)
2. **Quant Engine** — technical indicators, deterministic signals from RSI/momentum/volume (app/domain/prediction/engines/quant_engine.py)
3. **Ensemble Arbitrator** — Claude synthesizes all engine outputs into final signal (app/domain/prediction/engines/ensemble.py)
4. **RiskEngine** — vetoes entries, triggers forced liquidation, independent of prediction (app/domain/game/risk_engine.py)

All engines implement `PredictionEngine` Protocol. Signal model tracks `engine_source` ('claude', 'quant', 'ensemble').

## Game Rules (Constants)
- Starting cash: $10,000
- Initial margin: 150% of short value
- Maintenance margin: 130%
- Forced liquidation: 110%
- PDT threshold: $25,000 equity
- PDT limit: 3 day-trades per 5 rolling business days
- Borrow fee: (shares * price * annual_rate) / 360 per day
- Kelly criterion: disabled until 20 trades, max 25% of equity, min 1%
- Milestones: $100k, $150k, $250k, $500k, $1M (one-way, no downgrade)

## API Convention
- All endpoints: `{"data": ..., "meta": {"timestamp": "...", "market_open": bool}}`
- Pydantic response_model on every endpoint
- Errors: `{"data": null, "meta": {...}, "errors": [{"code": "...", "message": "..."}]}`

## Critical Rules
- ALL monetary arithmetic uses Decimal, NEVER float
- No TODO/FIXME/HACK in committed code
- exchange_calendars for all business day calculations
- Confidence is 0-100 integer (not 0.0-1.0 float)
- Claude API calls use tool_use (structured output), NOT JSON-in-text parsing
- Prompt text lives in prompts/*.txt files, loaded at startup

## Integration Patterns

### ServiceContainer (app/container.py)
Singleton holding shared services. Created during FastAPI lifespan, stored on `app.state.container`.
Contains: Anthropic client, Finnhub adapter, session factory, scheduler reference.
All domain services and jobs receive dependencies from the container via FastAPI `Depends()`.

### Dual Router Architecture
- `app/api/v1/router.py` — JSON API (response envelope: `{data, meta}`)
- `app/api/v1/partials.py` — HTMX HTML fragments (`response_class=HTMLResponse`)
Both mounted on the app. Partials endpoints return rendered Jinja2 template fragments.

### Alembic Configuration
`alembic/env.py` loads DATABASE_URL from `app.config`. Uses sync psycopg (not asyncpg).
Railway deploy: `alembic upgrade head && uvicorn ...` in railway.json startCommand.

### APScheduler Jobs
All jobs receive ServiceContainer. Misfire grace times: daily_scan=3600s, intraday=300s. Coalesce=True on all.

### Mark-to-Market 5-Phase Order
Phase 1: prices, Phase 2: borrow fees, Phase 3: stop-loss/take-profit, Phase 4: margin check, Phase 5: milestones.
Stop-loss auto-closes. Take-profit is advisory only. Forced liquidation is PDT-exempt. Largest-loss-first liquidation with recalc after each.

## Watchlist Tickers
DUOL, CRM, ZIP, LYFT, UBER — all AI disruption thesis plays.

## Reference Specifications
PRD: `prd.json` (v1.2.0, 19 stories, 7 waves)
