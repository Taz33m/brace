"""What the runs cost, worked out from the tokens they recorded. Unknown is null, never zero."""
from backend import run_cost


def test_cost_is_tokens_times_the_published_price():
    assert run_cost.usd("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 100_000}) == 6.0
    assert run_cost.usd("claude-haiku-5-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == 0.6


def test_an_unknown_model_or_missing_usage_is_null_not_zero():
    assert run_cost.usd("some-other-model", {"input_tokens": 5, "output_tokens": 5}) is None
    assert run_cost.usd("claude-opus-5-5", None) is None and run_cost.usd(None, {"input_tokens": 5}) is None
    assert run_cost.usd("claude-opus-5-5", {}) is None                                         # a run that recorded no tokens did not cost nothing; it is not known


def test_total_leaves_out_runs_without_a_cost_and_is_null_when_none_have_one():
    assert run_cost.total([{"model": "claude-opus-5-5", "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}, {"model": "x", "usage": {}}, None]) == 4.0
    assert run_cost.total([{"model": "x", "usage": {}}]) is None and run_cost.total([]) is None
