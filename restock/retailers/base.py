"""Shared HTTP plumbing for every retailer checker."""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from typing import Any
from urllib.parse import urlsplit

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
TRIALS = None   # set by the engine: a trials.TrialPlan (which method each store tries next)

PAGE_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
WARM_EVERY_S = 30 * 60              # how often the "arrive via the front page" method revisits the front page


def set_tracker(tracker) -> None:
    global TRACKER
    TRACKER = tracker


def set_trials(plan) -> None:
    global TRIALS
    TRIALS = plan


class _ArmUnavailable(Exception):
    """A trial method cannot run on this PC (for example a package is missing)."""


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
    page_home = ""                    # the store's own site, where page-fetch loads its data calls from
    search_has_stock = False          # search results already carry online stock
    default_fetch_mode = "direct"     # direct | auto | browser

    def __init__(self, cfg: Config, log: logging.Logger, browser: BrowserWorker | None = None):
        self.cfg = cfg
        self.rcfg = cfg.retailer_cfg(self.name)
        self.log = log
        self.browser = browser
        self.browser_until = 0.0
        self.last_via = "direct"
        self._imp = None                # curl_cffi session for the direct-impersonate trial
        self._h2 = None                 # HTTP/2 client for the direct-h2 trial method
        self._warm_session = None       # its own cookies, so the trial never changes the normal session
        self._warmed: dict[str, float] = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
        })

    # ---- override these -------------------------------------------------
    def setup_needed(self) -> str:
        """A short plain-words note when this store cannot be checked until you add something (a free developer
        key, for example). Empty when it is ready. Such a store is skipped quietly instead of being counted as blocked."""
        return ""

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
        body = "" if expect_json and resp.status_code < 400 else resp.text
        if not body and '"blockScript"' in resp.text[:1500]:
            body = resp.text         # a bot-check page sent as JSON with a normal status (Target does this)
        info = classify(resp.status_code, body, resp.headers)
        if TRACKER:
            TRACKER.record("direct", self.name, info is None or info.kind == "queue", info.kind if info else "")
        if info:
            self._raise(info, _retry_after(resp) if info.kind == "rate_limit" else None)
        if resp.status_code == 503:
            raise ConnectionError(f"{self.display}: temporarily unavailable (503)")
        return resp

    def fetch_html(self, url: str) -> FetchResult:
        """Load a product or search page. A trial plan may hand some checks to a trial method
        (one at a time per store, see trials.py); every other check runs the normal way."""
        family = "browser" if self.using_browser() else "direct"
        arm = TRIALS.arm_for(self.name, family) if TRIALS else None
        if arm is not None and not arm.control:
            res = self._run_arm(arm, url)
            if res is not None:
                return res
        try:
            res = self._fetch_html_normal(url)
        except Blocked as exc:
            if arm is not None and arm.control and not exc.waiting_for_human:
                TRIALS.note(self.name, arm, False, "blocked")
            raise
        if arm is not None and arm.control:
            TRIALS.note(self.name, arm, True)
        return res

    # ---- trial methods ------------------------------------------------------------
    def _run_arm(self, arm, url: str) -> FetchResult | None:
        """Run one trial method. Returns the page, or None to fall back to the normal way
        (the method was blocked, could not run, or hit a network error). A blocked trial
        method rests for this store, so the fallback is a single extra request."""
        if arm.family == "browser":
            return self._browser_arm(arm, url)
        try:
            resp = {"direct-h2": self._h2_get, "direct-impersonate": self._impersonate_get}.get(
                arm.key, self._warm_get)(url)
        except _ArmUnavailable as exc:
            TRIALS.mark_unavailable(arm.key, str(exc))
            TRIALS.skip(self.name, arm, str(exc))
            return None
        except Exception as exc:  # network trouble on the trial path: not a block, so not counted
            self.log.debug("%s: trial '%s' failed to load (%s)", self.display, arm.key, exc.__class__.__name__)
            TRIALS.fail(self.name, arm, exc.__class__.__name__)
            return None
        status, text, headers, final = resp
        info = classify(status, text, headers)
        if info is None and status >= 500:
            TRIALS.skip(self.name, arm, f"server error {status}", minutes=1)
            return None
        ok = info is None or info.kind == "queue"
        TRIALS.note(self.name, arm, ok, info.kind if info else "")
        if not ok:
            self.log.info("%s: trial method '%s' was blocked (%s); using the normal method this time",
                          self.display, arm.key, info.message(self.display))
            time.sleep(random.uniform(3, 8))     # do not hit a store that just refused us with an instant second request
            return None
        self.last_via = "direct"
        return FetchResult(status, text, final, info)

    def _browser_arm(self, arm, url: str) -> FetchResult | None:
        pool = self.browser
        if arm.key == "browser-slow":
            # Same checking as normal; the engine checks this store half as often while it runs.
            try:
                res = self._via_browser(url)
            except Blocked as exc:
                if exc.waiting_for_human:
                    raise
                TRIALS.note(self.name, arm, False, "blocked")
                raise
            TRIALS.note(self.name, arm, True)
            return res
        pick = {"browser-own": "own", "browser-stealth": "stealth"}.get(arm.key, "solo")
        if pick == "stealth":
            from .browser import patchright_installed
            if not patchright_installed():
                msg = "needs a package: run  .\\.venv\\Scripts\\python.exe -m pip install patchright"
                TRIALS.mark_unavailable(arm.key, msg)
                TRIALS.skip(self.name, arm, msg)
                return None
            pool.ensure_stealth()
            if not any(getattr(w, "stealth", False) and w.usable for w in pool.workers):
                TRIALS.skip(self.name, arm, "the stealth browser could not start (see the log)")
                return None
        if pick == "own" and not any(getattr(w, "cdp_url", "") and w.usable for w in pool.workers):
            TRIALS.skip(self.name, arm, "your own Chrome is not running")
            return None
        try:
            res = self._via_browser(url, pick=pick, label=arm.key)
        except Blocked as exc:
            if exc.waiting_for_human:
                raise
            TRIALS.note(self.name, arm, False, "blocked")
            self.log.info("%s: trial method '%s' was blocked; using the normal method this time", self.display, arm.key)
            time.sleep(random.uniform(3, 8))
            return None
        TRIALS.note(self.name, arm, True)
        return res

    def _h2_get(self, url: str) -> tuple:
        if self._h2 is None:
            try:
                import httpx
                self._h2 = httpx.Client(http2=True, follow_redirects=True, timeout=25, headers=self._page_headers())
            except ImportError as exc:
                raise _ArmUnavailable("HTTP/2 needs a package: run  .\\.venv\\Scripts\\python.exe -m pip install \"httpx[http2]\"") from exc
        r = self._h2.get(url)
        return r.status_code, r.text, dict(r.headers), str(r.url)

    def _impersonate_get(self, url: str) -> tuple:
        if self._imp is None:
            try:
                from curl_cffi import requests as cffi
            except ImportError as exc:
                raise _ArmUnavailable("needs a package: run  .\\.venv\\Scripts\\python.exe -m pip install curl_cffi") from exc
            self._imp = cffi.Session(impersonate="chrome")
        r = self._imp.get(url, timeout=25, headers={"Accept-Language": "en-US,en;q=0.9", "Cache-Control": "no-cache"})
        return r.status_code, r.text, dict(r.headers), str(r.url)

    def _warm_get(self, url: str) -> tuple:
        if self._warm_session is None:
            self._warm_session = requests.Session()
            self._warm_session.headers.update(self._page_headers())
        parts = urlsplit(url)
        home = f"{parts.scheme}://{parts.netloc}/"
        if parts.path in ("", "/") and not parts.query:
            r = self._warm_session.get(url, timeout=25)
            return r.status_code, r.text, dict(r.headers), r.url
        if time.time() - self._warmed.get(parts.netloc, 0) > WARM_EVERY_S:
            first = self._warm_session.get(home, timeout=25)
            info = classify(first.status_code, first.text, first.headers)
            if info is not None and info.kind != "queue":
                return first.status_code, first.text, dict(first.headers), first.url
            self._warmed[parts.netloc] = time.time()
            time.sleep(random.uniform(1.5, 4.0))
        r = self._warm_session.get(url, timeout=25, headers={"Referer": home})
        return r.status_code, r.text, dict(r.headers), r.url

    @staticmethod
    def _page_headers() -> dict:
        return {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "DNT": "1", "Accept": PAGE_ACCEPT,
                "Cache-Control": "no-cache", "Pragma": "no-cache"}

    def _fetch_html_normal(self, url: str) -> FetchResult:
        """The app's normal way to load a page: plain request, or the real browser when the site needs it."""
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

    def post_via_browser(self, url: str, payload: dict, referer: str = "") -> FetchResult:
        """POST JSON from inside the store's own page in the checking browser (needed where
        a plain request is refused)."""
        if not (self.browser and self.browser.usable):
            raise Blocked(f"{self.display}: needs the checking browser, which is off", 1800)
        return self._via_browser(url, post=payload, referer=referer)

    def _via_browser(self, url: str, post: dict | None = None, referer: str = "",
                     pick: str = "", label: str = "", wait_re: str = "") -> FetchResult:
        try:
            if post is None:
                extra = {"pick": pick, "label": label} if pick else {}
                if wait_re:
                    extra["wait_re"] = wait_re
                res = self.browser.fetch(url, **extra)  # type: ignore[union-attr]
            else:
                res = self.browser.fetch(url, post=post, referer=referer)  # type: ignore[union-attr]
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
        try:
            resp = self.get(url, expect_json=True, **kw)
        except Blocked as exc:
            data = self._json_via_page(url, kw.get("params"), exc)
            if data is None:
                raise
            return data
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

    def _json_via_page(self, url: str, params: dict | None, blocked: "Blocked") -> Any:
        """Page fetch: a plain data request was refused, so repeat it from inside the store's own
        page in a real browser, the way the store's own scripts do. Returns None when that is not
        possible or fails, and the original block then stands."""
        if (not self.page_home or blocked.waiting_for_human or not (self.browser and self.browser.usable)
                or not self.cfg.raw.get("browser", {}).get("page_fetch", True)):
            return None
        full = requests.Request("GET", url, params=params).prepare().url
        try:
            res = self.browser.fetch(full, referer=self.page_home, page_get=True)  # type: ignore[union-attr]
        except BrowserUnavailable:
            return None
        except Exception as exc:
            self.log.debug("%s page fetch failed: %s", self.display, exc)
            return None
        if res.block and res.block.kind != "queue" or res.status >= 400:
            return None
        try:
            data = json.loads(res.text)
        except ValueError:
            return None
        self.log.info("%s: the plain request was refused; the same call from inside the page worked (%s)",
                      self.display, res.profile or "browser")
        self.last_via = "browser"
        self.dump(url.rsplit("/", 1)[-1], data)
        return data

    def dump(self, label: str, data: Any, force: bool = False) -> None:
        """Save a raw response to data/debug for troubleshooting: always when
        force is set (something came back empty), otherwise only with debug_dump on."""
        if not (force or self.cfg.settings.get("debug_dump")):
            return
        folder = os.path.join(self.cfg.data_dir, "debug")
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{self.name}_{label}")[:80]
        path = os.path.join(folder, f"{safe}.json" if not isinstance(data, str) else f"{safe}.html")
        try:   # troubleshooting copies must never break a check (a locked or full disk)
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(data if isinstance(data, str) else json.dumps(data, indent=2, default=str))
            _trim_debug(folder)
        except (OSError, TypeError, ValueError) as exc:
            self.log.debug("Could not save a debug copy: %s", exc)

    @staticmethod
    def pause(seconds: float) -> None:
        time.sleep(seconds)

    def link_delay(self) -> float:
        """Seconds to wait before moving on to the next page on a store (the "delay between links"
        setting, plus up to half again at random so it never runs on a fixed beat)."""
        try:
            base = float(self.cfg.settings.get("link_delay_seconds", 4) or 0)
        except (TypeError, ValueError):
            base = 4.0
        return random.uniform(base, base * 1.5) if base > 0 else 0.0


DEBUG_KEEP = 150          # newest troubleshooting copies kept in data\debug; older ones are deleted
DEBUG_MAX_AGE_S = 14 * 86400
_last_trim = 0.0


def _trim_debug(folder: str) -> None:
    """Keep data\\debug small and free of old page copies (they can hold store and location details).
    Runs at most every 10 minutes."""
    global _last_trim
    now = time.time()
    if now - _last_trim < 600:
        return
    _last_trim = now
    try:
        files = [os.path.join(folder, f) for f in os.listdir(folder)]
        files = sorted((f for f in files if os.path.isfile(f)), key=os.path.getmtime, reverse=True)
    except OSError:
        return
    for i, f in enumerate(files):
        try:
            if i >= DEBUG_KEEP or now - os.path.getmtime(f) > DEBUG_MAX_AGE_S:
                os.remove(f)
        except OSError:
            pass


def _retry_after(resp: requests.Response) -> float:
    value = resp.headers.get("Retry-After")
    try:
        return max(float(value), 30.0) if value else PAUSE_FOR["rate_limit"]
    except ValueError:
        return PAUSE_FOR["rate_limit"]
