#!/usr/bin/env python3
"""Screening pipeline for Short Game — discovers and qualifies short candidates.

Three-stage funnel:
  Screen  → yfinance most_shorted_stocks predefined screener
  Qualify → Finnhub fundamentals per candidate (insider, analyst, EPS, etc.)
  Review  → Prints ranked candidates for Claude to analyze
  Promote → Moves a candidate to the active watchlist
  Retire  → Deactivates a watchlist ticker with reason

Usage:
  python scripts/run_screen.py <DB_URL> <FINNHUB_KEY> screen
  python scripts/run_screen.py <DB_URL> <FINNHUB_KEY> qualify [--top N]
  python scripts/run_screen.py <DB_URL> <FINNHUB_KEY> review [--top N]
  python scripts/run_screen.py <DB_URL> <FINNHUB_KEY> promote TICKER --category CAT --thesis "TEXT"
  python scripts/run_screen.py <DB_URL> <FINNHUB_KEY> retire TICKER --reason "TEXT"
"""

import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import finnhub
import psycopg
import yfinance as yf


# ── CLI args ──

DB_URL = sys.argv[1] if len(sys.argv) > 1 else ""
FINNHUB_KEY = sys.argv[2] if len(sys.argv) > 2 else ""
COMMAND = sys.argv[3] if len(sys.argv) > 3 else ""

if not DB_URL or not FINNHUB_KEY or not COMMAND:
    print("Usage: python scripts/run_screen.py <DB_URL> <FINNHUB_KEY> <screen|qualify|review|promote|retire> [args]")
    sys.exit(1)


# ── Helpers ──

