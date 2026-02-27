"""Ticker thesis registry — AI disruption plays."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TickerThesis:
    ticker: str
    category: str
    thesis: str


TICKER_THESIS: dict[str, TickerThesis] = {
    "DUOL": TickerThesis(
        ticker="DUOL",
        category="AI Disruption - EdTech",
        thesis=(
            "AI tutoring platforms are commoditizing language learning. GPT-powered apps offer personalized "
            "instruction at zero marginal cost, threatening Duolingo's gamified approach. As AI tutors improve, "
            "the gap between free AI instruction and Duolingo's paid tier narrows."
        ),
    ),
    "CRM": TickerThesis(
        ticker="CRM",
        category="AI Disruption - Enterprise SaaS",
        thesis=(
            "AI agents are automating sales workflows that Salesforce charges premium prices to manage. "
            "Autonomous AI SDRs, AI-powered CRM auto-population, and intelligent pipeline management "
            "reduce the need for complex CRM platforms. The per-seat SaaS model faces existential pressure."
        ),
    ),
    "ZIP": TickerThesis(
        ticker="ZIP",
        category="AI Disruption - Recruitment",
        thesis=(
            "LLM-powered recruiting tools are displacing traditional job boards. AI can write job descriptions, "
            "screen resumes, and conduct initial interviews. ZipRecruiter's matching algorithm becomes table "
            "stakes as every platform gains AI-powered candidate matching."
        ),
    ),
    "LYFT": TickerThesis(
        ticker="LYFT",
        category="AI Disruption - Rideshare/Autonomy",
        thesis=(
            "Lyft has no autonomous vehicle program. As Waymo and Tesla robotaxis expand, Lyft's driver-dependent "
            "model faces margin compression or obsolescence. Unlike Uber, Lyft has no diversified revenue "
            "streams (no delivery, no freight) to cushion the transition."
        ),
    ),
    "UBER": TickerThesis(
        ticker="UBER",
        category="AI Disruption - Rideshare/Delivery Platform",
        thesis=(
            "Autonomous vehicle competition threatens Uber's core rideshare business. While Uber has delivery "
            "and freight diversification, its rideshare margins depend on human drivers whose cost advantage "
            "over robotaxis is temporary. Uber's platform play depends on being the marketplace for autonomous "
            "fleets — but fleet operators may prefer direct-to-consumer."
        ),
    ),
}
