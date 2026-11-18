import json

import pytest
from conftest import fixture

pytestmark = pytest.mark.anyio

TOOLS = {
    "k45_brands",
    "k45_models",
    "k45_trims",
    "k45_price_estimate",
    "k45_cities",
    "k45_cars",
    "k45_car",
    "k45_inspection",
    "k45_deals",
    "k45_new_car_prices",
}
V1 = "/api/v1"


@pytest.fixture
def site(api):
    api[f"{V1}/brands/all/"] = fixture("brands.json")
    api[f"{V1}/models/"] = fixture("models.json")
    api[f"{V1}/city/"] = fixture("cities.json")
    return api


async def test_all_tools_are_read_only_and_described(client):
    tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.title and t.description.splitlines()[0].endswith("."), t.name


async def test_brands_filter_by_persian_or_english_name(client, site):
    r = (await client.call_tool("k45_brands", {"query": "پژو"})).structured_content
    assert [b["slug"] for b in r["brands"]] == ["peugeot"]
    r = (await client.call_tool("k45_brands", {"query": "kia"})).structured_content
    assert r["total"] == 1 and r["brands"][0]["title_en"] == "Kia"


async def test_models_resolves_brand_and_trims_fields(client, site):
    r = (await client.call_tool("k45_models", {"brand": "Peugeot"})).structured_content
    assert r["brand"]["id"] == 100 and r["models"][0].keys() == {"id", "title", "title_en", "slug"}
    assert site.calls[-1].url.params["brand_id"] == "100"


async def test_trims_lists_years_per_trim(client, api):
    api[f"{V1}/trims/"] = fixture("trims.json")
    api[f"{V1}/years/"] = fixture("years.json")
    r = (await client.call_tool("k45_trims", {"model_id": 517})).structured_content
    assert r["trims"][0]["years"][:2] == ["1401", "1400"] and len(r["trims"]) == 2


async def test_price_estimate_posts_resolved_trimyear_with_km(client, api):
    api[f"{V1}/years/"] = [{"id": 10, "title": "1396"}]
    api[f"{V1}/trimyears/"] = fixture("trimyears.json")
    api[f"{V1}/carprice/public/estimated_price/"] = {
        "source": "AI45",
        "market_price": {"min": 1, "price": 2, "max": 3},
        "k45_price": {"min": 0, "price": 1, "max": 2},
    }
    r = (await client.call_tool("k45_price_estimate", {"trim_id": 1849, "year": 1396, "km": 150000})).structured_content
    post = api.calls[-1]
    assert post.method == "POST" and json.loads(post.content) == {
        "source": "carprice",
        "trimyear_id": 698,
        "mileage": "150000",
        "defects": [],
    }
    assert post.headers["origin"] == "https://khodro45.com"
    assert r["market_price_toman"]["price"] == 2 and r["khodro45_offer_toman"]["price"] == 1 and r["trim"] == "EF7"


async def test_price_estimate_rejects_unknown_year(client, api):
    api[f"{V1}/years/"] = [{"id": 10, "title": "1396"}]
    r = await client.call_tool("k45_price_estimate", {"trim_id": 1849, "year": 1400})
    assert r.is_error is True


async def test_cars_maps_filters_and_trims_cards(client, site, api):
    api["/api/v2/car_listing/"] = fixture("listing.json")
    r = (
        await client.call_tool(
            "k45_cars",
            {
                "brand": "پژو",
                "model": "206",
                "city": "Tehran",
                "max_price": 2000000000,
                "min_year": 1395,
                "automatic": True,
                "sort": "cheapest",
                "limit": 2,
            },
        )
    ).structured_content
    q = api.calls[-1].url.params
    assert "brand_ids" not in q and q["city_ids"] == "1" and q["price__lte"] == "2000000000"
    assert q["year__gte"] == "1395" and q["is_automat"] == "true" and q["ordering"] == "price" and q["limit"] == "2"
    assert q["model_ids"] == "595" and r["total"] == 656
    c = r["cars"][0]
    assert c["price_toman"] > 0 and c["url"].startswith("https://khodro45.com/buy-car/") and "views" not in c


async def test_cars_model_needs_brand(client):
    r = await client.call_tool("k45_cars", {"model": "206"})
    assert r.is_error is True


async def test_car_detail_maps_color_and_drops_agent(client, api):
    api[f"{V1}/car_listing/71MEJ8/"] = fixture("detail.json")
    api[f"{V1}/portfolio/colors/"] = fixture("colors.json")
    r = (await client.call_tool("k45_car", {"slug": "71mej8"})).structured_content
    assert r["color"] == "سفید" and r["price_toman"] == 3081500000 and r["document_dong"] == "6"
    assert "agent" not in r and "09981454523" not in json.dumps(r)


async def test_inspection_reports_scores_defects_and_positives(client, api):
    api[f"{V1}/car_listing/71MEJ8/qc-public/"] = fixture("qc.json")
    r = (await client.call_tool("k45_inspection", {"slug": "71MEJ8"})).structured_content
    body = next(s for s in r["sections"] if s["score"] == 4.9)
    assert body["findings"] and any(f.get("defects") for f in body["findings"])
    assert r["positive_points"] == ["گارد سپر جلو"]


