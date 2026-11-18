"""Khodro45 tools: brands, models, trims, the public price estimate, used-car listings and inspection reports."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import SITE, ApiError, fetch
from .registry import tool

Slug = Annotated[
    str,
    Field(
        description="Listing `slug` from k45_cars (6 letters/digits, e.g. '71MEJ8').", pattern=r"^[0-9A-Za-z]{4,12}$"
    ),
]
SORTS = {
    "newest": "-created_time",
    "cheapest": "price",
    "priciest": "-price",
    "lowest_km": "klm",
    "newest_year": "-year",
}


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PHONE = re.compile(
    r"(?<![\d۰-۹])(?:\+?98|0098|0)?[\s-]?9(?:[\s-]?[\d۰-۹]){9}(?![\d۰-۹])|(?<![\d۰-۹])0(?:[\s-]?[\d۰-۹]){10}(?![\d۰-۹])"
)


def _norm(s: str) -> str:
    """Lowercase, ASCII digits, Arabic letters to Persian, ZWNJ to a space."""
    return s.strip().lower().translate(_DIGITS).replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک")


def _scrub(s: str | None) -> str | None:
    """Seller text is free-form: hide anything that looks like a phone number."""
    return _PHONE.sub("[number hidden]", s) if s else s


async def _brand(query: str) -> dict[str, Any]:
    """Find a brand by Persian or English name, slug or id."""
    rows = await fetch("/v1/brands/all/")
    q = _norm(query)
    for r in rows:
        if q in (_norm(r["title"]), _norm(r["title_en"]), r["seo_slug"], str(r["id"])):
            return r
    hits = [r for r in rows if q in _norm(r["title"]) or q in _norm(r["title_en"])]
    if len(hits) == 1:
        return hits[0]
    raise ApiError(f"Unknown brand {query!r}. Look it up with k45_brands.")


async def _model(brand: dict[str, Any], query: str) -> dict[str, Any]:
    """Find one model of a brand by name, slug or id."""
    rows = await fetch("/v1/models/", {"brand_id": brand["id"]})
    q = _norm(query)
    for r in rows:
        if q in (_norm(r["title"]), _norm(r["title_en"]), r["seo_slug"], str(r["id"])):
            return r
    hits = [r for r in rows if q in _norm(r["title"]) or q in _norm(r["title_en"])]
    if len(hits) == 1:
        return hits[0]
    raise ApiError(f"Unknown model {query!r} for {brand['title_en']}. Look it up with k45_models.")


async def _city_id(query: str) -> int:
    rows = await fetch("/v1/city/")
    q = _norm(query)
    for r in rows:
        if q in (_norm(r["title"]), _norm(r["title_en"]), str(r["id"])):
            return r["id"]
    raise ApiError(f"Unknown city {query!r}. Look it up with k45_cities.")


def _card(c: dict[str, Any]) -> dict[str, Any]:
    """One listing card from the list API, trimmed."""
    p, s = c["car_properties"], c["car_specifications"]
    return {
        "slug": c["slug"],
        "brand": p["brand"]["title"],
        "brand_en": p["brand"]["title_en"],
        "model": p["model"]["title"],
        "trim": p.get("trim"),
        "option": p.get("option"),
        "year": p["year"],
        "km": s.get("klm"),
        "city": c["city"]["title"],
        "price_toman": c["final_price"],
        "car_price_toman": c["price"],
        "installments": c.get("has_installment"),
        "immediate_delivery": c.get("immediate_delivery"),
        "tags": [t["title"] for t in c.get("fmp_tags") or []],
        "image": (c.get("image") or {}).get("url"),
        "url": f"{SITE}/buy-car/{p['model']['seo_slug']}/{c['city']['title_en'].lower()}/cla-{c['slug'].lower()}/",
    }


@tool("Used-car brands")
async def k45_brands(
    query: Annotated[
        str | None, Field(description="Part of a brand name, Persian or English, e.g. 'پژو' or 'kia'.")
    ] = None,
) -> dict[str, Any]:
    """List the car brands Khodro45 knows, optionally filtered by name.

    Returns id, Persian and English title and slug. Pass a brand to k45_models, or its name to k45_cars.
    """
    rows = await fetch("/v1/brands/all/")
    q = _norm(query) if query else None
    brands = [
        {"id": r["id"], "title": r["title"], "title_en": r["title_en"], "slug": r["seo_slug"]}
        for r in rows
        if not q or q in _norm(r["title"]) or q in _norm(r["title_en"]) or q in r["seo_slug"]
    ]
    return {"total": len(brands), "brands": brands}


@tool("Car models of a brand")
async def k45_models(
    brand: Annotated[
        str, Field(description="Brand name (Persian or English), slug or id from k45_brands.", min_length=1)
    ],
) -> dict[str, Any]:
    """List the models of one brand, e.g. Peugeot -> 206, 207, Pars.

    Returns each model's id and slug. Use the id with k45_trims, or the name with k45_cars.
    """
    b = await _brand(brand)
    rows = await fetch("/v1/models/", {"brand_id": b["id"]})
    return {
        "brand": {"id": b["id"], "title": b["title"], "title_en": b["title_en"]},
        "models": [
            {"id": m["id"], "title": m["title"], "title_en": m["title_en"], "slug": m["seo_slug"]} for m in rows
        ],
    }


@tool("Trims and years of a model")
async def k45_trims(
    model_id: Annotated[int, Field(description="Model `id` from k45_models.", ge=1)],
) -> dict[str, Any]:
    """List the trims (types) of a model and the model years each one was built.

    Pass a trim `id` and one of its years to k45_price_estimate.
    """
    trims = await fetch("/v1/trims/", {"model_id": model_id})
    out = []
    for t in trims[:25]:
        years = await fetch("/v1/years/", {"trim_id": t["id"]})
        out.append(
            {"id": t["id"], "title": t["title"], "title_en": t["title_en"], "years": [y["title"] for y in years]}
        )
    return {"model_id": model_id, "trims": out}


@tool("Used-car price estimate")
async def k45_price_estimate(
    trim_id: Annotated[int, Field(description="Trim `id` from k45_trims.", ge=1)],
    year: Annotated[
        int,
        Field(
            description="Model year as k45_trims lists it: Persian (1400) or Gregorian (2016) for imported cars.",
            ge=1300,
            le=2100,
        ),
    ],
    km: Annotated[
        int | None, Field(description="Mileage in kilometers. Omit for an estimate without mileage.", ge=0, le=2000000)
    ] = None,
    option_id: Annotated[
        int | None, Field(description="Option `id` when the trim-year has several (listed in `options`).")
    ] = None,
) -> dict[str, Any]:
    """Estimate the used-car price of a trim and year, the same public estimate khodro45.com/carprice shows.

    Returns the market price range and the price Khodro45 itself would pay, in Toman, for a car with no body or
    technical defects. No login or phone number needed.
    """
    years = await fetch("/v1/years/", {"trim_id": trim_id})
    year_id = next((y["id"] for y in years if y["title"] == str(year)), None)
    if year_id is None:
        raise ApiError(f"Trim {trim_id} has no model year {year}. Available: {', '.join(y['title'] for y in years)}.")
    combos = await fetch("/v1/trimyears/", {"trim_id": trim_id, "year_id": year_id})
    chosen = next((c for c in combos if option_id is None or c["option"]["id"] == option_id), None)
    if chosen is None:
        raise ApiError(f"Unknown option_id {option_id}. Options: {[c['option'] for c in combos]}.")
    body: dict[str, Any] = {"source": "carprice", "trimyear_id": chosen["id"], "defects": []}
    if km is not None:
        body = {"source": "carprice", "trimyear_id": chosen["id"], "mileage": str(km), "defects": []}
    r = await fetch("/v1/carprice/public/estimated_price/", body=body)
    return {
        "trim": chosen["trim"]["title"],
        "year": year,
        "option": chosen["option"]["title"],
        "options": [c["option"] for c in combos] if len(combos) > 1 else None,
        "km": km,
        "market_price_toman": r.get("market_price"),
        "khodro45_offer_toman": r.get("k45_price"),
        "note": "Each price is {min, price, max} in Toman.",
    }


@tool("Cities with listings")
async def k45_cities(
    query: Annotated[str | None, Field(description="Part of a city name, Persian or English.")] = None,
) -> dict[str, Any]:
    """List the cities where Khodro45 sells cars, optionally filtered by name.

    Pass the Persian or English name as `city` to k45_cars.
    """
    rows = await fetch("/v1/city/")
    q = _norm(query) if query else None
    cities = [
        {
            "id": c["id"],
            "title": c["title"],
            "title_en": c["title_en"],
            "province": (c.get("province") or {}).get("title"),
        }
        for c in rows
        if not q or q in _norm(c["title"]) or q in _norm(c["title_en"])
    ]
    return {"total": len(cities), "cities": cities}


@tool("Search used cars for sale")
async def k45_cars(
    brand: Annotated[
        str | None, Field(description="Brand name (Persian or English) or slug, e.g. 'پژو' or 'peugeot'.")
    ] = None,
    model: Annotated[
        str | None, Field(description="Model name or slug within the brand, e.g. '207'. Needs `brand`.")
    ] = None,
    city: Annotated[
        str | None, Field(description="City name, Persian or English, e.g. 'تهران'. See k45_cities.")
    ] = None,
    min_price: Annotated[int | None, Field(description="Minimum price in Toman.", ge=0)] = None,
    max_price: Annotated[int | None, Field(description="Maximum price in Toman.", ge=0)] = None,
    min_year: Annotated[
        int | None, Field(description="Earliest model year, Persian, e.g. 1400.", ge=1300, le=1500)
    ] = None,
    max_year: Annotated[
        int | None, Field(description="Latest model year, Persian, e.g. 1404.", ge=1300, le=1500)
    ] = None,
    max_km: Annotated[int | None, Field(description="Maximum mileage in km.", ge=0)] = None,
    automatic: Annotated[bool | None, Field(description="True for automatic gearbox only.")] = None,
    installments: Annotated[bool | None, Field(description="True for cars that can be bought in installments.")] = None,
    sort: Annotated[
        Literal["newest", "cheapest", "priciest", "lowest_km", "newest_year"], Field(description="Order of results.")
    ] = "newest",
    limit: Annotated[int, Field(description="Results per page.", ge=1, le=30)] = 10,
    offset: Annotated[int, Field(description="Results to skip, for paging.", ge=0)] = 0,
) -> dict[str, Any]:
    """Search the used cars listed for sale on Khodro45 (inspected by the company).

    Returns cards with price in Toman (final price the site shows), year, km and city. Open one with k45_car.
    """
    if model and not brand:
        raise ApiError("`model` needs `brand`.")
    params: dict[str, Any] = {
        "limit": limit,
        "offset": offset or None,
        "ordering": SORTS[sort],
        "price__gte": min_price,
        "price__lte": max_price,
        "year__gte": min_year,
        "year__lte": max_year,
        "klm__lte": max_km,
        "is_automat": "true" if automatic else None,
        "has_installment_only": "true" if installments else None,
    }
    if brand:
        b = await _brand(brand)
        if model:  # brand_ids and model_ids are OR-ed by the API, so send only the narrower one
            params["model_ids"] = (await _model(b, model))["id"]
        else:
            params["brand_ids"] = b["id"]
    if city:
        params["city_ids"] = await _city_id(city)
    r = await fetch("/v2/car_listing/", params)
    return {"total": r["count"], "offset": offset, "cars": [_card(c) for c in r["results"]]}


@tool("Used-car listing details")
async def k45_car(slug: Slug) -> dict[str, Any]:
    """Get one used-car listing in full: price, specs, ownership and document facts, photos.

    The inspection report is a separate call, k45_inspection.
    """
    c = await fetch(f"/v1/car_listing/{slug.upper()}/")
    p, s = c["car_properties"], c["car_specifications"]
    colors = await fetch("/v1/portfolio/colors/")
    color = next((x["name"] for x in colors if x["slug"] == s.get("body_color")), None)
    doc = s.get("doc_type") or ""
    photos = [{"view": i["title"]["title"], "url": i["image"]["url"]} for i in c.get("car_images") or []]
    return {
        "slug": c["slug"],
        "code": c["identifier"],
        "active": c["active"],
        "brand": p["brand"],
        "model": p["model"],
        "trim": p.get("trim"),
        "option": p.get("option"),
        "year": p["year"],
        "city": c["city"],
        "price_toman": c["final_price"],
        "car_price_toman": c["price"],
        "service_cost_toman": c.get("service_cost"),
        "installments": c.get("has_installment"),
        "immediate_delivery": c.get("immediate_delivery"),
        "guaranteed": c.get("guaranteed"),
        "views": c.get("views"),
        "listed_at": c.get("created_time"),
        "tags": [t["title"] for t in c.get("fmp_tags") or []],
        "km": s.get("mileage"),
        "color": color,
        "gearbox": s.get("transmission"),
        "body_type": s.get("body_type"),
        "capacity": s.get("capacity"),
        "ownership": s.get("ownership_type"),
        "document_dong": doc.split("_")[0] if doc.endswith("_dong") else doc or None,
        "single_page_document": s.get("first_hand_document"),
        "has_insurance": s.get("insurance"),
        "insurance_expires": s.get("insurance_expire_date"),
        "technical_inspection": s.get("technical_inspection"),
        "warranty": s.get("guarantee"),
        "warranty_expires": s.get("guarantee_expire_date"),
        "warranty_km": s.get("guarantee_expire_mileage"),
        "spare_key": s.get("spare_key"),
        "fuel_card": s.get("fuel_card"),
        "engine_replaced": s.get("engine_replaced"),
        "chassis_replaced": s.get("chassis_replaced"),
        "cabin_replaced": s.get("cabin_replaced"),
        "bought_from_public_auction": s.get("bought_from_public_auction"),
        "sell_reason": s.get("sell_reason"),
        "seller_note": _scrub(s.get("additional_information")),
        "photo_count": len(photos),
        "photos": photos[:8],
    }


@tool("Used-car inspection report")
async def k45_inspection(slug: Slug) -> dict[str, Any]:
    """Get the public Khodro45 expert inspection report of a listing: section scores and every found defect.

    Sections cover body and tires, engine, electrical, suspension and air conditioning, each scored out of 5.
    """
    rep = await fetch(f"/v1/car_listing/{slug.upper()}/qc-public/")
    sections, positives = [], []
    for sec in rep:
        comps = sec.get("components") or []
        if sec["slug"] == "inspection_positive_points":
            positives = [c["name"] for c in comps if c.get("available")]
            continue
        if not comps and sec.get("rate") is None:
            continue
        found = []
        for c in comps:
            ds = [
                {"defect": d["defect"]["name"], "severity": d.get("severity_text"), "note": d.get("note") or None}
                for d in c.get("defects") or []
            ]
            if ds or c.get("description"):
                found.append({"part": c["name"], "defects": ds, "note": c.get("description") or None})
        sections.append(
            {
                "section": sec["name"],
                "score": sec.get("rate"),
                "checked": len(comps),
                "defective_parts": sum(1 for c in comps if c.get("defects")),
                "findings": found,
            }
        )
    rates = [round(s["score"] * 10) for s in sections if s["score"] is not None]
    # The page's "health score" is not in the API: it equals the mean of the section scores cut (not rounded) to 0.1.
    overall = sum(rates) // len(rates) / 10 if rates else None
    return {"slug": slug.upper(), "overall_score": overall, "sections": sections, "positive_points": positives}


@tool("Recent used-car deals")
async def k45_deals(
    brand: Annotated[str | None, Field(description="Brand name (Persian or English) or slug, e.g. 'پژو'.")] = None,
    model: Annotated[
        str | None, Field(description="Model name or slug within the brand, e.g. '207'. Needs `brand`.")
    ] = None,
    city: Annotated[str | None, Field(description="City name, Persian or English, e.g. 'تهران'.")] = None,
    limit: Annotated[int, Field(description="Results per page.", ge=1, le=30)] = 10,
    offset: Annotated[int, Field(description="Results to skip, for paging.", ge=0)] = 0,
) -> dict[str, Any]:
    """List used cars Khodro45 really sold lately (the public deals hall), newest first, with the sale price.

    Real transaction prices, a good check against k45_price_estimate. Quality is the inspection score out of 5.
    """
    if model and not brand:
        raise ApiError("`model` needs `brand`.")
    params: dict[str, Any] = {
        "group": "buy",
        "ordering": "-sold_at",
        "limit": limit,
        "offset": offset or None,
    }
    if brand:
        b = await _brand(brand)
        if model:
            params["model_ids"] = (await _model(b, model))["id"]
        else:
            params["brand_ids"] = b["id"]
    if city:
        params["city_ids"] = await _city_id(city)
    r = await fetch("/v1/auction-hall/sales/", params)
    deals = []
    for d in r["results"]:
        trim = d["car"]["trim"]
        deals.append(
            {
                "sold_at": d["sold_at"],
                "price_toman": d["price"],
                "brand": trim["model"]["brand"]["title"],
                "model": trim["model"]["title"],
                "trim": trim["title"],
                "year": d["car"]["year"]["title"],
                "option": d["car"]["option"]["title"],
                "km": d.get("mileage"),
                "city": (d.get("location") or {}).get("title"),
                "quality": (d.get("quality") or {}).get("score"),
                "defects": (d.get("quality") or {}).get("defect_count"),
            }
        )
    return {"total": r["count"], "offset": offset, "deals": deals}


@tool("New-car market prices")
async def k45_new_car_prices(
    brand: Annotated[
        str | None, Field(description="Brand name (Persian or English) or slug. Omit for the price indexes.")
    ] = None,
    model: Annotated[
        str | None, Field(description="Model name or slug within the brand, e.g. '207'. Needs `brand`.")
    ] = None,
) -> dict[str, Any]:
    """Get today's zero-km car prices (market, factory, dealer) of a brand, or the market price indexes.

    Without a brand: the Khodro45 new and used market indexes with their 7-day change. Prices are Toman.
    """
    if model and not brand:
        raise ApiError("`model` needs `brand`.")
    if not brand:
        r = await fetch("/v1/ai/pricing45/summary/")
        return {
            "date": r["date"],
            "compared_with": r["comparison_date"],
            "indexes": [
                {
                    "series": i["series"],
                    "group": i["tag"],
                    "name": i["name"].strip(),
                    "index_toman": round(i["weighted_average_index"]),
                    "change_7d_pct": round(i["weighted_average_change_percent"], 2)
                    if i["weighted_average_change_percent"] is not None
                    else None,
                }
                for i in r["items"]
                if i["weighted_average_index"]
            ],
        }
    b = await _brand(brand)
    mid = (await _model(b, model))["id"] if model else None
    r = await fetch("/v1/pricing/dailycars/", {"brand_ids": b["id"], "limit": 1})
    cars = []
    for grp in r["results"]:
        for m in grp["models"]:
            for it in m["items"]:
                ty = it["trimyear"]
                if mid and ty["trim"]["model"]["id"] != mid:
                    continue
                row = {
                    "model": ty["trim"]["model"]["title"],
                    "trim": ty["trim"]["title"],
                    "year": ty["year"]["title"],
                    "option": (ty.get("option") or {}).get("title"),
                }
                for key, name in (("market", "market"), ("company", "factory"), ("agency", "dealer")):
                    p = it["prices"].get(key) or {}
                    row[f"{name}_toman"] = p.get("price")
                    row[f"{name}_change_pct"] = round(p["change_pct"], 2) if p.get("change_pct") is not None else None
                cars.append(row)
    return {"brand": b["title"], "total": len(cars), "cars": cars}
