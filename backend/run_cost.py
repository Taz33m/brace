"""What a saved run cost, worked out from the model and the tokens the run recorded itself.

Prices are Anthropic's published rates in dollars per million tokens, input then output. Only tokens are counted:
the fee for each web search is not, and tokens read from a cache are billed here at the full input rate when the run
counted them as input. A run whose model is not listed, or that recorded no tokens, has no known cost: null, never zero.
"""
from __future__ import annotations

PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.00, 40.00),
}
HOW = "tokens the runs recorded, times the published price for the model; web search fees are not counted"


def usd(model: str | None, usage: dict | None) -> float | None:
    """Dollars for one run, or None when the model's price or the run's tokens are not known."""
    rate = PRICES.get(model or "")
    tokens_in, tokens_out = (usage or {}).get("input_tokens"), (usage or {}).get("output_tokens")
    if not rate or (not tokens_in and not tokens_out):
        return None
    return round(((tokens_in or 0) * rate[0] + (tokens_out or 0) * rate[1]) / 1_000_000, 2)


def total(runs: list[dict | None]) -> float | None:
    """Dollars for several saved runs, leaving out any whose cost is not known. None when none is."""
    known = [c for c in (usd(r.get("model"), r.get("usage")) for r in runs if r) if c is not None]
    return round(sum(known), 2) if known else None
