"""Ticker thesis registry — short candidates across AI disruption and fundamental plays."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TickerThesis:
    ticker: str
    category: str
    thesis: str


TICKER_THESIS: dict[str, TickerThesis] = {
    "CVNA": TickerThesis(
        ticker="CVNA",
        category="Accounting Fraud",
        thesis=(
            "Gotham City Research and Hindenburg Research allege hidden related-party transactions with "
            "DriveTime/Bridgecrest overstated earnings by $1B+. SEC investigation confirmed via FOIA. "
            "DOJ involvement likely. Multiple securities fraud class actions filed."
        ),
    ),
    "DUOL": TickerThesis(
        ticker="DUOL",
        category="AI Disruption - EdTech",
        thesis=(
            "AI tutoring platforms commoditizing language learning at zero marginal cost. Management slashed "
            "2026 bookings guidance to 10-12% growth (down from 24%). Sacrificing $50M+ in bookings to invest "
            "in free user growth — conceding paid tier faces existential pressure from ChatGPT and AI tutors."
        ),
    ),
    "SMCI": TickerThesis(
        ticker="SMCI",
        category="Accounting Red Flags + DOJ",
        thesis=(
            "DOJ investigation into accounting practices ongoing. Gross margins collapsed to 6.4%. "
            "Management guided $2.3B QoQ revenue decline. Restated financials still incomplete. "
            "Dell and HPE competing aggressively in AI servers."
        ),
    ),
    "MSTR": TickerThesis(
        ticker="MSTR",
        category="Leveraged BTC Proxy",
        thesis=(
            "Most shorted large-cap stock (14% of market cap). Holds 717,722 BTC purchased at avg $66,385 — "
            "currently underwater. Trades at premium to NAV despite cheaper BTC ETFs existing. "
            "Convertible debt structure amplifies downside."
        ),
    ),
    "HIMS": TickerThesis(
        ticker="HIMS",
        category="Regulatory Catastrophe",
        thesis=(
            "SEC investigation + DOJ referral for mass marketing unapproved drugs + FDA crackdown on "
            "compounded GLP-1s + Novo Nordisk lawsuit. Pulled $49/month compounded semaglutide after FDA "
            "warned of swift action. GLP-1 revenue was major growth driver — now gone. SI at 32-34% of float."
        ),
    ),
    "AI": TickerThesis(
        ticker="AI",
        category="AI Disruption - Enterprise Software",
        thesis=(
            "C3.ai posted 46% YoY revenue plunge to $53.3M. EPS loss widened to -$0.94. Trades at 4.4x P/S "
            "vs 2.4x peer average despite revenue declining over 3 years. Open-source AI tools and vertical "
            "integration by enterprise clients eroding relevance. Multiple analyst downgrades to Sell."
        ),
    ),
    "PLTR": TickerThesis(
        ticker="PLTR",
        category="Valuation Compression - SaaSpocalypse",
        thesis=(
            "Palantir trades at 60-80x forward earnings in a market where software multiples are compressing. "
            "CEO Karp said AI will make many SaaS companies irrelevant — could apply to own platform. "
            "Hedge funds made $24B shorting software stocks in early 2026."
        ),
    ),
}
