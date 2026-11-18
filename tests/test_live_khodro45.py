import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_live_catalog_chain_and_estimate(client):
    b = (await client.call_tool("k45_brands", {"query": "سمند"})).structured_content
    assert b["brands"][0]["title_en"] == "Samand"
    m = (await client.call_tool("k45_models", {"brand": "Samand"})).structured_content
    t = (await client.call_tool("k45_trims", {"model_id": m["models"][0]["id"]})).structured_content
    trim = t["trims"][0]
    e = (
        await client.call_tool(
            "k45_price_estimate", {"trim_id": trim["id"], "year": int(trim["years"][0]), "km": 100000}
        )
    ).structured_content
    mp = e["market_price_toman"]
    assert 0 < mp["min"] <= mp["price"] <= mp["max"] and e["khodro45_offer_toman"]["price"] > 0


async def test_live_cars_car_and_inspection(client):
    r = (
        await client.call_tool("k45_cars", {"brand": "پژو", "city": "تهران", "max_price": 3000000000, "limit": 3})
    ).structured_content
    assert r["total"] > 0 and r["cars"]
    assert all(c["brand_en"] == "Peugeot" and c["city"] == "تهران" for c in r["cars"])
    slug = r["cars"][0]["slug"]
    d = (await client.call_tool("k45_car", {"slug": slug})).structured_content
    assert d["slug"] == slug and d["price_toman"] == r["cars"][0]["price_toman"]
    q = (await client.call_tool("k45_inspection", {"slug": slug})).structured_content
    assert q["slug"] == slug and "sections" in q


async def test_live_cities(client):
    c = (await client.call_tool("k45_cities", {"query": "tehran"})).structured_content
    assert any(x["title"] == "تهران" for x in c["cities"])


async def test_live_deals_and_new_car_prices(client):
    d = (await client.call_tool("k45_deals", {"brand": "پژو", "model": "207", "limit": 3})).structured_content
    assert d["total"] > 0 and all(x["model"] == "207" and x["price_toman"] > 0 for x in d["deals"])
    idx = (await client.call_tool("k45_new_car_prices", {})).structured_content
    assert any(i["series"] == "used" and i["index_toman"] > 0 for i in idx["indexes"])
    p = (await client.call_tool("k45_new_car_prices", {"brand": "audi"})).structured_content
    assert p["total"] > 0 and p["cars"][0]["market_toman"] > 0


async def test_live_inspection_overall_and_gregorian_estimate(client):
    q = (await client.call_tool("k45_inspection", {"slug": "UUBF4K"})).structured_content
    assert 0 < q["overall_score"] <= 5
    m = (await client.call_tool("k45_models", {"brand": "هیوندای"})).structured_content
    t = (
        await client.call_tool("k45_trims", {"model_id": next(x["id"] for x in m["models"] if x["title"] == "النترا")})
    ).structured_content
    trim = next(x for x in t["trims"] if x["years"][0].startswith("20"))
    e = await client.call_tool("k45_price_estimate", {"trim_id": trim["id"], "year": int(trim["years"][0])})
    assert e.is_error is False
