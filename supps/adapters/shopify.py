"""Shopify storefronts: the public /products.json catalogue lists every product and variant."""

import re

from ..model import Offer, Variant, group_variants
from ..normalize import (
    FLAVOURLESS,
    SWEETENER_FREE,
    TESTED,
    classify,
    clean,
    flavour_of,
    is_creapure,
    is_native,
    net_weight,
    parse_grams,
    protein_per_100g,
    whey_type,
)

FLAVOUR_OPTION = re.compile(r"sabor|saveur|go[uû]t|flav|ar[oô]me|aroma|geschmack", re.I)


def collect(src: dict, fetch, now: str) -> list[Offer]:
    base = src["base"].rstrip("/")
    offers = []
    for page in range(1, src.get("max_pages", 12) + 1):
        products = fetch.json(f"{base}/products.json?limit=250&page={page}").get("products", [])
        if not products:
            break
        for p in products:
            offers += _product(src, base, p, now, fetch)
    return offers


def _page_text(fetch, url: str) -> str:
    """Rendered product page as text; nutrition tables often live in theme blocks, not body_html."""
    try:
        return clean(fetch.text(url))
    except Exception:  # noqa: BLE001 - enrichment is best effort
        return ""


def _product(src: dict, base: str, p: dict, now: str, fetch=None) -> list[Offer]:
    title = p["title"].strip()
    tags = p.get("tags") or []
    extra = " ".join([p.get("product_type") or "", *(tags if isinstance(tags, list) else [tags])])
    kind = classify(title, extra)
    if not kind:
        return []
    body = clean(p.get("body_html"))
    option_names = [o.get("name", "").lower() for o in p.get("options", [])]
    variants = []
    for v in p.get("variants", []):
        labels = [v.get("option1"), v.get("option2"), v.get("option3")]
        named = list(zip(labels, option_names + ["", "", ""]))
        size_label = " ".join(x for x, n in named if x and not FLAVOUR_OPTION.match(n))
        grams = parse_grams(size_label, v.get("title"), title)
        if grams is None and v.get("grams") and len(p.get("variants", [])) == 1 and kind == "creatine":
            grams = None  # shipping weight includes the tub: never use it
        flavour = flavour_of(*[x for x, n in zip(labels, option_names + ["", "", ""]) if x and x != size_label])
        variants.append(
            Variant(
                label=flavour or v.get("title") or "",
                grams=grams,
                price=float(v["price"]),
                list_price=float(v["compare_at_price"]) if v.get("compare_at_price") else None,
                available=v.get("available"),
            )
        )
    url = f"{src.get('product_base', base)}/products/{p['handle']}"
    page = ""
    needs_size = any(v.grams is None for v in variants) and len(variants) <= 3
    protein = protein_per_100g(body) if kind == "whey" else None
    if fetch is not None and src.get("pages", True) and ((kind == "whey" and protein is None) or needs_size):
        page = _page_text(fetch, url)
        if kind == "whey" and protein is None:
            protein = protein_per_100g(page)
        if needs_size:
            g = net_weight(body) or net_weight(page)
            for v in variants:
                v.grams = v.grams or g
    out = []
    for grams, s in group_variants(variants).items():
        if s["price"] / grams * 1000 < 5:  # a sample or a bundle line; not a real per-kg price
            continue
        out.append(
            Offer(
                shop=src["id"],
                market=src["market"],
                kind=kind,
                product=title,
                url=url,
                grams=grams,
                price=s["price"],
                list_price=s["list_price"],
                available=s["available"],
                flavours=s["flavours"],
                brand=(p.get("vendor") or "").strip() or None,
                creapure=is_creapure(title),
                whey_type=whey_type(title) if kind == "whey" else None,
                native=kind == "whey" and is_native(title),
                protein_100g=protein,
                unflavoured=any(FLAVOURLESS.search(lbl) for lbl in s["labels"]) or bool(FLAVOURLESS.search(title)),
                sweetener_free=bool(SWEETENER_FREE.search(title + " " + body[:600])),
                tested=bool(TESTED.search(body + page)),
                method="feed",
                captured_at=now,
            )
        )
    return out
