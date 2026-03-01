#!/usr/bin/env python3
"""Local scan runner for Short Game — fetches real market data and computes quant signals.

Designed to run from Claude Code CLI. The AI analysis (fundamental + ensemble)
is performed by Claude Opus 4.6 in the CLI, not via API calls.

Usage:
  python scripts/run_scan.py <DB_URL> <FINNHUB_KEY> wipe       # Clear fake signals/predictions/briefings
  python scripts/run_scan.py <DB_URL> <FINNHUB_KEY> collect     # Fetch data + quant analysis → stdout
  python scripts/run_scan.py <DB_URL> <FINNHUB_KEY> write       # Write signals + briefing from JSON stdin
"""

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import finnhub
import numpy as np
import psycopg
import yfinance as yf


# ── CLI args ──

DB_URL = sys.argv[1] if len(sys.argv) > 1 else ""
FINNHUB_KEY = sys.argv[2] if len(sys.argv) > 2 else ""
COMMAND = sys.argv[3] if len(sys.argv) > 3 else "collect"

if not DB_URL or not FINNHUB_KEY:
    print("Usage: python scripts/run_scan.py <DB_URL> <FINNHUB_KEY> [wipe|collect|write]")
    sys.exit(1)


# ── Helpers ──

def round_price(val: float) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_technicals(closes: list[float]) -> dict:
    """RSI-14, momentum 5/10/20d, annualized volatility."""
    assert len(closes) >= 20, f"Need >=20 closes, got {len(closes)}"
    prices = np.array(closes, dtype=np.float64)
    returns = np.diff(prices) / prices[:-1]

    last_14 = returns[-14:]
    gains = np.where(last_14 > 0, last_14, 0.0)
    losses = np.where(last_14 < 0, -last_14, 0.0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))
    rsi = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    current = prices[-1]
    mom_5d = ((current - prices[-6]) / prices[-6]) * 100
    mom_10d = ((current - prices[-11]) / prices[-11]) * 100
    mom_20d = ((current - prices[-20]) / prices[-20]) * 100
    vol = float(np.std(returns[-20:], ddof=1) * np.sqrt(252))

    return {
        "rsi_14": round(rsi, 1),
        "momentum_5d_pct": round(float(mom_5d), 2),
        "momentum_10d_pct": round(float(mom_10d), 2),
        "momentum_20d_pct": round(float(mom_20d), 2),
        "volatility_20d": round(vol, 4),
    }


def quant_signal(price: float, technicals: dict, volume: int, avg_volume: int) -> dict:
    """Deterministic quant engine — mirrors app/domain/prediction/engines/quant_engine.py."""
    t = technicals
    confidence = 50

    if t["rsi_14"] > 70:
        confidence += 15
    elif t["rsi_14"] < 30:
        confidence -= 15

    neg_count = sum(
        1 for m in [t["momentum_5d_pct"], t["momentum_10d_pct"], t["momentum_20d_pct"]] if m < 0
    )
    confidence += neg_count * 10

    if avg_volume > 0 and volume > 2 * avg_volume:
        confidence += 10

    if t["volatility_20d"] > 0.5:
        confidence -= 5

    confidence = max(0, min(confidence, 85))

    if confidence >= 55:
        direction = "SHORT"
    elif confidence <= 35:
        direction = "AVOID"
    else:
        direction = "HOLD"

    vol_factor = max(t["volatility_20d"], 0.01)
    stop_pct = 1.08 + vol_factor * 0.1
    target_pct = 1 - (0.15 + vol_factor * 0.1)
    stop_loss = round(price * stop_pct, 2)
    target = round(price * target_pct, 2)

    reasoning = []
    if t["rsi_14"] > 70:
        reasoning.append(f"RSI-14 at {t['rsi_14']} — overbought")
    elif t["rsi_14"] < 30:
        reasoning.append(f"RSI-14 at {t['rsi_14']} — oversold, avoid shorting")

    if neg_count == 3:
        reasoning.append("All momentum windows (5d/10d/20d) negative — strong downtrend")
    elif neg_count >= 1:
        reasoning.append(f"{neg_count}/3 momentum windows negative")

    if avg_volume > 0 and volume > 2 * avg_volume:
        reasoning.append(f"Volume spike: {volume:,} vs {avg_volume:,} avg")

    if not reasoning:
        reasoning.append("No strong technical signals detected")

    return {
        "direction": direction,
        "confidence": confidence,
        "entry_price": price,
        "stop_loss": stop_loss,
        "target": target,
        "time_horizon_days": 3,
        "reasoning": reasoning,
    }


