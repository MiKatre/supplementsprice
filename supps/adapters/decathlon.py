"""Decathlon (ES/FR): search result cards carry title, price, crossed-out price and marketplace seller.
Decathlon-brand whey pages are opened for the protein figure; marketplace pages aren't (too many)."""

import re

from ..model import Offer
from ..normalize import (
    FLAVOURLESS,
    SWEETENER_FREE,
    classify,
    is_creapure,
    is_native,
    parse_grams,
    protein_per_100g,
    whey_type,
)

CARDS_JS = r"""() => [...document.querySelectorAll('article.product-card')].map(c => ({
  brand: (c.querySelector('img') || {}).alt || '',
  title: (c.querySelector('h2') || {}).innerText || '',
  href: (c.querySelector('h2 a') || {}).href || '',
  text: c.innerText,
}))"""

PRICE = re.compile(r"(\d{1,4}(?:[.\s]\d{3})*,\d{2})\s*€(?!\s*/)")
LIST = re.compile(
    r"(?:PVPR|Prix conseillé|Precio anterior|Prix de référence|Ancien prix)\D{0,20}(\d{1,4},\d{2})\s*€", re.I
)
SELLER = re.compile(r"(?:Vendido y enviado por|Vendu et expédié par)\s+([^\n]+)", re.I)


def _eur(s: str) -> float:
    return float(s.replace(".", "").replace(" ", "").replace(",", "."))


def collect(src: dict, browser, now: str) -> list[Offer]:
    seen, offers = set(), []
    for cat in src["categories"]:
        for start in range(0, src.get("max_results", 160), 40):
            browser.goto(cat if start == 0 else f"{cat}?from={start}&size=40", settle=1.5)
            cards = browser.eval(CARDS_JS)
            if not cards:
                break
            for c in cards:
                if c["href"] in seen:
                    continue
                seen.add(c["href"])
                o = _card(src, c, now)
                if o:
                    offers.append(o)
            if len(cards) < 40:
                break
    # Protein for Decathlon's own whey (their pages state it; marketplace items would cost a page each).
    own = [o for o in offers if o.kind == "whey" and not o.seller][: src.get("protein_pages", 20)]
    for o in own:
        try:
            browser.goto(o.url, settle=1.0)
            o.protein_100g = protein_per_100g(browser.page_text())
        except Exception:  # noqa: BLE001 - protein is enrichment; keep the price either way
            continue
    return offers


def _card(src, c, now) -> Offer | None:
    title = " ".join(c["title"].split())
    brand = c["brand"].replace(" picture", "").strip()
    name = title[len(brand):].strip(" -") if brand and title.upper().startswith(brand.upper()) else title
    kind = classify(title)
    if not kind:
        return None
    grams = parse_grams(title)
    text = c["text"]
    prices = PRICE.findall(text.split("€/kg")[0] if "€/kg" in text else text)
    if not grams or not prices:
        return None
    price = _eur(prices[0])
    lst = LIST.search(text)
    seller = SELLER.search(text)
    return Offer(
        shop=src["id"],
        market=src["market"],
        kind=kind,
        product=name or title,
        url=c["href"].split("?")[0],
        grams=grams,
        price=price,
        list_price=_eur(lst.group(1)) if lst and _eur(lst.group(1)) > price else None,
        available=True,
        brand=brand.title() if brand else None,
        seller=seller.group(1).strip() if seller else None,
        creapure=is_creapure(title),
        whey_type=whey_type(title) if kind == "whey" else None,
        native=kind == "whey" and is_native(title),
        unflavoured=bool(FLAVOURLESS.search(title)),
        sweetener_free=bool(SWEETENER_FREE.search(title)),
        method="browser",
        captured_at=now,
    )
