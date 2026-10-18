"""Amazon.es / Amazon.fr search results, read in a real browser. Results mix brands and sellers, so
only titles that state a size are kept; the product page link is the stable /dp/ASIN form."""

import re
from urllib.parse import quote

from ..model import Offer
from ..normalize import FLAVOURLESS, classify, is_creapure, is_native, parse_grams, whey_type

CARDS_JS = r"""() => [...document.querySelectorAll('[data-component-type="s-search-result"]')].map(r => ({
  asin: r.dataset.asin,
  title: (r.querySelector('h2') || {}).innerText || '',
  price: (r.querySelector('.a-price:not(.a-text-price) .a-offscreen') || {}).textContent || '',
  list: (r.querySelector('.a-price.a-text-price .a-offscreen') || {}).textContent || '',
  sponsored: !!r.querySelector('.puis-sponsored-label-text, [aria-label*="patrocinado" i]'),
}))"""


def _eur(s: str) -> float | None:
    """'24,98 €', '1 249,99 €', '€24.98' → float."""
    s = re.sub(r"[\s\xa0\u202f]", "", s or "")
    m = re.search(r"\d+(?:[.,]\d{3})*(?:[.,]\d{1,2})?", s)
    if not m:
        return None
    v = m.group(0)
    if re.search(r"[.,]\d{1,2}$", v):
        whole, dec = v[:-3 if v[-3] in ".," else -2], v[-2:] if v[-3] in ".," else v[-1:]
        v = re.sub(r"[.,]", "", whole) + "." + dec
    else:
        v = re.sub(r"[.,]", "", v)
    try:
        return float(v)
    except ValueError:
        return None


def collect(src: dict, browser, now: str) -> list[Offer]:
    base = src["base"]
    seen, offers = set(), []
    for q in src["queries"]:
        for page in range(1, src.get("pages", 2) + 1):
            browser.goto(f"{base}/s?k={quote(q)}" + (f"&page={page}" if page > 1 else ""), settle=1.5)
            cards = browser.eval(CARDS_JS)
            if not cards:
                if not offers and page == 1:  # say what Amazon showed instead of results
                    raise RuntimeError(f"no results on '{browser.page.title()[:70]}' ({browser.page.url[:80]})")
                break
            for c in cards:
                if not c["asin"] or c["asin"] in seen:
                    continue
                seen.add(c["asin"])
                o = _card(src, c, now)
                if o:
                    offers.append(o)
    return offers


def _card(src, c, now) -> Offer | None:
    title = " ".join(c["title"].split())
    kind = classify(title)
    price = _eur(c["price"])
    grams = parse_grams(title)
    if not kind or not price or not grams:
        return None
    lst = _eur(c["list"]) if c["list"] else None
    return Offer(
        shop=src["id"],
        market=src["market"],
        kind=kind,
        product=title[:140],
        url=f"{src['base']}/dp/{c['asin']}",
        grams=grams,
        price=price,
        list_price=lst if lst and lst > price else None,
        available=True,
        creapure=is_creapure(title),
        whey_type=whey_type(title) if kind == "whey" else None,
        native=kind == "whey" and is_native(title),
        unflavoured=bool(FLAVOURLESS.search(title)),
        method="browser",
        note="sponsored result" if c.get("sponsored") else "",
        captured_at=now,
    )
