"""Polite HTTP: identified User-Agent, robots.txt, per-host spacing, stop on refusal."""

import time
from urllib.parse import urlsplit

import httpx
from protego import Protego

USER_AGENT = "SupplementsPrice/0.1 (+https://github.com/MiKatre/supplementsprice)"
ROBOTS_AGENT = "SupplementsPrice"


class Blocked(Exception):
    """The shop refused us (401/403/429, challenge page, robots). Stop that source for this run."""


class Fetcher:
    def __init__(self, delay: float = 1.5, timeout: float = 25, max_requests: int = 5000):
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,fr;q=0.8,en;q=0.5"},
            timeout=timeout,
            follow_redirects=True,
        )
        self.delay = delay
        self.max_requests = max_requests
        self.requests = 0
        self._robots: dict[str, Protego | None] = {}
        self._last: dict[str, float] = {}
        self.deadline = float("inf")  # set per source by the collector

    def close(self):
        self.client.close()

    def robots(self, url: str) -> Protego | None:
        base = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if base not in self._robots:
            try:
                r = self.client.get(base + "/robots.txt")
                self._robots[base] = Protego.parse(r.text) if r.status_code == 200 else None
            except httpx.HTTPError:
                self._robots[base] = None
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        rp = self.robots(url)
        return rp is None or rp.can_fetch(url, ROBOTS_AGENT)

    def _wait(self, url: str):
        host = urlsplit(url).netloc
        rp = self.robots(url)
        delay = max(self.delay, (rp.crawl_delay(ROBOTS_AGENT) or 0) if rp else 0)
        wait = self._last.get(host, 0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def get(self, url: str, **kw) -> httpx.Response:
        if not self.allowed(url):
            raise Blocked(f"robots.txt disallows {url}")
        if self.requests >= self.max_requests:
            raise Blocked("request budget for this run exhausted")
        if time.monotonic() > self.deadline:
            raise Blocked("time budget for this source exhausted")
        for attempt in (1, 2):
            self._wait(url)
            self.requests += 1
            try:
                r = self.client.get(url, **kw)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                continue
            if r.status_code in (401, 403, 429):
                raise Blocked(f"HTTP {r.status_code} for {url}")
            if r.status_code >= 500 and attempt == 1:
                continue
            return r
        return r

    def json(self, url: str, **kw):
        r = self.get(url, **kw)
        r.raise_for_status()
        return r.json()

    def text(self, url: str, **kw) -> str:
        r = self.get(url, **kw)
        r.raise_for_status()
        return r.text