def classify_squeeze_risk(si_pct: float, dtc: float, borrow_rate: float, prev_rate: float) -> dict:
    """Squeeze risk classification — mirrors app/domain/game/rules/squeeze.py."""
    def _level(val, thresholds):
        for thresh, lvl in reversed(thresholds):
            if val >= thresh:
                return lvl
        return "LOW"

    si_level = _level(si_pct, [(10, "MEDIUM"), (20, "HIGH"), (40, "CRITICAL")])
    dtc_level = _level(dtc, [(3, "MEDIUM"), (5, "HIGH"), (8, "CRITICAL")])
    ctb_level = _level(borrow_rate * 100, [(5, "MEDIUM"), (20, "HIGH"), (50, "CRITICAL")])

    ratio = borrow_rate / prev_rate if prev_rate > 0 else 1.0
    ctb_spike_level = _level(ratio, [(2, "MEDIUM"), (3, "HIGH"), (5, "CRITICAL")])

    scores = {"LOW": 0, "MEDIUM": 33, "HIGH": 67, "CRITICAL": 100}

    if "CRITICAL" in (si_level, dtc_level, ctb_level, ctb_spike_level):
        return {"level": "CRITICAL", "score": 100, "si": si_level, "dtc": dtc_level, "ctb": ctb_level, "ctb_spike": ctb_spike_level}

    score = int(
        scores[si_level] * 0.35 + scores[dtc_level] * 0.25
        + scores[ctb_level] * 0.20 + scores[ctb_spike_level] * 0.20
    )

    if score >= 75:
        overall = "CRITICAL"
    elif score >= 55:
        overall = "HIGH"
    elif score >= 30:
        overall = "MEDIUM"
    else:
        overall = "LOW"

    return {"level": overall, "score": score, "si": si_level, "dtc": dtc_level, "ctb": ctb_level, "ctb_spike": ctb_spike_level}


def classify_data_quality(candles, quote, news, recommendation, earnings) -> str:
    if candles is None or quote is None:
        return "INCOMPLETE"
    optional_count = sum([
        news is not None and len(news) > 0,
        recommendation is not None,
        earnings is not None and earnings.get("date") is not None,
    ])
    if optional_count == 3:
        return "COMPLETE"
    elif optional_count >= 1:
        return "PARTIAL"
    return "STALE"


# ── Finnhub fetchers (sync, with retry) ──

def finnhub_retry(func, *args, **kwargs):
    """Retry Finnhub calls with backoff."""
    backoffs = (1, 2, 4)
    for attempt in range(3):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"    Finnhub retry {attempt + 1}/3: {e}")
            if attempt < 2:
                time.sleep(backoffs[attempt])
    return None


