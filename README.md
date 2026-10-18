# Creatine & Whey Prices

Creatine (Creapure® and plain monohydrate) and whey protein compared by price per kg, and whey by
price per kg of protein (read from each shop's nutrition label), across shops selling in Spain and France.

- `sources.json`: every shop, its adapter, market and nightly group.
- `supps/`: collector. Shopify `/products.json`, WooCommerce Store API, JSON-LD / Open Graph product
  pages, and a real Chromium (Playwright) for shops that only serve browsers.
- `data/latest.json`: current offers plus each source's status. `data/history/`: one price file per day.
  `data/enrich.json`: protein per 100 g and net weights read from product pages, re-read after 30 days.
- `site/`: one static page; `python site/build.py` bakes the data into `dist/index.html`.
- `.github/workflows/collect.yml`: three nightly runs (groups a, b, c), commits the data, uploads the page.

```sh
uv sync --group dev
uv run playwright install chromium
uv run python -m supps.collect --group a          # one group
uv run python -m supps.collect --only hsn,crown   # some sources
HEADED=1 uv run python -m supps.collect           # browser sources need a headed Chrome
uv run python site/build.py
```

## Sources

| Group | Shops | How |
|---|---|---|
| a | Nutrimuscle, Toutelanutrition, Novoma, Inshape, Fitnessboutique, Eiyolab, Nutrimea, Crown, 226ERS, Nutri9, Quamtrax, Body & Fit, ESN | Shopify `/products.json`; from GitHub it answers 429, so the collector repeats the request from inside the browser |
| a | Myprotein ES/FR | JSON-LD `ProductGroup` on product pages, plain HTTP |
| b | HSN | Browser; configurable-options JSON embedded in each product page |
| b | Decathlon ES/FR | Browser; category pages (search is disallowed by robots.txt) |
| b | Prozis ES/FR, Bulk ES/FR | Browser; rendered listing pages, JSON-LD product pages (Bulk sizes come from the SKU) |
| c | Amazon.es/.fr | Browser; search results, titles must state a size |
| c | MASmusculo, Nutritienda | Browser; Open Graph / JSON-LD product pages |
| c | Fitadium, Gold Nutrición | JSON-LD product pages, plain HTTP |

Shops that challenge GitHub's network on a given night keep their last good prices, shown with their date.
MASmusculo's firewall refuses datacenter IPs outright; refresh it (and anything else stuck) from home:

```sh
HEADED=1 uv run python -m supps.collect --only masmusculo,decathlon-es,decathlon-fr,prozis-es
git add data && git commit -m "chore(data): refresh blocked shops from home" && git push
```

Not covered: Zumub and El Corte Inglés (Cloudflare challenge even for a normal browser), Nutripure,
Foodspring, brand-only shops without prices (Weider, Optimum Nutrition).

## Collection manners

Identified User-Agent on plain HTTP, robots.txt honoured (for browser pages too), ≥1.5 s between requests
to a host (slower for Prozis, Decathlon, Amazon), stop at 401/403/429. Browser sources wait out
"checking your browser" interstitials but never solve or click CAPTCHAs; a source still challenged after
a second try in a fresh browser is reported as blocked. Per-source time budgets plus a watchdog keep one
slow shop from stalling a run.

## Data rules

- One row per product size: cheapest in-stock flavour; sachets, single doses and samples are dropped.
- Creatine: powder only (no capsules, gummies, blends with HMB, electrolytes or whey).
- Whey: concentrate, isolate, hydrolysed and WPC/WPI blends; no gainers, casein, vegan, bars, drinks.
- Protein per 100 g as sold, from the label's table; "dry matter" figures are skipped.
- €/kg outside 6–300 (creatine) or 12–160 (whey) is treated as a parsing error and dropped.
