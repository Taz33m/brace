"""The flood research agent: what it records is checked against the page, and only a confirmed fix is saved as confirmed."""
import json
from types import SimpleNamespace as NS

from backend import flood, flood_agent

PAGE = "<html><style>p{}</style><body><p>The 4&nbsp;ft model costs $ 50 per linear foot, before shipping.</p><p>It fills in a few hours.</p></body></html>"
FIX = {"name": "Water-filled barrier, 4 ft", "type": "quick", "price": 50, "price_high": None, "price_unit": "per linear foot", "height": 4, "height_unit": "ft",
       "height_quote": "The 4 ft model costs $50 per linear foot, before shipping.", "height_source_url": None, "crew_hours_per_100ft": None, "bags_per_person_hour": None,
       "weeks": None, "time_text": "fills in a few hours", "source_title": "Maker", "source_url": "https://example.org/price", "quote": "The 4 ft model costs $50 per linear foot, before shipping."}


def _text(markup):
    import html, re
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", re.sub(r"(?is)<(script|style|noscript)\\b.*?</\\1>", " ", markup)))


def test_a_fix_is_confirmed_only_when_the_page_holds_both_the_price_and_the_sentence():
    fix = flood_agent._clean(FIX)
    assert flood_agent.confirm(fix, _text(PAGE)) == (True, "the price and the sentence are on the page")
    assert flood_agent.confirm({**fix, "price": 5.0}, _text(PAGE))[1] == "the price is not on the page"                 # $5 must not match inside $50
    assert flood_agent.confirm({**fix, "source": {**fix["source"], "quote": "Our barriers are the cheapest in Texas at this price."}}, _text(PAGE))[1] == "the price is on the page but the sentence is not"
    assert flood_agent.confirm(fix, None) == (False, "the page could not be read")


def test_only_public_web_pages_are_fetched():
    assert not flood_agent._public("http://localhost:8011/api") and not flood_agent._public("http://127.0.0.1/") and not flood_agent._public("file:///etc/passwd") and not flood_agent._public("http://10.0.0.5/x")


def test_a_record_without_a_price_a_page_or_a_sentence_is_refused():
    assert flood_agent._clean({**FIX, "price": 0}) is None and flood_agent._clean({**FIX, "source_url": "see the brochure"}) is None and flood_agent._clean({**FIX, "quote": " "}) is None
    assert flood_agent._clean({**FIX, "height": None, "weeks": -2})["weeks"] is None and flood_agent._clean({**FIX, "height": None})["holds_ft"] is None
    assert flood_agent._clean({**FIX, "height": 30, "height_unit": "in"})["holds_ft"] == 2.5 and flood_agent._clean({**FIX, "price_high": 40})["price_high"] is None       # a top end below the low end is not a range


def test_both_ends_of_a_price_range_must_be_on_the_page_and_a_height_its_page_does_not_bear_out_is_dropped():
    page = _text("<p>Water-filled barriers run $15-40 per foot. The tube stands 30 inches high.</p>")
    fix = flood_agent._clean({**FIX, "price": 15, "price_high": 40, "quote": "Water-filled barriers run $15-40 per foot.", "height": 30, "height_unit": "in", "height_quote": "The tube stands 30 inches high."})
    assert flood_agent.confirm(fix, page)[0] and flood_agent.confirm({**fix, "price_high": 90.0}, page) == (False, "the price is not on the page")
    assert flood_agent.confirm_height(fix, page) and not flood_agent.confirm_height({**fix, "height": {**fix["height"], "quote": "The tube stands 48 inches high."}}, page)
    assert not flood_agent.confirm_height({**fix, "height": {**fix["height"], "value": 3.0}}, page)                       # the figure must be in the sentence


class _Client:
    """Stands in for the API: one turn that searches and records two fixes, then one that stops."""
    def __init__(self):
        turn1 = NS(stop_reason="tool_use", usage=NS(input_tokens=100, output_tokens=20), content=[
            NS(type="server_tool_use", name="web_search", input={"query": "water-filled flood barrier price per foot"}),
            NS(type="tool_use", name="record_fix", id="a", input=FIX),
            NS(type="tool_use", name="record_fix", id="b", input={**FIX, "name": "Made-up wall", "price": 7, "source_url": "https://example.org/other"})])
        turn2 = NS(stop_reason="end_turn", usage=NS(input_tokens=50, output_tokens=5), content=[NS(type="text", text="Recorded two.")])
        self.turns, self.sent = [turn1, turn2], []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.sent.append(kw)
        return self.turns.pop(0)


def test_a_run_saves_each_fix_with_whether_its_page_confirmed_it(tmp_path, monkeypatch):
    monkeypatch.setattr(flood, "RESEARCH", tmp_path / "flood" / "research.json")
    client = _Client()
    run = flood_agent.research(client=client, fetch=lambda url: _text(PAGE) if url.endswith("/price") else None)
    assert run["stop"] == "end_turn" and [f["checked"] for f in run["fixes"]] == [True, False] and [f["holds_ft"] for f in run["fixes"]] == [4.0, None] and run["usage"] == {"input_tokens": 150, "output_tokens": 25}
    assert [s["kind"] for s in run["steps"]] == ["search", "found", "found"] and run["steps"][0]["text"] == "water-filled flood barrier price per foot"
    assert client.sent[0]["tools"][0]["type"] == "web_search_20260209" and client.sent[1]["messages"][2]["content"][1]["content"].startswith("Recorded. Check of the page: the page could not be read")
    saved = json.loads((tmp_path / "flood" / "research.json").read_text())
    assert len(saved["fixes"]) == 2
    cat = flood.catalogue()                                                                                              # and the plan takes only the confirmed one
    assert [m["name"] for m in cat["measures"]] == ["Water-filled barrier, 4 ft"] and cat["by"] == "agent"
