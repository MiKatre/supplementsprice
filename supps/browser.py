"""A real Chromium for shops that only serve browsers. Same manners as the HTTP fetcher:
robots.txt, spacing between page loads, and stop at the first refusal or challenge page.

On CI it runs headed under xvfb (HEADED=1): a normal desktop Chrome, nothing spoofed.
"""

import json
import os
import re
import time
from urllib.parse import urlsplit

from .http import Blocked, Fetcher

CHALLENGE = re.compile(
    r"just a moment|attention required|access denied|robot check|are you a robot|captcha|"
    r"enter the characters you see|verify you are human|unusual traffic|pardon our interruption|"
    r"request unsuccessful|incapsula|perimeterx|px-captcha|datadome|waf\b|"
    r"continuer vos achats|continue shopping|seguir comprando|cliquez sur le bouton ci-dessous|"
    r"click the button below to continue",
    re.I,
)


INTERSTITIAL = re.compile(r"^(un momento|un instant|one moment|momentito|please wait|espere)", re.I)


class Browser:
    def __init__(self, delay: float = 2.5, max_pages: int = 1500):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=os.environ.get("HEADED") != "1")
        self.context = self.browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1366, "height": 900},
        )
        self.context.set_default_timeout(30000)
        self.context.set_default_navigation_timeout(45000)
        self.page = self.context.new_page()
        self.delay = delay
        self.max_pages = max_pages
        self.pages = 0
        self.robots = Fetcher()
        self._last = 0.0
        self._origins: set[str] = set()
        self._canonical: dict[str, str] = {}
        self.deadline = float("inf")  # set per source by the collector

    def fresh(self):
        """New browser context (no cookies) for a second attempt at a source that challenged us."""
        self.context.close()
        self.context = self.browser.new_context(
            locale="es-ES", timezone_id="Europe/Madrid", viewport={"width": 1366, "height": 900}
        )
        self.context.set_default_timeout(30000)
        self.context.set_default_navigation_timeout(45000)
        self.page = self.context.new_page()
        self._origins.clear()
        self._canonical.clear()

    def close(self):
        try:
            self.context.close()
            self.browser.close()
        finally:
            self._pw.stop()
            self.robots.close()

    def goto(self, url: str, wait: str = "domcontentloaded", settle: float = 1.0):
        if not self.robots.allowed(url):
            raise Blocked(f"robots.txt disallows {url}")
        if self.pages >= self.max_pages:
            raise Blocked("page budget for this run exhausted")
        if time.monotonic() > self.deadline:
            raise Blocked("time budget for this source exhausted")
        gap = self._last + self.delay - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        self.pages += 1
        resp = self.page.goto(url, wait_until=wait, timeout=45000)
        self._last = time.monotonic()
        if settle:
            self.page.wait_for_timeout(int(settle * 1000))
        status = resp.status if resp else 0
        title = self.page.title()
        if status in (403, 429, 503) or CHALLENGE.search(title) or INTERSTITIAL.search(title):
            # Interstitial "checking your browser" pages clear on their own in a normal browser.
            # Give it time; never click anything. Still there afterwards → treat as blocked.
            for _ in range(20):
                self.page.wait_for_timeout(2000)
                title = self.page.title()
                if not (CHALLENGE.search(title) or INTERSTITIAL.search(title)):
                    status = 200
                    self.page.wait_for_load_state("domcontentloaded")
                    break
        if status in (401, 403, 429) or CHALLENGE.search(title) or INTERSTITIAL.search(title):
            raise Blocked(f"HTTP {status} / '{title[:60]}' for {url}")
        head = self.page.evaluate("document.body ? document.body.innerText.slice(0, 600) : ''")
        if CHALLENGE.search(head) and len(head) < 600:  # a bare bot page, not a product page mentioning it
            raise Blocked(f"challenge page at {url}: {head[:80]!r}")
        return resp

    def eval(self, js: str, arg=None):
        return self.page.evaluate(js, arg)

    def page_text(self) -> str:
        """Whole page text including collapsed tabs (nutrition tables hide in those)."""
        return self.page.evaluate("document.body ? document.body.textContent.replace(/\\s+/g, ' ') : ''")

    def _fetch(self, url: str) -> str:
        """GET from inside the page (real Chrome, same cookies). Opens the shop's home page first so any
        interstitial check runs once, like a person landing on the site."""
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
        if origin not in self._origins:
            self.goto(origin + "/", settle=1.5)
            self._origins.add(origin)
            landed = self.page.evaluate("location.origin")
            if landed != origin:  # e.g. inshape-nutrition.com → www.inshape-nutrition.com
                self._canonical[origin] = landed
        if origin in self._canonical:
            url = self._canonical[origin] + url[len(origin):]
        elif self.page.evaluate("location.origin") != origin:
            self.goto(origin + "/", settle=1.0)
        if not self.robots.allowed(url):
            raise Blocked(f"robots.txt disallows {url}")
        if time.monotonic() > self.deadline:
            raise Blocked("time budget for this source exhausted")
        gap = self._last + self.delay - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        self.pages += 1
        r = self.page.evaluate(
            "async u => { const r = await fetch(u, {credentials: 'include'}); return [r.status, await r.text()] }",
            url,
        )
        self._last = time.monotonic()
        status, body = r
        if status in (401, 403, 429):
            raise Blocked(f"HTTP {status} (in-browser) for {url}")
        if status >= 400:
            raise RuntimeError(f"HTTP {status} for {url}")
        return body

    def json(self, url: str):
        return json.loads(self._fetch(url))

    def text(self, url: str) -> str:
        return self._fetch(url)

    def scroll(self, times: int = 6, pause: float = 0.7):
        for _ in range(times):
            self.page.mouse.wheel(0, 2500)
            self.page.wait_for_timeout(int(pause * 1000))
