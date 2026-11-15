"""One lookalike is not a range: a matched product sets a line's price only when at least two were kept."""
from backend import tighten


def row(low, high, url="https://example.org/g"):
    return {"price": low, "price_high": high, "source": {"url": url, "title": "t"}}


def test_a_single_lookalike_stays_on_the_line_but_the_cost_guide_prices_it():
    guide, fit = row(250.0, 2500.0), row(100.0, 250.0, "https://example.org/f")
    one = {"low": 199.0, "high": 199.0, "candidates": [{"make": "M", "price": 199.0, "url": "https://shop.example/a"}]}
    got = tighten.price_of(guide, one, fit)
    assert (got["price_low"], got["price_high"]) == (250.0, 2500.0) and got["price_basis"] == tighten.GUIDE and got["fitting_low"] is None


def test_two_lookalikes_price_the_line_with_their_fitting():
    guide, fit = row(250.0, 2500.0), row(100.0, 250.0, "https://example.org/f")
    two = {"low": 199.0, "high": 289.0, "candidates": [{"make": "M", "price": 199.0, "url": "https://shop.example/a"}, {"make": "N", "price": 289.0, "url": "https://shop.example/b"}]}
    got = tighten.price_of(guide, two, fit)
    assert (got["price_low"], got["price_high"]) == (299.0, 539.0) and got["price_basis"] == tighten.MATCH_FITTED


def test_a_single_lookalike_does_not_beat_a_price_for_what_was_seen():
    one = {"low": 1000.0, "high": 1000.0, "candidates": [{"make": "M", "price": 1000.0, "url": "https://shop.example/a"}]}
    got = tighten.price_of(row(600.0, 2000.0), one, None, row(900.0, 1400.0, "https://example.org/s"))
    assert (got["price_low"], got["price_high"]) == (900.0, 1400.0) and got["price_basis"] == tighten.SEEN
