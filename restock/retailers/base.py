"""Shared HTTP plumbing for every retailer checker."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests

from ..config import Config
from ..models import StockResult
from .blocks import BlockInfo, classify
from .browser import BrowserUnavailable, BrowserWorker, FetchResult

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
BROWSER_STICKY_S = 6 * 3600          # after a block, keep using the browser this long
PAUSE_FOR = {"rate_limit": 300, "challenge": 900, "denied": 1800, "queue": 60}
HARD_DENY_PAUSE = 6 * 3600          # Imperva "Error 15" style bans


TRACKER = None  # set by the engine: a sessions.BlockTracker


def set_tracker(tracker) -> None:
    global TRACKER
    TRACKER = tracker


class Blocked(Exception):
    """Site refused or rate limited us. The engine backs off when it sees this."""

    def __init__(self, message: str, retry_after: float = 0, waiting_for_human: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.waiting_for_human = waiting_for_human


class Retailer:
    name = "base"
    display = "Base"
    supports_search = False
    supports_in_store = False
    search_has_stock = False          # search results already carry online stock
    default_fetch_mode = "direct"     # direct | auto | browser

    def __init__(self, cfg: Config, log: logging.Logger, browser: BrowserWorker | None = None):
        self.cfg = cfg
        self.rcfg = cfg.retailer_cfg(self.name)
        self.log = log
        self.browser = browser
        self.browser_until = 0.0
        self.last_via = "direct"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
        })

    # ---- override these -------------------------------------------------
    def resolve_upc(self, upc: str) -> str | None:
        return None

    def seed_products(self) -> list:
        """Known products to track when search finds nothing. Stores without a list return none."""
        return []

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        raise NotImplementedError

    def search(self, query: str, limit: int) -> list[StockResult]:
        return []

    def stores_near(self, areas) -> list:
        """Store list for the places finder (list of places.Place). Chains with a store finder override this."""
        return []

    def signals(self) -> list[dict]:
        """Extra site-wide signals checked once a cycle, e.g. a drop queue opening."""
        return []

    # ---- helpers ----------------------------------------------------------
    @property
    def zip(self) -> str:
        return str(self.cfg.location.get("zip") or "").strip()

    @property
    def radius(self) -> float:
        return float(self.cfg.location.get("radius_miles") or 25)

    @property
    def areas(self):
        return self.cfg.areas

    def in_store_enabled(self) -> bool:
        return bool(self.cfg.settings.get("in_store")) and bool(self.areas)

    @property
    def fetch_mode(self) -> str:
        mode = str(self.rcfg.get("fetch_mode") or self.default_fetch_mode).lower()
        return mode if mode in ("direct", "auto", "browser") else "direct"

    def using_browser(self) -> bool:
        if not (self.browser and self.browser.usable):
            return False
        return self.fetch_mode == "browser" or (self.fetch_mode == "auto" and time.time() < self.browser_until)

    def _raise(self, info: BlockInfo, retry_after: float | None = None) -> None:
        pause = HARD_DENY_PAUSE if info.hard else (info.retry_after or retry_after or PAUSE_FOR[info.kind])
        raise Blocked(info.message(self.display), pause)

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            expect_json: bool = False, timeout: float = 20) -> requests.Response:
        """Direct request for APIs and JSON endpoints."""
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            raise ConnectionError(f"{self.display}: network error {exc.__class__.__name__}") from exc
        if resp.status_code >= 500 and resp.status_code != 503:
            raise ConnectionError(f"{self.display}: server error {resp.status_code}")
        info = classify(resp.status_code, "" if expect_json and resp.status_code < 400 else resp.text, resp.headers)
        if TRACKER:
            TRACKER.record("direct", self.name, info is None or info.kind == "queue", info.kind if info else "")
        if info:
            self._raise(info, _retry_after(resp) if info.kind == "rate_limit" else None)
        if resp.status_code == 503:
            raise ConnectionError(f"{self.display}: temporarily unavailable (503)")
        return resp

    def fetch_html(self, url: str) -> FetchResult:
        """Load a product or search page, using the real browser when the site needs it."""
        if self.using_browser():
            return self._via_browser(url)

        try:
            # no-cache: ask for a fresh page so a cached "in stock" or "sold out" is not reported.
            resp = self.session.get(url, timeout=25, headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Cache-Control": "no-cache", "Pragma": "no-cache"})
        except requests.RequestException as exc:
            raise ConnectionError(f"{self.display}: network error {exc.__class__.__name__}") from exc
        info = classify(resp.status_code, resp.text, resp.headers)
        if TRACKER and not (info is None and resp.status_code >= 500):
            TRACKER.record("direct", self.name, info is None or info.kind == "queue", info.kind if info else "")
        if info is None and resp.status_code >= 500:
            raise ConnectionError(f"{self.display}: server error {resp.status_code}")
        if info is None or info.kind == "queue":
            self.last_via = "direct"
            return FetchResult(resp.status_code, resp.text, resp.url, info)

        if (info.kind != "rate_limit" and self.fetch_mode == "auto"
                and self.browser and self.browser.usable):
            self.browser_until = time.time() + BROWSER_STICKY_S
            self.log.info("%s; switching to browser checks for %d hours", info.message(self.display),
                          BROWSER_STICKY_S // 3600)
            return self._via_browser(url)
        self._raise(info, _retry_after(resp) if info.kind == "rate_limit" else None)
        raise AssertionError("unreachable")

    def _via_browser(self, url: str) -> FetchResult:
        try:
            res = self.browser.fetch(url)  # type: ignore[union-attr]
        except BrowserUnavailable as exc:
            raise Blocked(f"{self.display}: {exc}", 1800) from exc
        self.last_via = "browser"
        if res.waiting_for_human:
            raise Blocked(f"{self.display}: waiting for you to finish the check in the browser window",
                          60, waiting_for_human=True)
        if res.block and res.block.kind != "queue":
            self._raise(res.block)
        return res

    def get_json(self, url: str, **kw: Any) -> Any:
        resp = self.get(url, expect_json=True, **kw)
        if resp.status_code == 404:
            return None
        try:
            data = resp.json()
        except ValueError as exc:
            info = classify(403, resp.text, resp.headers)
            if info:
                self._raise(info)
            raise ConnectionError(f"{self.display}: response was not JSON ({resp.status_code})") from exc
        self.dump(url.rsplit("/", 1)[-1], data)
        return data

    def dump(self, label: str, data: Any, force: bool = False) -> None:
        """Save a raw response to data/debug for troubleshooting: always when
        force is set (something came back empty), otherwise only with debug_dump on."""
        if not (force or self.cfg.settings.get("debug_dump")):
            return
        folder = os.path.join(self.cfg.data_dir, "debug")
        os.makedirs(folder, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{self.name}_{label}")[:80]
        path = os.path.join(folder, f"{safe}.json" if not isinstance(data, str) else f"{safe}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data, indent=2))

    @staticmethod
    def pause(seconds: float) -> None:
        time.sleep(seconds)


def _retry_after(resp: requests.Response) -> float:
    value = resp.headers.get("Retry-After")
    try:
        return max(float(value), 30.0) if value else PAUSE_FOR["rate_limit"]
    except ValueError:
        return PAUSE_FOR["rate_limit"]