def fetch_candles_yfinance(ticker: str) -> list[dict] | None:
    """Fetch 20-day OHLCV from Yahoo Finance (free, no API key)."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1mo")
        if hist.empty:
            return None
        bars = []
        for date, row in hist.iterrows():
            bars.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return bars[-20:]
    except Exception as e:
        print(f"    yfinance error for {ticker}: {e}")
        return None


def fetch_ticker_data(client: finnhub.Client, ticker: str) -> dict:
    """Fetch market data: candles from yfinance, quote/news/recs/earnings from Finnhub."""

    # Required: candles from yfinance
    candles = fetch_candles_yfinance(ticker)
    if not candles:
        return {"error": f"No candle data for {ticker}"}

    # Required: quote from Finnhub
    quote_raw = finnhub_retry(client.quote, ticker)
    if not quote_raw or quote_raw.get("c", 0) == 0:
        return {"error": f"No quote data for {ticker}"}

    quote = {
        "price": float(quote_raw["c"]),
        "change_pct": float(quote_raw.get("dp", 0)),
        "volume": int(quote_raw.get("v", 0)),
        "prev_close": float(quote_raw.get("pc", 0)),
    }

    # Optional: news
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    week_ago = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    news_raw = finnhub_retry(client.company_news, ticker, _from=week_ago, to=today)
    news = None
    if news_raw:
        news = [
            {
                "headline": a.get("headline", ""),
                "source": a.get("source", ""),
                "datetime": datetime.fromtimestamp(a.get("datetime", 0), tz=UTC).strftime("%Y-%m-%d %H:%M"),
            }
            for a in news_raw[:8]
        ]

    # Optional: analyst recommendations
    recs_raw = finnhub_retry(client.recommendation_trends, ticker)
    recommendation = None
    if recs_raw and len(recs_raw) > 0:
        r = recs_raw[0]
        recommendation = {
            "buy": r.get("buy", 0), "hold": r.get("hold", 0), "sell": r.get("sell", 0),
            "strong_buy": r.get("strongBuy", 0), "strong_sell": r.get("strongSell", 0),
            "period": r.get("period", ""),
        }

    # Optional: earnings
    earnings_raw = finnhub_retry(client.company_earnings, ticker, limit=1)
    earnings = None
    if earnings_raw and len(earnings_raw) > 0:
        e = earnings_raw[0]
        earnings = {
            "date": e.get("period"),
            "eps_estimate": e.get("estimate"),
            "eps_actual": e.get("actual"),
        }

    return {
        "quote": quote,
        "candles": candles,
        "news": news,
        "recommendation": recommendation,
        "earnings": earnings,
    }


# ── Subcommands ──

def cmd_wipe():
    """Delete all signals, predictions, and briefings."""
    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("DELETE FROM predictions")
    pred_count = cur.rowcount
    cur.execute("DELETE FROM signals")
    sig_count = cur.rowcount
    cur.execute("DELETE FROM briefings")
    brief_count = cur.rowcount

    conn.commit()
    cur.close()
    conn.close()

    print(f"Wiped: {sig_count} signals, {pred_count} predictions, {brief_count} briefings")


def cmd_collect():
    """Fetch market data for all watchlist tickers and output analysis context."""
    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT ticker, thesis_category, thesis_text,
               short_interest_pct, days_to_cover, borrow_rate_annual, prev_borrow_rate
        FROM watchlist WHERE active = true ORDER BY ticker
    """)
    watchlist = cur.fetchall()
    cur.close()
    conn.close()

    if not watchlist:
        print("ERROR: No active watchlist tickers found")
        sys.exit(1)

    print(f"Scanning {len(watchlist)} tickers: {', '.join(w[0] for w in watchlist)}")
    print(f"Timestamp: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    client = finnhub.Client(api_key=FINNHUB_KEY)
    all_results = []

    for ticker, category, thesis, si_pct, dtc, borrow_rate, prev_borrow_rate in watchlist:
        print(f"{'═' * 72}")
        print(f"  {ticker} — {category}")
        print(f"{'═' * 72}")
        print(f"Thesis: {thesis}")
        print()

        # Rate limit: Finnhub free tier = 60 calls/min, ~5 calls per ticker
        data = fetch_ticker_data(client, ticker)
        if "error" in data:
            print(f"  SKIPPED: {data['error']}")
            print()
            continue

        quote = data["quote"]
        candles = data["candles"]
        news = data["news"]
        recommendation = data["recommendation"]
        earnings = data["earnings"]

        # Data quality
        dq = classify_data_quality(candles, quote, news, recommendation, earnings)

        # Technicals
        closes = [bar["close"] for bar in candles]
        if len(closes) < 20:
            while len(closes) < 20:
                closes.insert(0, closes[0])

        technicals = compute_technicals(closes)

        # Squeeze risk
        squeeze = classify_squeeze_risk(
            float(si_pct), float(dtc), float(borrow_rate), float(prev_borrow_rate)
        )

        # Volume
        volumes = [bar["volume"] for bar in candles]
        avg_volume = int(sum(volumes) / len(volumes)) if volumes else 0

        # Quant signal
        qs = quant_signal(quote["price"], technicals, quote["volume"], avg_volume)

        # Print report
        print(f"Price: ${quote['price']:.2f} ({quote['change_pct']:+.2f}%)")
        print(f"Volume: {quote['volume']:,} | 20d Avg: {avg_volume:,}")
        print(f"Data Quality: {dq}")
        print()

        print("Technical Indicators:")
        print(f"  RSI-14:       {technicals['rsi_14']}")
        print(f"  Momentum 5d:  {technicals['momentum_5d_pct']:+.2f}%")
        print(f"  Momentum 10d: {technicals['momentum_10d_pct']:+.2f}%")
        print(f"  Momentum 20d: {technicals['momentum_20d_pct']:+.2f}%")
        print(f"  Volatility:   {technicals['volatility_20d']:.4f}")
        print()

        print(f"Squeeze Risk: {squeeze['level']} (score: {squeeze['score']})")
        print(f"  SI%: {squeeze['si']} | DTC: {squeeze['dtc']} | CTB: {squeeze['ctb']} | CTB Spike: {squeeze['ctb_spike']}")
        print()

        if news:
            print(f"Recent News ({len(news)} articles):")
            for n in news[:5]:
                print(f"  • {n['headline'][:90]} — {n['source']} ({n['datetime']})")
            print()

        if recommendation:
            r = recommendation
            total = r["strong_buy"] + r["buy"] + r["hold"] + r["sell"] + r["strong_sell"]
            print(f"Analyst Consensus ({r['period']}):")
            print(f"  Strong Buy: {r['strong_buy']} | Buy: {r['buy']} | Hold: {r['hold']} | Sell: {r['sell']} | Strong Sell: {r['strong_sell']} (total: {total})")
            print()

        if earnings:
            eps_str = f"${earnings['eps_actual']}" if earnings["eps_actual"] is not None else "N/A"
            est_str = f"${earnings['eps_estimate']}" if earnings["eps_estimate"] is not None else "N/A"
            print(f"Last Earnings ({earnings['date'] or 'N/A'}): EPS {eps_str} vs est {est_str}")
            print()

        print(f"Quant Signal: {qs['direction']} ({qs['confidence']}% confidence)")
        print(f"  Entry: ${qs['entry_price']:.2f} | Stop: ${qs['stop_loss']:.2f} | Target: ${qs['target']:.2f}")
        print(f"  Horizon: {qs['time_horizon_days']} days")
        print(f"  Reasoning: {'; '.join(qs['reasoning'])}")
        print()

        print("20-Day Price History:")
        for bar in candles[-5:]:
            print(f"  {bar['date']}: ${bar['close']:.2f} (vol: {bar['volume']:,})")
        if len(candles) > 5:
            print(f"  ... ({len(candles) - 5} earlier bars omitted)")
        print()

        all_results.append({
            "ticker": ticker,
            "category": category,
            "thesis": thesis,
            "quote": quote,
            "technicals": technicals,
            "squeeze": squeeze,
            "data_quality": dq,
            "avg_volume_20d": avg_volume,
            "quant_signal": qs,
            "news_count": len(news) if news else 0,
        })

        # Respect rate limits between tickers
        time.sleep(1.5)

    # Summary
    print(f"{'═' * 72}")
    print("  SCAN SUMMARY")
    print(f"{'═' * 72}")
    for r in all_results:
        qs = r["quant_signal"]
        print(f"  {r['ticker']:5s}  ${r['quote']['price']:>9.2f}  Quant: {qs['direction']:5s} {qs['confidence']:2d}%  Squeeze: {r['squeeze']['level']}")
    print()
    print("Awaiting Claude Opus 4.6 fundamental analysis + ensemble synthesis...")


def cmd_write():
    """Write signals and briefing from JSON on stdin."""
    print("Paste JSON (signals + briefing), then Ctrl-D:")
    raw = sys.stdin.read()
    payload = json.loads(raw)

    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()
    now = datetime.now(UTC)

    signal_ids = []

    for sig in payload.get("signals", []):
        # Write each signal (quant, claude, ensemble) and linked prediction
        cur.execute("""
            INSERT INTO signals (
                ticker, signal_type, direction, confidence, entry_price,
                stop_loss, target, time_horizon_days, reasoning, catalyst,
                schema_version, data_quality, engine_source, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            sig["ticker"], "daily_scan", sig["direction"], sig["confidence"],
            Decimal(str(sig["entry_price"])),
            Decimal(str(sig["stop_loss"])),
            Decimal(str(sig["target"])),
            sig["time_horizon_days"],
            json.dumps(sig.get("reasoning", [])),
            sig.get("catalyst", ""),
            "v1", sig.get("data_quality", "COMPLETE"),
            sig["engine_source"], now,
        ))
        signal_id = cur.fetchone()[0]
        signal_ids.append(signal_id)
        print(f"  Signal #{signal_id}: {sig['ticker']} {sig['engine_source']} {sig['direction']} {sig['confidence']}%")

        # Linked prediction
        cur.execute("""
            INSERT INTO predictions (
                signal_id, ticker, predicted_direction, confidence, engine_source, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            signal_id, sig["ticker"], sig["direction"],
            sig["confidence"], sig["engine_source"], now,
        ))

    # Briefing
    briefing = payload.get("briefing")
    if briefing:
        ensemble_ids = [
            sid for sid, sig in zip(signal_ids, payload["signals"])
            if sig["engine_source"] == "ensemble"
        ]
        cur.execute("""
            INSERT INTO briefings (
                headline, summary, top_3, avoid_list, market_context, signal_ids, created_at
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s)
        """, (
            briefing["headline"],
            briefing["summary"],
            json.dumps(briefing["top_3"]),
            json.dumps(briefing.get("avoid_list", [])),
            briefing.get("market_context", ""),
            json.dumps(ensemble_ids),
            now,
        ))
        print(f"  Briefing: {briefing['headline']}")

    # Alert
    cur.execute("""
        INSERT INTO alerts (alert_type, priority, message, acknowledged, created_at)
        VALUES (%s, %s, %s, false, %s)
    """, ("BRIEFING_READY", "INFO", "Morning scan complete — real signals generated via CLI", now))

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nWrote {len(signal_ids)} signals, {len(signal_ids)} predictions, 1 briefing, 1 alert")


# ── Main ──

if __name__ == "__main__":
    if COMMAND == "wipe":
        cmd_wipe()
    elif COMMAND == "collect":
        cmd_collect()
    elif COMMAND == "write":
        cmd_write()
    else:
        print(f"Unknown command: {COMMAND}")
        print("Usage: python scripts/run_scan.py <DB_URL> <FINNHUB_KEY> [wipe|collect|write]")
        sys.exit(1)