async def test_inspection_overall_score_is_mean_cut_to_one_decimal(client, api):
    sec = lambda slug, rate: {"name": slug, "slug": slug, "rate": rate, "components": [{"name": "x", "defects": []}]}  # noqa: E731
    api[f"{V1}/car_listing/ABCDEF/qc-public/"] = [
        sec("a", 4.8),
        sec("b", 5),
        sec("c", 5),
        sec("d", 5),
        sec("e", 5),
        {"name": "p", "slug": "inspection_positive_points", "rate": None, "components": []},
    ]
    r = (await client.call_tool("k45_inspection", {"slug": "ABCDEF"})).structured_content
    assert r["overall_score"] == 4.9  # mean 4.96 is cut, not rounded to 5


async def test_price_estimate_accepts_gregorian_years(client, api):
    api[f"{V1}/years/"] = [{"id": 10, "title": "2016"}]
    api[f"{V1}/trimyears/"] = fixture("trimyears.json")
    api[f"{V1}/carprice/public/estimated_price/"] = {
        "market_price": {"min": 1, "price": 2, "max": 3},
        "k45_price": {"min": 0, "price": 1, "max": 2},
    }
    r = await client.call_tool("k45_price_estimate", {"trim_id": 850, "year": 2016})
    assert r.is_error is False and r.structured_content["year"] == 2016


async def test_names_accept_persian_digits_and_zwnj():
    from khodro45_mcp.khodro45 import _norm

    assert _norm(" ۲۰۷\u200cSD ") == "207 sd" and _norm("١٢٣") == "123"


async def test_car_detail_hides_phone_numbers_in_seller_note(client, api):
    d = fixture("detail.json")
    d["car_specifications"]["additional_information"] = (
        "تماس: ۰۹۱۲ ۳۴۵ ۶۷۸۹ یا 09123456789 یا +98 912 345 6789، بیمه ۱۴۰۶/۰۳/۲۸"
    )
    api[f"{V1}/car_listing/71MEJ8/"] = d
    api[f"{V1}/portfolio/colors/"] = fixture("colors.json")
    note = (await client.call_tool("k45_car", {"slug": "71MEJ8"})).structured_content["seller_note"]
    assert "[number hidden]" in note and "345" not in note and "۱۴۰۶/۰۳/۲۸" in note


async def test_deals_lists_sold_cars_newest_first(client, site, api):
    api["/api/v1/auction-hall/sales/"] = {
        "count": 1,
        "results": [
            {
                "sold_at": "2026-11-17T19:48:41+03:30",
                "price": 5562000000,
                "car": {
                    "trim": {"title": "2.0", "model": {"title": "سراتو", "brand": {"title": "کیا"}}},
                    "year": {"title": "1397"},
                    "option": {"title": "استاندارد"},
                },
                "location": {"title": "تهران"},
                "mileage": 88009,
                "quality": {"score": 5, "defect_count": 18},
            }
        ],
    }
    r = (await client.call_tool("k45_deals", {"brand": "Peugeot", "city": "tehran"})).structured_content
    q = api.calls[-1].url.params
    assert q["group"] == "buy" and q["ordering"] == "-sold_at" and q["brand_ids"] == "100" and q["city_ids"] == "1"
    assert r["deals"][0]["price_toman"] == 5562000000 and r["deals"][0]["km"] == 88009 and r["total"] == 1


async def test_new_car_prices_index_and_brand(client, site, api):
    api["/api/v1/ai/pricing45/summary/"] = {
        "date": "2026-11-18",
        "comparison_date": "2026-11-11",
        "items": [
            {
                "series": "new",
                "tag": "all",
                "name": " شاخص",
                "weighted_average_index": 3700953897.5,
                "weighted_average_change_percent": 1.1628,
            },
            {
                "series": "new",
                "tag": "x",
                "name": "صفر",
                "weighted_average_index": 0.0,
                "weighted_average_change_percent": None,
            },
        ],
    }
    r = (await client.call_tool("k45_new_car_prices", {})).structured_content
    assert r["indexes"] == [
        {"series": "new", "group": "all", "name": "شاخص", "index_toman": 3700953898, "change_7d_pct": 1.16}
    ]
    item = lambda mid, mkt: {  # noqa: E731
        "trimyear": {
            "trim": {"title": "TU5", "model": {"id": mid, "title": str(mid)}},
            "year": {"title": "1405"},
            "option": {"title": "o"},
        },
        "prices": {
            "market": {"price": mkt, "change_pct": 3.146},
            "company": {"price": None, "change_pct": None},
            "agency": {},
        },
    }
    api["/api/v1/pricing/dailycars/"] = {
        "count": 1,
        "results": [{"models": [{"items": [item(597, 2950000000), item(1, 5)]}]}],
    }
    r = (await client.call_tool("k45_new_car_prices", {"brand": "پژو"})).structured_content
    assert r["total"] == 2 and r["cars"][0]["market_toman"] == 2950000000 and r["cars"][0]["market_change_pct"] == 3.15
    assert "dealer_toman" not in r["cars"][0]  # null prices are dropped
