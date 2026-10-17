"""WooCommerce Store API (/wp-json/wc/store/v1): public catalogue with per-variation prices."""

from ..model import Offer, Variant, group_variants
from ..normalize import (
    FLAVOURLESS,
    SWEETENER_FREE,
    TESTED,
    classify,
    clean,
    is_creapure,
    is_native,
    parse_grams,
    protein_per_100g,
    whey_type,
)


def _price(prices: dict, key: str) -> float | None:
    raw = prices.get(key)
    if raw in (None, ""):
        return None
    return int(raw) / 10 ** int(prices.get("currency_minor_unit", 2))


def collect(src: dict, fetch, now: str) -> list[Offer]:
    api = src["base"].rstrip("/") + "/wp-json/wc/store/v1/products"
    seen, offers = set(), []
    for term in src.get("search", [""]):
        for page in range(1, 8):
            query = f"&search={term}" if term else ""
            batch = fetch.json(f"{api}?per_page=100&page={page}{query}")
            if not batch:
                break
            for p in batch:
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                offers += _product(src, api, fetch, p, now)
            if len(batch) < 100:
                break
    return offers


def _product(src, api, fetch, p, now) -> list[Offer]:
    title = clean(p["name"])
    cats = " ".join(c.get("name", "") for c in p.get("categories", []))
    kind = classify(title, cats)
    if not kind:
        return []
    text = clean(p.get("description", "")) + "\n" + clean(p.get("short_description", ""))
    variants = []
    if p.get("type") == "variable" and p.get("variations"):
        for var in p["variations"][:30]:
            label = " ".join(a.get("value", "") for a in var.get("attributes", []))
            try:
                d = fetch.json(f"{api}/{var['id']}")
            except Exception:
                continue
            variants.append(
                Variant(
                    label=label,
                    grams=parse_grams(label, title),
                    price=_price(d["prices"], "price") or 0,
                    list_price=_price(d["prices"], "regular_price"),
                    available=d.get("is_in_stock"),
                )
            )
    else:
        variants.append(
            Variant(
                label="",
                grams=parse_grams(title),
                price=_price(p["prices"], "price") or 0,
                list_price=_price(p["prices"], "regular_price"),
                available=p.get("is_in_stock"),
            )
        )
    out = []
    for grams, s in group_variants(variants).items():
        out.append(
            Offer(
                shop=src["id"],
                market=src["market"],
                kind=kind,
                product=title,
                url=p["permalink"],
                grams=grams,
                price=s["price"],
                list_price=s["list_price"],
                available=s["available"],
                flavours=s["flavours"],
                brand=src.get("brand"),
                creapure=is_creapure(title),
                whey_type=whey_type(title) if kind == "whey" else None,
                native=kind == "whey" and is_native(title),
                protein_100g=protein_per_100g(text) if kind == "whey" else None,
                unflavoured=any(FLAVOURLESS.search(lbl) for lbl in s["labels"]) or bool(FLAVOURLESS.search(title)),
                sweetener_free=bool(SWEETENER_FREE.search(title)),
                tested=bool(TESTED.search(text)),
                method="feed",
                captured_at=now,
            )
        )
    return out
