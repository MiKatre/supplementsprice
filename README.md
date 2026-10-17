# Creatine & Whey Prices

Creatine (Creapure® and plain monohydrate) and whey protein compared by price per kg, and whey by
price per kg of protein, across shops selling in Spain and France.

- `sources.json`: every shop, its adapter and market.
- `supps/`: collector. Shopify `/products.json`, WooCommerce Store API, JSON-LD product pages, and
  a real Chromium (Playwright) for shops that only serve browsers.
- `data/latest.json`: current offers plus each source's status. `data/history/`: one price file per day.
- `site/`: one static page; `python site/build.py` bakes the data into `dist/index.html`.
- `.github/workflows/collect.yml`: daily collection, commits the data, uploads the built page.

```sh
uv sync --group dev
uv run playwright install chromium
uv run python -m supps.collect                    # everything
uv run python -m supps.collect --only hsn,crown   # some sources
HEADED=1 uv run python -m supps.collect           # browser sources need a headed Chrome
uv run python site/build.py
```

Collection manners: identified User-Agent on plain HTTP, robots.txt honoured, ≥1.5 s between
requests to a host, stop at 401/403/429. Browser sources wait out "checking your browser"
interstitials but never solve or click CAPTCHAs; a source that keeps challenging is reported as blocked
and its last good prices stay visible with their date.
