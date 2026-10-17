"""HSN (hsnstore.com): Magento. Category pages list products; each product page embeds its
configurable-options JSON with the final price of every flavour × size, and the nutrition table."""

import json
import re

from ..model import Offer, Variant, group_variants
from ..normalize import (
    FLAVOURLESS,
    SWEETENER_FREE,
    TESTED,
    classify,
    is_creapure,
    is_native,
    parse_grams,
    protein_per_100g,
    whey_type,
)

CATEGORIES = [
    "https://www.hsnstore.com/nutricion-deportiva/creatina",
    "https://www.hsnstore.com/nutricion-deportiva/proteinas",
]

CONFIG_JS = r"""() => {
  const t = [...document.scripts].map(s => s.textContent).find(t => /initConfigurableSwatchOptions_/.test(t));
  if (!t) return null;
  const i = t.indexOf('{"attributes"');
  let d = 0, j = i;
  for (; j < t.length; j++) { if (t[j] == '{') d++; else if (t[j] == '}') { d--; if (!d) break; } }
  return t.slice(i, j + 1);
}"""


def collect(src: dict, browser, now: str) -> list[Offer]:
    links: dict[str, str] = {}
    for cat in src.get("categories", CATEGORIES):
        browser.goto(cat)
        browser.scroll(8)
        for href, name in browser.eval(
            """() => [...document.querySelectorAll('main a[href*="/marcas/"]')]
                 .map(a => [a.href.split(/[?#]/)[0], (a.innerText || a.title || '').trim()])"""
        ):
            if re.search(r"/marcas/[^/]+/[^/]+$", href) and href not in links:
                links[href] = name
    offers = []
    for url in links:
        slug = url.rsplit("/", 1)[1].replace("-", " ")
        if not classify(slug) and not classify(links[url]):
            continue
        browser.goto(url, settle=0.5)
        offers += _product(src, browser, url, now)
    return offers


def _product(src, browser, url, now) -> list[Offer]:
    title = browser.eval("() => (document.querySelector('h1') || {}).innerText || document.title").strip()
    kind = classify(title) or classify(browser.page.title())
    if not kind:
        return []
    raw = browser.eval(CONFIG_JS)
    text = browser.page_text()
    variants = []
    if raw:
        cfg = json.loads(raw)
        salable = set()
        for opts in (cfg.get("salable") or {}).values():
            for ids in opts.values():
                salable.update(ids)
        attrs = list(cfg["attributes"].values())
        is_size = lambda a: re.search(r"weight|peso|size|format", a["code"] + a["label"], re.I)  # noqa: E731
        size_attr = next((a for a in attrs if is_size(a)), None)
        other = [a for a in attrs if a is not size_attr]
        label_of = {}
        for a in other:
            for o in a["options"]:
                for pid in o["products"]:
                    label_of[pid] = o["label"]
        for o in (size_attr or {"options": []})["options"]:
            if re.search(r"pack|monodos|sample|muestra", o["label"], re.I):
                continue
            grams = parse_grams(o["label"])
            for pid in o["products"]:
                prices = cfg["optionPrices"].get(pid) or {}
                price = (prices.get("finalPrice") or {}).get("amount")
                old = (prices.get("oldPrice") or {}).get("amount")
                if not price:
                    continue
                variants.append(
                    Variant(
                        label=label_of.get(pid, ""),
                        grams=grams,
                        price=round(price, 2),
                        list_price=round(old, 2) if old else None,
                        available=pid in salable if salable else None,
                    )
                )
    out = []
    protein = protein_per_100g(text) if kind == "whey" else None
    for grams, s in group_variants(variants).items():
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
                brand=url.split("/marcas/")[1].split("/")[0].replace("-", " ").title(),
                creapure=is_creapure(title, browser.page.title()),
                whey_type=whey_type(title + " " + browser.page.title()) if kind == "whey" else None,
                native=kind == "whey" and is_native(title),
                protein_100g=protein,
                unflavoured=any(FLAVOURLESS.search(lbl) for lbl in s["labels"]),
                sweetener_free=bool(SWEETENER_FREE.search(title)),
                tested=bool(TESTED.search(text)),
                method="browser",
                captured_at=now,
            )
        )
    return out
