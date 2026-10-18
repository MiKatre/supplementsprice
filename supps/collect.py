"""Run every source, keep what each one returned, write data/latest.json and a dated history file.

    python -m supps.collect                 # all sources
    python -m supps.collect --only hsn,myprotein-es
    python -m supps.collect --skip-browser  # no Playwright sources

A source that fails keeps its previous offers (with their original capture time) so one bad night
doesn't empty the table. Each source's status lands in data/latest.json for the site to show.
"""

import argparse
import importlib
import json
import signal
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .cache import ENRICH
from .http import Blocked, Fetcher

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources.json"
LATEST = ROOT / "data" / "latest.json"
HISTORY = ROOT / "data" / "history"
REVIEWED = ROOT / "reviewed" / "manual.json"
REPORT = ROOT / "runs" / "report.json"

# €/kg outside these ranges is a parsing error (sample sachet, bundle, wrong size), not a deal.
SANE = {"creatine": (6, 300), "whey": (12, 160)}


class Watchdog(Exception):
    """A source overran its time budget inside a call that has no timeout of its own."""


def _alarm(signum, frame):
    raise Watchdog("source exceeded its time budget (watchdog)")


def _browser(deadline: float = float("inf")):
    from .browser import Browser

    b = Browser()
    b.deadline = deadline
    return b


def load_sources() -> list[dict]:
    return json.loads(SOURCES.read_text())["sources"]


def sane(o: dict) -> bool:
    lo, hi = SANE[o["kind"]]
    return lo <= o["eur_kg"] <= hi


