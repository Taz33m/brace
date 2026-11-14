from backend import portfolio


def comp(date, price, status, *pids, allocated=None):
    entities = [{"propertyId": p, **({"allocatedPrice": allocated[i]} if allocated else {})} for i, p in enumerate(pids)]
    return {"soldDate": f"{date}T12:00:00-05:00", "soldForPrice": price, "salePriceStatus": status, "entities": entities}


def test_last_sale_takes_the_most_recent_priced_sale_and_keeps_its_basis():
    sales = portfolio.last_sales([
        comp("2012-03-01", 4_000_000, 3, 10),
        comp("2021-06-15", 9_500_000, 5, 10),
        comp("2023-01-10", None, 0, 10),            # sold again, price not disclosed: not a price
    ])
    assert sales["10"] == {"price": 9_500_000, "basis": "FullValue", "portfolio": False, "date": "2021-06-15"}


def test_portfolio_sale_uses_the_allocated_share_and_says_so():
    sales = portfolio.last_sales([comp("2020-05-05", 60_000_000, 3, 20, 21, 22, allocated=[30_000_000, 20_000_000, None])])
    assert sales["20"] == {"price": 30_000_000, "basis": "Allocated", "portfolio": True, "date": "2020-05-05"}
    assert sales["21"]["price"] == 20_000_000
    assert "22" not in sales                        # no allocation for this one: the portfolio total is never used


def test_sales_without_price_or_date_are_ignored():
    assert portfolio.last_sales([comp("2019-01-01", None, 0, 30), {"soldForPrice": 5, "entities": [{"propertyId": 31}]}]) == {}
