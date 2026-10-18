"""Shops whose product pages publish schema.org Product / ProductGroup JSON-LD (Myprotein, many
PrestaShop and Magento stores). Category pages give the product links; product pages give
variants, prices, availability and the nutrition table."""

import json
import re
from urllib.parse import urljoin, urlsplit

from ..cache import ENRICH
from ..model import Offer, Variant, group_variants
from ..normalize import (
    FLAVOURLESS,
    SWEETENER_FREE,
    TESTED,
    classify,
    clean,
    is_creapure,
    is_native,
    is_sample,
    parse_grams,
    protein_per_100g,
    whey_type,
)

BROWSER_FALLBACK = True
LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def _nodes(html: str):
    for block in LD.findall(html):
        block = re.sub(r"/\*\s*<!\[CDATA\[\s*\*/|/\*\s*\]\]>\s*\*/", "", block).strip()
        try:
            data = json.loads(block, strict=False)
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                if "@graph" in n:
                    stack += n["@graph"]
                yield n
            elif isinstance(n, list):
                stack += n


def _types(n) -> set:
    t = n.get("@type", [])
    return set(t if isinstance(t, list) else [t])


def _offers(o) -> list[dict]:
    if not o:
        return []
    return o if isinstance(o, list) else [o]


def _price(offer: dict) -> float | None:
    for k in ("price", "lowPrice"):
        if offer.get(k) not in (None, ""):
            try:
                return float(str(offer[k]).replace(",", "."))
            except ValueError:
                pass
    spec = offer.get("priceSpecification")
    if isinstance(spec, list) and spec:
        spec = spec[0]
    if isinstance(spec, dict) and spec.get("price") is not None:
        return float(spec["price"])
    return None


def _weight(n: dict) -> float | None:
    w = n.get("weight")
    if isinstance(w, dict) and w.get("value"):
        unit = (w.get("unitText") or w.get("unitCode") or "g").lower()
        return parse_grams(f"{w['value']} {'kg' if unit in ('kg', 'kgm') else 'g' if unit in ('g', 'grm') else unit}")
    return None


def _in_stock(offer: dict) -> bool | None:
    a = str(offer.get("availability", ""))
    if not a:
        return None
    return bool(re.search(r"InStock|LimitedAvailability|OnlineOnly|PreOrder", a))


def _list_price(offer: dict) -> float | None:
    spec = offer.get("priceSpecification")
    for sp in spec if isinstance(spec, list) else [spec]:
        if isinstance(sp, dict) and "ListPrice" in str(sp.get("priceType", "")) and sp.get("price"):
            return float(sp["price"])
    return None


def _sku_grams(offer: dict, rx: re.Pattern | None) -> float | None:
    m = rx.search(str(offer.get("sku", ""))) if rx else None
    return float(m.group(1)) if m and 100 <= float(m.group(1)) <= 10000 else None


META = re.compile(r'<meta[^>]+(?:property|itemprop|name)="([^"]+)"[^>]+content="([^"]*)"', re.I)


def _meta_variant(html: str) -> tuple[str, list[Variant]]:
    """Open Graph / microdata fallback: one price for the page's own size (PrestaShop, Magento)."""
    meta = {}
    for k, v in META.findall(html):
        meta.setdefault(k.lower(), v)
    name = meta.get("og:title") or meta.get("name") or ""
    raw = meta.get("og:price:amount") or meta.get("product:price:amount") or meta.get("price")
    if not raw:
        return name, []
    try:
        price = float(raw.replace(",", "."))
    except ValueError:
        return name, []
    avail = meta.get("availability") or meta.get("product:availability") or meta.get("og:availability") or ""
    stock = None if not avail else bool(re.search(r"instock|in stock|available|limited", avail, re.I))
    return name, [Variant(name, parse_grams(name), price, None, stock)]


def variants_from(html: str, sku_rx: re.Pattern | None = None) -> tuple[str, list[Variant]]:
    """Product name and variants from a product page's JSON-LD (Open Graph price as fallback)."""
    name, variants = "", []
    for n in _nodes(html):
        types = _types(n)
        if "ProductGroup" in types:
            name = n.get("name") or name
            for v in n.get("hasVariant", []):
                for off in _offers(v.get("offers")):
                    p = _price(off)
                    if p:
                        label = v.get("name", "")
                        variants.append(Variant(label, _weight(v) or parse_grams(label), p, None, _in_stock(off)))
        elif "Product" in types and not variants:
            name = name or n.get("name", "")
            label = n.get("name", "")
            for off in _offers(n.get("offers")):
                if off.get("@type") == "AggregateOffer" and off.get("offers"):
                    subs = [x for x in _offers(off["offers"]) if _price(x)]
                    one_price = len({_price(x) for x in subs}) == 1
                    for sub in subs:
                        sub_label = sub.get("name") or ""
                        # A sub-offer without its own size only inherits the title's size when every
                        # sub-offer costs the same (flavours of one size); otherwise sizes are unknown.
                        grams = parse_grams(sub_label) or (parse_grams(label) if one_price else None)
                        variants.append(
                            Variant(sub_label or label, grams, _price(sub), _list_price(sub), _in_stock(sub))
                        )
                    continue
                p = _price(off)
                if p and not (off.get("@type") == "AggregateOffer" and off.get("highPrice")
                              and float(off["highPrice"]) != p):
                    grams = _sku_grams(off, sku_rx) or _weight(n) or parse_grams(off.get("name") or "", label)
                    variants.append(Variant(str(off.get("sku") or label), grams, p, _list_price(off), _in_stock(off)))
    if not variants:
        meta_name, variants = _meta_variant(html)
        name = name or meta_name
    return name, variants