def dedupe(offers: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for o in offers:
        k = f"{o['shop']}|{o['url']}|{int(o['grams'])}"
        if k not in best or o["price"] < best[k]["price"]:
            best[k] = o
    return list(best.values())


def run(only: set[str] | None = None, skip_browser: bool = False, budget_minutes: float = 40) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_deadline = time.monotonic() + budget_minutes * 60
    previous = json.loads(LATEST.read_text()) if LATEST.exists() else {"offers": [], "sources": {}}
    prev_by_shop: dict[str, list] = {}
    for o in previous.get("offers", []):
        prev_by_shop.setdefault(o["shop"], []).append(o)

    fetch = Fetcher()
    browser = None
    statuses, offers = {}, []
    # Browser sources that hit a challenge get one more try at the end, in a fresh browser context:
    # these checks are often intermittent, and by then the run has spent a few minutes elsewhere.
    queue = [(1, s) for s in load_sources()]
    try:
        i = 0
        while i < len(queue):
            attempt, src = queue[i]
            i += 1
            sid = src["id"]
            if only and sid not in only:
                if sid in previous.get("sources", {}):
                    statuses[sid] = previous["sources"][sid]
                offers += prev_by_shop.get(sid, [])
                continue
            meta = {k: src.get(k) for k in ("name", "market", "url", "adapter")}
            if src.get("paused"):
                statuses[sid] = {**meta, "status": "paused", "reason": src["paused"]}
                offers += prev_by_shop.get(sid, [])
                continue
            if time.monotonic() > run_deadline:
                statuses[sid] = {**meta, "status": "skipped", "reason": "run time budget used up",
                                 "kept_offers": len(prev_by_shop.get(sid, []))}
                offers += prev_by_shop.get(sid, [])
                continue
            if attempt == 2 and browser:
                browser.fresh()
            if src.get("browser") and skip_browser:
                statuses[sid] = previous.get("sources", {}).get(sid, {**meta, "status": "skipped"})
                offers += prev_by_shop.get(sid, [])
                continue
            t0 = time.monotonic()
            source_deadline = min(run_deadline, t0 + src.get("max_minutes", 8) * 60)
            fetch.deadline = source_deadline
            if browser:
                browser.deadline = source_deadline
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(int(source_deadline - t0) + 90)
            try:
                mod = importlib.import_module(f".adapters.{src['adapter']}", __package__)
                if src.get("browser"):
                    browser = browser or _browser(source_deadline)
                    browser.delay = src.get("delay", 2.5)
                    got = mod.collect(src, browser, now)
                else:
                    try:
                        got = mod.collect(src, fetch, now)
                    except Blocked as e:
                        if not getattr(mod, "BROWSER_FALLBACK", False) or skip_browser:
                            raise
                        print(f"{sid:24} {e}; retrying in the browser", flush=True)
                        browser = browser or _browser(source_deadline)
                        browser.delay = src.get("delay", 2.5)
                        got = mod.collect(src, browser, now)
                        meta["via"] = "browser"
                rows = [o.to_dict() for o in got]
                rows = [r for r in rows if sane(r)]
                if not rows and src.get("expect_offers", True):
                    raise RuntimeError("returned no creatine or whey offers")
                offers += rows
                statuses[sid] = {
                    **meta,
                    "status": "ok",
                    "offers": len(rows),
                    "checked_at": now,
                    "seconds": round(time.monotonic() - t0, 1),
                }
            except Exception as e:  # noqa: BLE001 - one source must never stop the others
                if isinstance(e, Watchdog) and browser:
                    try:
                        browser.close()
                    except Exception:  # noqa: BLE001 - it's already wedged; start a fresh one next time
                        pass
                    browser = None
                if attempt == 1 and isinstance(e, Blocked) and src.get("browser") and "robots" not in str(e):
                    queue.append((2, src))
                    print(f"{sid:24} blocked ({str(e)[:80]}); will retry at the end", flush=True)
                    signal.alarm(0)
                    continue
                kept = prev_by_shop.get(sid, [])
                offers += kept
                statuses[sid] = {
                    **meta,
                    "status": "blocked" if isinstance(e, Blocked) else "failed",
                    "error": f"{type(e).__name__}: {e}"[:300],
                    "kept_offers": len(kept),
                    "last_ok": previous.get("sources", {}).get(sid, {}).get("checked_at")
                    if previous.get("sources", {}).get(sid, {}).get("status") == "ok"
                    else previous.get("sources", {}).get(sid, {}).get("last_ok"),
                    "checked_at": now,
                    "seconds": round(time.monotonic() - t0, 1),
                }
                if not isinstance(e, Blocked):
                    traceback.print_exc()
            signal.alarm(0)
            s = statuses[sid]
            print(f"{sid:24} {s['status']:8} {s.get('offers', s.get('kept_offers', 0)):4}  {s.get('error', '')[:120]}",
                  flush=True)
    finally:
        fetch.close()
        if browser:
            browser.close()

    ENRICH.save()

    # Hand-checked observations fill in shops we couldn't read this run (never override fresh data).
    if REVIEWED.exists():
        fresh_shops = {sid for sid, s in statuses.items() if s["status"] == "ok"}
        for r in json.loads(REVIEWED.read_text())["offers"]:
            if r["shop"] not in fresh_shops:
                offers.append(r)

    offers = dedupe(offers)
    offers.sort(key=lambda o: (o["kind"], o["eur_kg"]))
    data = {"generated_at": now, "sources": statuses, "offers": offers}
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    HISTORY.mkdir(parents=True, exist_ok=True)
    day = now[:10]
    (HISTORY / f"{day}.json").write_text(
        json.dumps(
            {"date": day, "prices": {f"{o['shop']}|{o['url']}|{int(o['grams'])}": o["price"] for o in offers
                                     if o.get("captured_at", "")[:10] == day}},
            ensure_ascii=False, sort_keys=True,
        ) + "\n"
    )
    report = {
        "generated_at": now,
        "offers": len(offers),
        "by_kind": {k: sum(o["kind"] == k for o in offers) for k in SANE},
        "ok": sorted(s for s, v in statuses.items() if v["status"] == "ok"),
        "failed": sorted(s for s, v in statuses.items() if v["status"] in ("failed", "blocked")),
        "requests": fetch.requests,
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps({**report, "sources": statuses}, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated source ids")
    ap.add_argument("--group", help="run the sources of one group from sources.json (a, b, c)")
    ap.add_argument("--skip-browser", action="store_true")
    ap.add_argument("--budget", type=float, default=40, help="minutes for the whole run")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    if a.group:
        only = (only or set()) | {s["id"] for s in load_sources() if s.get("group") == a.group}
    run(only, a.skip_browser, a.budget)


if __name__ == "__main__":
    main()
