"""Bake data/latest.json into the page.

    python site/build.py   → dist/index.html (standalone page) and dist/artifact.html (body fragment)
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = (
    "shop market kind product url grams price list_price available flavours brand seller creapure whey_type "
    "native protein_100g unflavoured sweetener_free tested method note captured_at eur_kg eur_kg_protein"
).split()


def build() -> Path:
    data = json.loads((ROOT / "data/latest.json").read_text())
    sources = {s["id"]: s for s in json.loads((ROOT / "sources.json").read_text())["sources"]}
    shops = {}
    for sid, st in data["sources"].items():
        src = sources.get(sid, {})
        shops[sid] = {
            "name": src.get("name", st.get("name", sid)),
            "market": src.get("market", st.get("market")),
            "url": src.get("url", st.get("url")),
            "status": st["status"],
            "offers": st.get("offers"),
            "kept_offers": st.get("kept_offers"),
        }
    for o in data["offers"]:  # hand-checked shops have no run status
        if o["shop"] not in shops:
            src = sources.get(o["shop"], {})
            shops[o["shop"]] = {"name": src.get("name", o["shop"]), "market": o["market"], "url": src.get("url", ""),
                                "status": "reviewed"}
    payload = {
        "generated_at": data["generated_at"],
        "shops": shops,
        "offers": [{k: o[k] for k in KEEP if k in o and (k in ("available", "flavours") or o[k] not in (None, "")
                                                          and o[k] is not False)}
                   for o in data["offers"]],
    }
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (ROOT / "data/site.json").write_text(compact + "\n")  # what the live page fetches each visit
    blob = compact.replace("</", "<\\/")
    fragment = (ROOT / "site/template.html").read_text().replace("__DATA__", blob)
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    (out / "artifact.html").write_text(fragment)
    head, _, body = fragment.partition("<div class=\"wrap\">")
    page = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        f"{head}</head>\n<body>\n<div class=\"wrap\">{body}</body>\n</html>\n"
    )
    (out / "index.html").write_text(page)
    print(f"dist/index.html: {len(payload['offers'])} offers, {len(shops)} shops, {len(page) // 1024} KB")
    return out / "index.html"


if __name__ == "__main__":
    build()