def parse_flag(flag: str, default: str | None = None) -> str | None:
    """Parse a --flag VALUE from sys.argv."""
    for i, arg in enumerate(sys.argv):
        if arg == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def round_dec(val: float, places: str = "0.0001") -> Decimal:
    return Decimal(str(val)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


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


# ── Screen Score (0-100) ──

def compute_screen_score(si_pct: float, market_cap: int | None, avg_volume: int | None,
                         pe_ratio: float | None, momentum_20d: float | None) -> float:
    """
    Screen score formula:
      SI% weight (0-30): higher SI = higher score
      Market cap penalty (0-15): >$50B gets 0, <$2B gets 15
      Volume score (0-15): adequate liquidity for shorting
      P/E score (0-20): extreme or negative P/E = higher
      Momentum (0-20): negative 20d momentum = higher
    """
    score = 0.0

    # SI% (0-30): linear scale, cap at 60%
    si_clamped = min(si_pct, 60.0)
    score += (si_clamped / 60.0) * 30.0

    # Market cap penalty (0-15): smaller = more shortable
    if market_cap is not None and market_cap > 0:
        if market_cap < 2_000_000_000:
            score += 15.0
        elif market_cap < 10_000_000_000:
            score += 10.0
        elif market_cap < 50_000_000_000:
            score += 5.0
        # >$50B gets 0

    # Volume (0-15): need liquidity to short
    if avg_volume is not None and avg_volume > 0:
        if avg_volume > 5_000_000:
            score += 15.0
        elif avg_volume > 1_000_000:
            score += 10.0
        elif avg_volume > 500_000:
            score += 5.0
        # <500K too illiquid, 0 points

    # P/E (0-20): negative or extreme = bearish thesis
    if pe_ratio is not None:
        if pe_ratio < 0:
            score += 20.0  # Negative earnings
        elif pe_ratio > 100:
            score += 15.0  # Wildly overvalued
        elif pe_ratio > 50:
            score += 10.0
        elif pe_ratio > 30:
            score += 5.0

    # Momentum (0-20): negative = bearish
    if momentum_20d is not None:
        if momentum_20d < -15:
            score += 20.0
        elif momentum_20d < -10:
            score += 15.0
        elif momentum_20d < -5:
            score += 10.0
        elif momentum_20d < 0:
            score += 5.0

    return min(score, 100.0)


# ── Qual Score (0-100) ──

def compute_qual_score(screen_score: float, analyst_data: dict | None,
                       insider_mspr: float | None, eps_revision_pct: float | None,
                       downgrade_count: int | None, price_target_gap_pct: float | None) -> float:
    """
    Qual score adds fundamental data to screen_score, re-normalized to 0-100:
      Analyst sentiment (0-20): more sell ratings = higher
      Insider selling (0-20): negative MSPR = higher
      EPS revisions (0-20): downward revisions = higher
      Downgrades (0-15): more recent downgrades = higher
      Price target gap (0-25): current price above consensus target = higher
    """
    raw_addition = 0.0

    # Analyst sentiment (0-20)
    if analyst_data:
        total = analyst_data.get("buy", 0) + analyst_data.get("hold", 0) + analyst_data.get("sell", 0)
        if total > 0:
            sell_ratio = analyst_data.get("sell", 0) / total
            raw_addition += sell_ratio * 20.0

    # Insider selling (0-20): MSPR ranges -100 to +100
    if insider_mspr is not None:
        if insider_mspr < -50:
            raw_addition += 20.0
        elif insider_mspr < -20:
            raw_addition += 15.0
        elif insider_mspr < 0:
            raw_addition += 10.0

    # EPS revisions (0-20): negative revision % = bearish
    if eps_revision_pct is not None:
        if eps_revision_pct < -20:
            raw_addition += 20.0
        elif eps_revision_pct < -10:
            raw_addition += 15.0
        elif eps_revision_pct < -5:
            raw_addition += 10.0
        elif eps_revision_pct < 0:
            raw_addition += 5.0

    # Downgrades (0-15)
    if downgrade_count is not None:
        if downgrade_count >= 5:
            raw_addition += 15.0
        elif downgrade_count >= 3:
            raw_addition += 10.0
        elif downgrade_count >= 1:
            raw_addition += 5.0

    # Price target gap (0-25): positive gap means current price > target (bearish)
    if price_target_gap_pct is not None:
        if price_target_gap_pct > 30:
            raw_addition += 25.0
        elif price_target_gap_pct > 15:
            raw_addition += 20.0
        elif price_target_gap_pct > 5:
            raw_addition += 15.0
        elif price_target_gap_pct > 0:
            raw_addition += 10.0

    # Re-normalize: weighted average of screen (40%) and fundamental (60%)
    max_fundamental = 100.0  # max possible raw_addition
    fundamental_normalized = min((raw_addition / max_fundamental) * 100.0, 100.0)
    combined = screen_score * 0.4 + fundamental_normalized * 0.6

    return min(combined, 100.0)


# ── Subcommands ──

def cmd_screen():
    """Run yfinance most_shorted_stocks screener and upsert to screen_candidates."""
    print("Running yfinance most-shorted screener...")

    response = yf.screen("most_shorted_stocks", count=100)

    quotes = response.get("quotes", [])
    if not quotes:
        print("ERROR: No results from screener")
        sys.exit(1)

    print(f"Screener returned {len(quotes)} tickers")
    print("Fetching short interest data per ticker...")

    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()
    now = datetime.now(UTC)
    upserted = 0

    for i, q in enumerate(quotes):
        ticker = q.get("symbol", "")
        if not ticker or len(ticker) > 10:
            continue

        # Screener provides: marketCap, averageDailyVolume3Month, forwardPE, regularMarketPrice, fiftyDayAverage
        # But NOT shortPercentOfFloat — need Ticker.info for that
        market_cap = q.get("marketCap")
        avg_volume = q.get("averageDailyVolume3Month") or q.get("averageDailyVolume10Day")
        pe_ratio = q.get("forwardPE")

        # Compute momentum from regularMarketPrice vs fiftyDayAverage
        price = q.get("regularMarketPrice", 0) or 0
        fifty_day = q.get("fiftyDayAverage", 0) or 0
        momentum_20d = None
        if price > 0 and fifty_day > 0:
            momentum_20d = ((price - fifty_day) / fifty_day) * 100

        # Fetch actual SI% from Ticker.info (screener doesn't include it)
        si_pct = 0.0
        try:
            info = yf.Ticker(ticker).info
            si_float = info.get("shortPercentOfFloat", 0) or 0
            # yfinance returns as fraction (0.44 = 44%), convert to percentage
            si_pct = float(si_float) * 100 if si_float < 1 else float(si_float)
            # Also grab trailingPE if forwardPE was missing
            if pe_ratio is None:
                pe_ratio = info.get("trailingPE")
        except Exception as e:
            print(f"    {ticker}: info fetch failed ({e}), using rank-based SI estimate")
            # Fallback: since screener sorts by SI% DESC, estimate from rank position
            si_pct = max(5.0, 50.0 - (i * 0.5))

        screen_score = compute_screen_score(
            si_pct=si_pct,
            market_cap=int(market_cap) if market_cap else None,
            avg_volume=int(avg_volume) if avg_volume else None,
            pe_ratio=float(pe_ratio) if pe_ratio else None,
            momentum_20d=float(momentum_20d) if momentum_20d is not None else None,
        )

        cur.execute("""
            INSERT INTO screen_candidates (
                ticker, source, screen_score, short_interest_pct,
                market_cap, avg_volume, pe_ratio, momentum_20d,
                status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'screened', %s)
            ON CONFLICT (ticker) DO UPDATE SET
                screen_score = EXCLUDED.screen_score,
                short_interest_pct = EXCLUDED.short_interest_pct,
                market_cap = EXCLUDED.market_cap,
                avg_volume = EXCLUDED.avg_volume,
                pe_ratio = EXCLUDED.pe_ratio,
                momentum_20d = EXCLUDED.momentum_20d,
                created_at = EXCLUDED.created_at
        """, (
            ticker, "yfinance_most_shorted",
            round_dec(screen_score, "0.1"),
            round_dec(si_pct),
            int(market_cap) if market_cap else None,
            int(avg_volume) if avg_volume else None,
            round_dec(float(pe_ratio)) if pe_ratio else None,
            round_dec(float(momentum_20d)) if momentum_20d is not None else None,
            now,
        ))
        upserted += 1

        print(f"  {ticker:6s}  SI: {si_pct:5.1f}%  Score: {screen_score:5.1f}  MktCap: {market_cap or 0:>14,}")

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nUpserted {upserted} candidates to screen_candidates")


def cmd_qualify():
    """Qualify top N screened candidates with Finnhub fundamental data."""
    top_n = int(parse_flag("--top", "10"))
    client = finnhub.Client(api_key=FINNHUB_KEY)

    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()

    # Get top N candidates by screen_score that haven't been qualified yet
    cur.execute("""
        SELECT id, ticker, screen_score, short_interest_pct
        FROM screen_candidates
        WHERE status = 'screened'
        ORDER BY screen_score DESC
        LIMIT %s
    """, (top_n,))
    candidates = cur.fetchall()

    if not candidates:
        print("No screened candidates to qualify. Run 'screen' first.")
        cur.close()
        conn.close()
        return

    print(f"Qualifying {len(candidates)} candidates with Finnhub fundamentals...")
    now = datetime.now(UTC)
    ninety_days_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    for cid, ticker, screen_score, si_pct in candidates:
        print(f"\n{'─' * 60}")
        print(f"  {ticker} (screen_score: {screen_score})")
        print(f"{'─' * 60}")

        # 1. Insider sentiment (MSPR)
        insider_mspr = None
        insider_data = finnhub_retry(client.stock_insider_sentiment, ticker, "2024-01-01", today)
        if insider_data and insider_data.get("data"):
            # Aggregate MSPR over available months
            msprs = [m.get("mspr", 0) for m in insider_data["data"] if m.get("mspr") is not None]
            if msprs:
                insider_mspr = sum(msprs) / len(msprs)
                print(f"  Insider MSPR: {insider_mspr:.2f} (avg of {len(msprs)} months)")
        time.sleep(1)

        # 2. Analyst recommendation trends
        analyst_data = None
        analyst_consensus = None
        recs = finnhub_retry(client.recommendation_trends, ticker)
        if recs and len(recs) > 0:
            r = recs[0]
            buy = r.get("buy", 0) + r.get("strongBuy", 0)
            sell = r.get("sell", 0) + r.get("strongSell", 0)
            hold = r.get("hold", 0)
            analyst_data = {"buy": buy, "hold": hold, "sell": sell}
            total = buy + hold + sell
            if total > 0:
                if sell > buy:
                    analyst_consensus = "sell"
                elif buy > sell:
                    analyst_consensus = "buy"
                else:
                    analyst_consensus = "hold"
            print(f"  Analyst: Buy={buy} Hold={hold} Sell={sell} → {analyst_consensus}")
        time.sleep(1)

        # 3. EPS estimate revisions
        eps_revision_pct = None
        earnings = finnhub_retry(client.company_eps_estimates, ticker, freq="quarterly")
        if earnings and earnings.get("data") and len(earnings["data"]) >= 2:
            recent = earnings["data"][0]
            prev = earnings["data"][1]
            est_now = recent.get("epsAvg")
            est_prev = prev.get("epsAvg")
            if est_now is not None and est_prev is not None and est_prev != 0:
                eps_revision_pct = ((est_now - est_prev) / abs(est_prev)) * 100
                print(f"  EPS Revision: {eps_revision_pct:+.1f}% (${est_prev:.2f} → ${est_now:.2f})")
        time.sleep(1)

        # 4. Upgrade/downgrade activity (last 90 days)
        downgrade_count = 0
        upgrades = finnhub_retry(client.upgrade_downgrade, symbol=ticker, _from=ninety_days_ago, to=today)
        if upgrades:
            downgrade_count = sum(1 for u in upgrades if u.get("action", "").lower() in ("downgrade", "down"))
            upgrade_count = sum(1 for u in upgrades if u.get("action", "").lower() in ("upgrade", "up"))
            print(f"  Upgrades/Downgrades (90d): {upgrade_count} up / {downgrade_count} down")
        time.sleep(1)

        # 5. Price target consensus
        price_target_gap_pct = None
        targets = finnhub_retry(client.price_target, ticker)
        if targets and targets.get("targetMedian"):
            target_median = targets["targetMedian"]
            last_close = targets.get("lastClose") or targets.get("targetMean", 0)
            if last_close and last_close > 0:
                # Positive gap = price above target (bearish for shorts = good)
                price_target_gap_pct = ((last_close - target_median) / target_median) * 100
                print(f"  Price Target: ${target_median:.2f} median, last ${last_close:.2f} → gap {price_target_gap_pct:+.1f}%")
        time.sleep(1)

        # Compute qual score
        qual_score = compute_qual_score(
            screen_score=float(screen_score),
            analyst_data=analyst_data,
            insider_mspr=insider_mspr,
            eps_revision_pct=eps_revision_pct,
            downgrade_count=downgrade_count,
            price_target_gap_pct=price_target_gap_pct,
        )
        print(f"  Qual Score: {qual_score:.1f}")

        # Update DB
        cur.execute("""
            UPDATE screen_candidates SET
                qual_score = %s,
                analyst_consensus = %s,
                insider_sentiment = %s,
                eps_revision_pct = %s,
                downgrade_count_90d = %s,
                price_target_gap_pct = %s,
                status = 'qualified',
                qualified_at = %s
            WHERE id = %s
        """, (
            round_dec(qual_score, "0.1"),
            analyst_consensus,
            round_dec(insider_mspr) if insider_mspr is not None else None,
            round_dec(eps_revision_pct) if eps_revision_pct is not None else None,
            downgrade_count,
            round_dec(price_target_gap_pct) if price_target_gap_pct is not None else None,
            now,
            cid,
        ))

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nQualified {len(candidates)} candidates")


def cmd_review():
    """Print top qualified candidates ranked by qual_score for Claude to analyze."""
    top_n = int(parse_flag("--top", "20"))

    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT ticker, screen_score, qual_score, short_interest_pct,
               market_cap, avg_volume, pe_ratio, momentum_20d,
               analyst_consensus, insider_sentiment, eps_revision_pct,
               downgrade_count_90d, price_target_gap_pct, status, qualified_at
        FROM screen_candidates
        WHERE status IN ('screened', 'qualified')
        ORDER BY COALESCE(qual_score, screen_score) DESC
        LIMIT %s
    """, (top_n,))
    candidates = cur.fetchall()
    cur.close()
    conn.close()

    if not candidates:
        print("No candidates to review. Run 'screen' and 'qualify' first.")
        return

    # Also check existing watchlist to flag overlaps
    conn2 = psycopg.connect(DB_URL)
    cur2 = conn2.cursor()
    cur2.execute("SELECT ticker FROM watchlist WHERE active = true")
    active_tickers = {row[0] for row in cur2.fetchall()}
    cur2.close()
    conn2.close()

    print(f"{'═' * 80}")
    print(f"  SCREENING PIPELINE — Top {len(candidates)} Candidates")
    print(f"  Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'═' * 80}")
    print()

    for i, row in enumerate(candidates, 1):
        (ticker, screen_score, qual_score, si_pct, market_cap, avg_volume,
         pe_ratio, momentum_20d, analyst_consensus, insider_sentiment,
         eps_revision_pct, downgrade_count, price_target_gap, status, qualified_at) = row

        effective_score = qual_score if qual_score is not None else screen_score
        flag = " [ACTIVE]" if ticker in active_tickers else ""

        print(f"#{i:2d}  {ticker:6s}  Score: {effective_score:5.1f}  Status: {status}{flag}")

        print(f"     SI%: {si_pct:.1f}%", end="")
        if market_cap:
            if market_cap >= 1_000_000_000:
                print(f"  MktCap: ${market_cap / 1_000_000_000:.1f}B", end="")
            else:
                print(f"  MktCap: ${market_cap / 1_000_000:.0f}M", end="")
        if avg_volume:
            print(f"  AvgVol: {avg_volume:,}", end="")
        if pe_ratio:
            print(f"  P/E: {pe_ratio:.1f}", end="")
        if momentum_20d is not None:
            print(f"  Mom20d: {momentum_20d:+.1f}%", end="")
        print()

        if status == "qualified":
            parts = []
            if analyst_consensus:
                parts.append(f"Analyst: {analyst_consensus}")
            if insider_sentiment is not None:
                parts.append(f"InsiderMSPR: {insider_sentiment:.2f}")
            if eps_revision_pct is not None:
                parts.append(f"EPSRev: {eps_revision_pct:+.1f}%")
            if downgrade_count is not None:
                parts.append(f"Downgrades90d: {downgrade_count}")
            if price_target_gap is not None:
                parts.append(f"TargetGap: {price_target_gap:+.1f}%")
            if parts:
                print(f"     {' | '.join(parts)}")

        print()

    print(f"{'═' * 80}")
    print(f"  {len(candidates)} candidates shown. {len(active_tickers)} already on active watchlist.")
    print("  Use 'promote TICKER' to add a candidate to the watchlist.")
    print(f"{'═' * 80}")


def cmd_promote():
    """Promote a screen candidate to the active watchlist."""
    ticker = sys.argv[4].upper() if len(sys.argv) > 4 else ""
    category = parse_flag("--category")
    thesis = parse_flag("--thesis")

    if not ticker or not category or not thesis:
        print("Usage: python scripts/run_screen.py <DB> <KEY> promote TICKER --category CAT --thesis TEXT")
        sys.exit(1)

    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()
    now = datetime.now(UTC)

    # Verify candidate exists
    cur.execute("SELECT id, screen_score, qual_score, short_interest_pct FROM screen_candidates WHERE ticker = %s", (ticker,))
    row = cur.fetchone()
    if not row:
        print(f"ERROR: {ticker} not found in screen_candidates")
        cur.close()
        conn.close()
        sys.exit(1)

    cid, screen_score, qual_score, si_pct = row

    # Check if already in watchlist
    cur.execute("SELECT id, active FROM watchlist WHERE ticker = %s", (ticker,))
    wl_row = cur.fetchone()

    if wl_row:
        wl_id, active = wl_row
        if active:
            print(f"ERROR: {ticker} is already active in watchlist")
            cur.close()
            conn.close()
            sys.exit(1)
        # Reactivate
        cur.execute("""
            UPDATE watchlist SET
                active = true, removed_at = NULL, removal_reason = NULL,
                thesis_category = %s, thesis_text = %s,
                source = 'screen_pipeline', screen_candidate_id = %s
            WHERE id = %s
        """, (category, thesis, cid, wl_id))
        print(f"Reactivated {ticker} in watchlist")
    else:
        cur.execute("""
            INSERT INTO watchlist (
                ticker, thesis_category, thesis_text, short_interest_pct,
                days_to_cover, borrow_rate_annual, prev_borrow_rate,
                source, screen_candidate_id, active, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'screen_pipeline', %s, true, %s)
        """, (ticker, category, thesis, si_pct, Decimal("0"), Decimal("0"), Decimal("0"), cid, now))
        print(f"Added {ticker} to watchlist from screening pipeline")

    # Update candidate status
    cur.execute("""
        UPDATE screen_candidates SET status = 'promoted', promoted_at = %s WHERE id = %s
    """, (now, cid))

    conn.commit()
    cur.close()
    conn.close()

    print(f"  Score: {qual_score or screen_score} | SI%: {si_pct} | Category: {category}")


def cmd_retire():
    """Deactivate a watchlist ticker with reason."""
    ticker = sys.argv[4].upper() if len(sys.argv) > 4 else ""
    reason = parse_flag("--reason", "manual retirement")

    if not ticker:
        print("Usage: python scripts/run_screen.py <DB> <KEY> retire TICKER [--reason TEXT]")
        sys.exit(1)

    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()
    now = datetime.now(UTC)

    cur.execute("SELECT id, active FROM watchlist WHERE ticker = %s", (ticker,))
    row = cur.fetchone()
    if not row:
        print(f"ERROR: {ticker} not found in watchlist")
        cur.close()
        conn.close()
        sys.exit(1)

    wl_id, active = row
    if not active:
        print(f"{ticker} is already inactive")
        cur.close()
        conn.close()
        return

    cur.execute("""
        UPDATE watchlist SET active = false, removed_at = %s, removal_reason = %s WHERE id = %s
    """, (now, reason, wl_id))

    conn.commit()
    cur.close()
    conn.close()

    print(f"Retired {ticker} from watchlist: {reason}")


# ── Main ──

if __name__ == "__main__":
    commands = {
        "screen": cmd_screen,
        "qualify": cmd_qualify,
        "review": cmd_review,
        "promote": cmd_promote,
        "retire": cmd_retire,
    }

    handler = commands.get(COMMAND)
    if handler:
        handler()
    else:
        print(f"Unknown command: {COMMAND}")
        print("Commands: screen, qualify, review, promote, retire")
        sys.exit(1)