def collect(src: dict, fetch, now: str) -> list[Offer]:
    link_rx = re.compile(src.get("link_pattern", r'href="([^"]*/p/[^"?#]+)'))
    links: dict[str, bool] = {}
    for cat in src["categories"]:
        try:
            if src.get("render") and hasattr(fetch, "goto"):
                fetch.goto(cat, settle=2.0)
                fetch.scroll(src.get("scrolls", 6))
                rendered = fetch.eval("() => [...document.querySelectorAll('a[href]')].map(a => a.href)")
                bare = ['href="' + h.split("?")[0].split("#")[0] + '"' for h in rendered]
                hrefs = [m.group(1) for h in bare if (m := link_rx.search(h))]
            else:
                hrefs = []
                for page in range(1, src.get("pages", 1) + 1):
                    sep = "&" if "?" in cat else "?"
                    url = cat if page == 1 else f"{cat}{sep}{src.get('page_param', 'page')}={page}"
                    robots = getattr(fetch, "robots", None)
                    allowed = fetch.allowed(url) if hasattr(fetch, "allowed") else robots.allowed(url)
                    if page > 1 and not allowed:
                        break
                    found = link_rx.findall(fetch.text(url))
                    if page > 1 and not set(found) - set(hrefs):
                        break
                    hrefs += found
        except Exception as e:  # noqa: BLE001 - a moved category shouldn't drop the others
            if type(e).__name__ == "Blocked":
                raise
            print(f"  {src['id']}: category unavailable {cat}: {e}"[:160])
            continue
        tested_cat = bool(re.search(r"informed", cat))
        for href in hrefs:
            url = urljoin(cat, href).split("#")[0]
            links[url] = links.get(url, False) or tested_cat
    offers = []
    for url, tested_cat in list(links.items())[: src.get("max_products", 120)]:
        slug = re.sub(r"[-_/.]+", " ", urlsplit(url).path)
        if not classify(slug) and not src.get("open_all"):
            continue
        try:
            html = fetch.text(url)
        except Exception as e:  # noqa: BLE001 - one broken page shouldn't drop the shop
            if type(e).__name__ == "Blocked":
                raise
            continue
        offers += _product(src, url, html, now, tested_cat)
    return offers


def _brand(html: str) -> str | None:
    for n in _nodes(html):
        if _types(n) & {"Product", "ProductGroup"}:
            b = n.get("brand")
            b = b.get("name") if isinstance(b, dict) else b
            if isinstance(b, str) and b.strip():
                return clean(b).strip()
    return None


def _product(src, url, html, now, tested_cat=False) -> list[Offer]:
    name, variants = variants_from(html, re.compile(src["sku_grams"]) if src.get("sku_grams") else None)
    brand = src.get("brand") or _brand(html)
    name = clean(name)
    kind = classify(name)
    if not kind:
        return []
    variants = [v for v in variants if not is_sample(v.label.replace(name, ""))]
    text = clean(html)
    protein = None
    if kind == "whey":
        facts = ENRICH.get(url) or ENRICH.put(url, protein=protein_per_100g(text), tested=bool(TESTED.search(text)))
        protein = facts.get("protein")
    out = []
    for grams, s in group_variants(variants).items():
        out.append(
            Offer(
                shop=src["id"],
                market=src["market"],
                kind=kind,
                product=name,
                url=url,
                grams=grams,
                price=s["price"],
                list_price=s["list_price"],
                available=s["available"],
                flavours=s["flavours"],
                brand=brand,
                creapure=is_creapure(name),
                whey_type=whey_type(name) if kind == "whey" else None,
                native=kind == "whey" and is_native(name),
                protein_100g=protein,
                unflavoured=any(FLAVOURLESS.search(lbl) for lbl in s["labels"]),
                sweetener_free=bool(SWEETENER_FREE.search(name)),
                tested=tested_cat or bool(TESTED.search(text)),
                method="page",
                captured_at=now,
            )
        )
    return out
