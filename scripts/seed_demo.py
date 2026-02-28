"""Seed Railway database with demo data for Short Game.

Pulls live quotes from Finnhub so prices are always current.
Usage: python scripts/seed_demo.py <DATABASE_PUBLIC_URL> <FINNHUB_API_KEY>
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.request import urlopen

DB_URL = sys.argv[1] if len(sys.argv) > 1 else ""
FINNHUB_KEY = sys.argv[2] if len(sys.argv) > 2 else ""
if not DB_URL or not FINNHUB_KEY:
    print("Usage: python scripts/seed_demo.py <DATABASE_PUBLIC_URL> <FINNHUB_API_KEY>")
    sys.exit(1)

import psycopg


def get_quote(ticker: str) -> Decimal:
    """Fetch current price from Finnhub."""
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
    with urlopen(url) as resp:
        data = json.loads(resp.read())
    price = data.get("c", 0)
    if not price:
        print(f"  WARNING: No price for {ticker}, using 0")
        return Decimal("0")
    return Decimal(str(price))


def round_price(price: Decimal) -> Decimal:
    return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


now = datetime.now(UTC)

conn = psycopg.connect(DB_URL)
cur = conn.cursor()

# ── Fetch live prices ──
tickers = ["CVNA", "MSTR", "UPST", "RIVN", "SMCI", "DUOL"]
prices = {}
print("Fetching live quotes...")
for t in tickers:
    prices[t] = get_quote(t)
    print(f"  {t}: ${prices[t]}")

# ── Watchlist: 6 short candidates with static thesis data ──
watchlist = [
    ("CVNA", "Valuation Disconnect",
     "Carvana trades at extreme forward earnings multiples with declining unit economics. Used car market normalizing post-COVID. Debt load of $6B creates existential risk if volumes soften.",
     "18.5", "4.2", "0.085", "0.072"),
    ("MSTR", "Leveraged BTC Proxy",
     "MicroStrategy is a leveraged Bitcoin bet trading at massive premium to NAV. Convertible debt structure amplifies downside. Post-split shares still price in extreme BTC optimism. If BTC corrects 30%, equity could lose 60%+.",
     "22.3", "3.8", "0.125", "0.098"),
    ("UPST", "AI Lending Hype",
     "Upstart's AI lending model untested in real recession. Loan performance deteriorating. Stock down from peak but recent bounce on AI narrative is unsustainable without fundamental improvement in default rates.",
     "28.7", "5.1", "0.095", "0.082"),
    ("RIVN", "Cash Burn Machine",
     "Rivian burning $1.5B/quarter with no path to profitability before 2027. Competition intensifying from legacy OEMs. Current valuation implies far higher annual deliveries than actual production supports.",
     "15.2", "3.5", "0.065", "0.058"),
    ("SMCI", "Accounting Red Flags",
     "Super Micro Computer under DOJ investigation. Delayed 10-K filing. Revenue recognition concerns. AI server demand may be double-counted through channel partners.",
     "24.1", "6.3", "0.145", "0.110"),
    ("DUOL", "Growth Deceleration",
     "Duolingo's DAU growth slowing. Premium conversion plateauing. Valuation at high revenue multiples assumes sustained hypergrowth that recent metrics don't support.",
     "12.8", "2.9", "0.045", "0.038"),
]

for ticker, cat, thesis, si, dtc, br, pbr in watchlist:
    cur.execute("""
        INSERT INTO watchlist (ticker, thesis_category, thesis_text, short_interest_pct, days_to_cover, borrow_rate_annual, prev_borrow_rate, active, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s)
        ON CONFLICT (ticker) DO UPDATE SET
            thesis_category = EXCLUDED.thesis_category,
            thesis_text = EXCLUDED.thesis_text,
            short_interest_pct = EXCLUDED.short_interest_pct,
            days_to_cover = EXCLUDED.days_to_cover,
            borrow_rate_annual = EXCLUDED.borrow_rate_annual,
            prev_borrow_rate = EXCLUDED.prev_borrow_rate
    """, (ticker, cat, thesis, Decimal(si), Decimal(dtc), Decimal(br), Decimal(pbr), now))

print(f"Seeded {len(watchlist)} watchlist entries")

# ── Signals: 4 actionable signals with live prices ──
# Stop loss ~18% above entry, target ~32% below entry (short positions)
signals = [
    ("CVNA", "SHORT", "SHORT", 78,
     round_price(prices["CVNA"]),
     round_price(prices["CVNA"] * Decimal("1.12")),
     round_price(prices["CVNA"] * Decimal("0.78")),
     14,
     {"thesis": "Valuation disconnect deepening",
      "catalysts": ["Q4 earnings miss expected", "Used car prices declining MoM"],
      "risks": ["Short squeeze potential", "Retail momentum"]},
     "Q4 earnings report upcoming — consensus expects beat but unit economics suggest miss",
     "ensemble"),
    ("SMCI", "SHORT", "SHORT", 85,
     round_price(prices["SMCI"]),
     round_price(prices["SMCI"] * Decimal("1.19")),
     round_price(prices["SMCI"] * Decimal("0.68")),
     10,
     {"thesis": "Accounting investigation escalating",
      "catalysts": ["DOJ probe timeline accelerating", "Auditor concerns unresolved"],
      "risks": ["AI demand could paper over issues", "Buyback support"]},
     "DOJ investigation update expected — market underpricing restatement risk",
     "ensemble"),
    ("MSTR", "SHORT", "SHORT", 72,
     round_price(prices["MSTR"]),
     round_price(prices["MSTR"] * Decimal("1.19")),
     round_price(prices["MSTR"] * Decimal("0.69")),
     21,
     {"thesis": "BTC premium unsustainable at post-split levels",
      "catalysts": ["Bitcoin approaching key resistance", "Convertible debt maturity in Q2"],
      "risks": ["BTC breakout above $100K", "Retail FOMO"]},
     "Bitcoin showing bearish divergence on weekly RSI — MSTR amplifies any BTC weakness 2-3x",
     "ensemble"),
    ("UPST", "HOLD", "SHORT", 55,
     round_price(prices["UPST"]),
     round_price(prices["UPST"] * Decimal("1.21")),
     round_price(prices["UPST"] * Decimal("0.66")),
     14,
     {"thesis": "AI lending narrative fading",
      "catalysts": ["Loan default rates rising", "Funding partner pullback"],
      "risks": ["New bank partnerships", "Rate cuts boost origination"]},
     "Wait for confirmation — loan performance data due next week before initiating",
     "ensemble"),
]

signal_ids = []
for ticker, stype, direction, conf, entry, sl, target, horizon, reasoning, catalyst, engine in signals:
    cur.execute("""
        INSERT INTO signals (ticker, signal_type, direction, confidence, entry_price, stop_loss, target, time_horizon_days, reasoning, catalyst, schema_version, data_quality, engine_source, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, '1.0', 'GOOD', %s, %s)
        RETURNING id
    """, (ticker, stype, direction, conf, entry, sl, target, horizon,
          json.dumps(reasoning), catalyst, engine, now - timedelta(hours=2)))
    signal_ids.append(cur.fetchone()[0])
    print(f"  Signal: {ticker} entry=${entry} stop=${sl} target=${target}")

print(f"Seeded {len(signals)} signals")

# ── Predictions linked to signals ──
for sid, (ticker, _, direction, conf, *_rest) in zip(signal_ids, signals):
    engine = _rest[-1]
    cur.execute("""
        INSERT INTO predictions (signal_id, ticker, predicted_direction, confidence, engine_source, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (sid, ticker, direction, conf, engine, now - timedelta(hours=2)))

print(f"Seeded {len(signal_ids)} predictions")

# ── Briefing ──
top_3 = [
    {"ticker": s[0], "confidence": s[3], "entry": str(s[4]), "target": str(s[6]), "catalyst": s[9]}
    for s in signals[:3]
]
cur.execute("""
    INSERT INTO briefings (headline, summary, top_3, avoid_list, market_context, signal_ids, created_at)
    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s)
""", (
    "Accounting Risk and Valuation Gaps Create Short Opportunities",
    f"Three high-conviction shorts emerge from today's scan. SMCI leads with 85% confidence as DOJ investigation pressure mounts — the market is dramatically underpricing restatement risk. CVNA's valuation disconnect widens ahead of earnings, with used car prices in freefall. MSTR offers a leveraged play on Bitcoin weakness as BTC shows bearish divergence on weekly timeframes. Avoid UPST until loan performance data confirms the thesis.",
    json.dumps(top_3),
    json.dumps([
        {"ticker": "UPST", "reason": "Wait for loan performance data confirmation"},
        {"ticker": "RIVN", "reason": "High institutional ownership limits downside velocity"},
    ]),
    "Market showing signs of rotation out of momentum into value. VIX elevated suggesting uncertainty. Fed minutes hawkish — rate cuts pushed to H2. Credit spreads widening slightly. Overall environment favors selective shorts in overvalued names with identifiable catalysts.",
    json.dumps(signal_ids),
    now - timedelta(hours=1),
))

print("Seeded briefing")

# ── Alerts ──
smci_price = prices["SMCI"]
cvna_price = prices["CVNA"]
alerts = [
    ("BRIEFING_READY", "INFO", "Morning briefing ready — 3 actionable signals identified", None),
    ("SQUEEZE_ESCALATION", "WARNING", "SMCI squeeze risk elevated to MEDIUM (SI: 24.1%, DTC: 6.3 days)", "SMCI"),
    ("SIGNAL_NEW", "INFO", f"New SHORT signal: CVNA at ${cvna_price} (78% confidence)", "CVNA"),
    ("SIGNAL_NEW", "INFO", f"New SHORT signal: SMCI at ${smci_price} (85% confidence)", "SMCI"),
]

for atype, priority, message, ticker in alerts:
    cur.execute("""
        INSERT INTO alerts (alert_type, priority, message, ticker, acknowledged, created_at)
        VALUES (%s, %s, %s, %s, false, %s)
    """, (atype, priority, message, ticker, now - timedelta(minutes=30)))

print(f"Seeded {len(alerts)} alerts")

conn.commit()
cur.close()
conn.close()
print("Done — database seeded with live market data")
