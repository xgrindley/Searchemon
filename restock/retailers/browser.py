"""Real-browser checking for sites that turn away plain requests.

Runs Microsoft Edge (built into Windows) or Chrome through Playwright with its
own profile in data/browser-profile, loading product pages the way you would.
It does not disguise itself: no fingerprint spoofing, no CAPTCHA-solving
services, no proxy rotation. When a site wants a human check, the window comes
on screen, you solve it once, and the cookies it sets let checking continue.

All Playwright calls happen on one dedicated thread, because Playwright's sync
API is not thread-safe. Retailer threads hand it jobs and wait for results.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from .blocks import BlockInfo, classify

OFFSCREEN = -32000
HUMAN_WAIT_REMIND_S = 1800
SAME_SITE_GAP_S = 3.0


class BrowserUnavailable(Exception):
    pass


@dataclass
class FetchResult:
    status: int
    text: str
    url: str
    block: BlockInfo | None = None
    waiting_for_human: bool = False
    via: str = "direct"
    profile: str = ""


def playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


class BrowserWorker:
    def __init__(self, raw_cfg: dict, data_dir: str, log: logging.Logger,
                 on_human: Callable[[str, str, BlockInfo], None] | None = None,
                 on_verified: Callable[[str], None] | None = None,
                 name: str = "edge", channel: str = "", cdp_url: str = "", profile_dir: str = ""):
        self.bcfg = raw_cfg.get("browser") or {}
        self.name = name
        self.channel = channel
        self.cdp_url = cdp_url
        self.profile_dir = profile_dir or os.path.join(data_dir, "browser-profile")
        self.log = log
        self.on_human = on_human or (lambda *a: None)
        self.on_verified = on_verified or (lambda *a: None)
        self.jobs: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.start_lock = threading.Lock()
        self.failed = ""                 # set if the browser could not start
        self.pages: dict = {}            # domain -> Page used for checks
        self.pending: dict[str, dict] = {}  # domain -> {"page", "since", "url", "reminded"}
        self.last_load: dict[str, float] = {}
        self.closed = False              # the window or browser was closed by hand
        self.on_reopen: Callable[[], None] | None = None

    # ---- availability ---------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.bcfg.get("enabled", True))

    @property
    def usable(self) -> bool:
        return self.enabled and playwright_installed() and not self.failed

    @property
    def keep_hidden(self) -> bool:
        return not self.bcfg.get("show_window", False)

    def waiting_domains(self) -> list[dict]:
        return [{"domain": d, "url": p["url"], "since": p["since"]} for d, p in list(self.pending.items())]

    # ---- public API (any thread) ---------------------------------------------------
    def fetch(self, url: str, timeout: float = 120, ask: bool = True) -> FetchResult:
        res = self._submit(lambda: self._fetch(url, ask), timeout)
        res.profile = self.name
        return res

    def show_window(self) -> None:
        """Bring the checking browser on screen, starting it if needed (e.g. to pick your Walmart store)."""
        if self.usable:
            self._submit(self._show_any, 60)

    def open_url(self, url: str) -> None:
        """Open a page on screen in the checking browser, for example to sign in to
        your own store account. It gets its own tab, so checks never navigate it away."""
        if self.usable:
            self._submit(lambda: self._open(url), 90)

    def stop(self) -> None:
        if self.thread and self.thread.is_alive():
            self.jobs.put(None)
            self.thread.join(timeout=15)

    def _submit(self, fn, timeout: float):
        if not self.usable:
            raise BrowserUnavailable(self.failed or "Browser checking is off or Playwright is not installed")
        with self.start_lock:
            if not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._run, daemon=True, name="browser")
                self.thread.start()
        fut: Future = Future()
        self.jobs.put((fn, fut))
        return fut.result(timeout=timeout)

    # ---- browser thread ---------------------------------------------------------------
    def _run(self) -> None:
        pw = ctx = None
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            ctx = self._launch(pw)
            self.ctx = ctx
            self.log.info("Browser '%s' started (%s)", self.name,
                          "attached over DevTools" if self.cdp_url else (self.channel or "msedge"))
        except Exception as exc:
            self.failed = f"Browser could not start: {exc.__class__.__name__}: {str(exc).splitlines()[0][:160]}"
            self.log.warning(self.failed)
            while True:  # fail any queued jobs so callers do not hang
                try:
                    job = self.jobs.get(timeout=1)
                except queue.Empty:
                    break
                if job:
                    job[1].set_exception(BrowserUnavailable(self.failed))
            if pw:
                pw.stop()
            return

        self._watch_close(ctx)
        while True:
            job = self.jobs.get()
            if job is None:
                break
            fn, fut = job
            if not fut.set_running_or_notify_cancel():
                continue
            if self.closed:
                ctx = self._reopen(pw, ctx)
            try:
                fut.set_result(fn())
            except Exception as exc:
                if "has been closed" in str(exc):
                    # Someone closed the window mid-check. Reopen for the next job.
                    self.closed = True
                fut.set_exception(exc)
        try:
            ctx.close()
        except Exception:
            pass
        finally:
            pw.stop()

    def _watch_close(self, ctx) -> None:
        self.closed = False
        try:
            ctx.on("close", lambda *_: setattr(self, "closed", True))
        except Exception:
            pass

    def _reopen(self, pw, old_ctx):
        """The checking browser was closed (usually its window): start it again."""
        try:
            old_ctx.close()
        except Exception:
            pass
        self.pages.clear()
        self.pending.clear()
        try:
            ctx = self._launch(pw)
        except Exception as exc:
            self.log.warning("Could not reopen the checking browser: %s", exc)
            return old_ctx
        self.ctx = ctx
        self._watch_close(ctx)
        self.log.info("The checking browser was closed, so it was reopened. Minimize it instead of closing it.")
        if self.on_reopen:
            self.on_reopen()
        return ctx

    def _launch(self, pw):
        if self.cdp_url:
            # Attach to a Chrome you started yourself with --remote-debugging-port, using its real profile.
            browser = pw.chromium.connect_over_cdp(self.cdp_url)
            return browser.contexts[0] if browser.contexts else browser.new_context()
        os.makedirs(self.profile_dir, exist_ok=True)
        channel = (self.channel or self.bcfg.get("channel") or "msedge").lower()
        args = ["--window-size=1280,900"]
        if self.keep_hidden:
            args.append(f"--window-position={OFFSCREEN},{OFFSCREEN}")
        kwargs = dict(user_data_dir=self.profile_dir, headless=bool(self.bcfg.get("headless", False)),
                      args=args, no_viewport=True, locale="en-US")
        tried = []
        for ch in dict.fromkeys([channel, "msedge", "chrome", "chromium"]):
            try:
                if ch == "chromium":
                    return pw.chromium.launch_persistent_context(**kwargs)
                return pw.chromium.launch_persistent_context(channel=ch, **kwargs)
            except Exception as exc:
                tried.append(f"{ch}: {str(exc).splitlines()[0][:80]}")
        raise RuntimeError("; ".join(tried))

    @staticmethod
    def _html(page) -> str:
        try:
            return page.content()
        except Exception:  # page mid-navigation
            page.wait_for_timeout(1500)
            try:
                return page.content()
            except Exception:
                return ""

    def _page_for(self, domain: str):
        page = self.pages.get(domain)
        if page is None or page.is_closed():
            page = self.ctx.new_page()
            self.pages[domain] = page
        return page

    def _fetch(self, url: str, ask: bool = True) -> FetchResult:
        domain = urlsplit(url).netloc.lower()
        now = time.time()

        pend = self.pending.get(domain)
        if pend:
            # A person was asked to verify on this site. Don't load anything else
            # there until that page is clear; just look at it.
            html = self._html(pend["page"])
            info = classify(200, html) if html else BlockInfo("Generic", "challenge", True)
            if info and info.kind != "queue":
                if now - pend["reminded"] > HUMAN_WAIT_REMIND_S:
                    pend["reminded"] = now
                    self._show(pend["page"])
                    self.on_human(domain, pend["url"], info)
                return FetchResult(0, "", url, info, waiting_for_human=True, via=self.name)
            self.pending.pop(domain, None)
            try:
                pend["page"].close()
            except Exception:
                pass
            self._hide_all()
            self.log.info("%s verified, browser checks resuming", domain)
            self.on_verified(domain)

        gap = SAME_SITE_GAP_S - (now - self.last_load.get(domain, 0))
        if gap > 0:
            time.sleep(gap)

        page = self._page_for(domain)
        resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self.last_load[domain] = time.time()
        try:
            page.wait_for_load_state("load", timeout=10000)
        except Exception:
            pass
        status = resp.status if resp else 0
        headers = resp.headers if resp else {}
        html = self._html(page)
        info = classify(status, html, headers)

        if info and info.kind == "queue":
            return FetchResult(status, html, page.url, info, via=self.name)

        if info and info.kind == "challenge" and not info.needs_human:
            # Many JavaScript checks clear by themselves in a real browser after a few seconds.
            for _ in range(10):
                page.wait_for_timeout(1000)
                html = self._html(page)
                if html and not classify(200, html):
                    info, status = None, 200
                    break

        if info and info.kind != "rate_limit" and ask and self.bcfg.get("ask_me_to_verify", True):
            self.pending[domain] = {"page": page, "since": time.time(), "url": url, "reminded": time.time()}
            self.pages.pop(domain, None)  # keep this tab for the person; checks use a fresh one later
            self._show(page)
            self.on_human(domain, url, info)
            return FetchResult(status, html, page.url, info, waiting_for_human=True, via=self.name)

        return FetchResult(status, html, page.url, info, via=self.name)

    # ---- window placement (Chromium DevTools protocol) -------------------------------
    def _bounds(self, page, bounds: dict) -> None:
        try:
            cdp = page.context.new_cdp_session(page)
            win = cdp.send("Browser.getWindowForTarget")
            cdp.send("Browser.setWindowBounds", {"windowId": win["windowId"], "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds", {"windowId": win["windowId"], "bounds": bounds})
            cdp.detach()
        except Exception as exc:
            self.log.debug("window move failed: %s", exc)

    def _show(self, page) -> None:
        self._bounds(page, {"left": 80, "top": 60, "width": 1280, "height": 900})
        try:
            page.bring_to_front()
        except Exception:
            pass

    def _open(self, url: str) -> None:
        key = "signin:" + urlsplit(url).netloc.lower()
        page = self.pages.get(key)
        if page is None or page.is_closed():
            page = self.ctx.new_page()
            self.pages[key] = page
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            self.log.info("Opening %s: %s", url, exc)
        self._show(page)

    def _show_any(self) -> None:
        page = next((p["page"] for p in self.pending.values()), None) or next(iter(self.pages.values()), None)
        if page is None:
            page = self.ctx.new_page()
            self.pages["about:blank"] = page
        self._show(page)

    def _hide_all(self) -> None:
        if not self.keep_hidden or self.pending:
            return
        page = next(iter(self.pages.values()), None)
        if page is not None:
            self._bounds(page, {"left": OFFSCREEN, "top": OFFSCREEN, "width": 1280, "height": 900})


class BrowserPool:
    """Several checking browsers, each with its own profile and cookies.

    Checks rotate round-robin across the profiles, so each one's session sees
    only a share of the traffic. When a site blocks one profile, that profile
    rests for that site (for as long as the block says, or a default) and the
    others carry on. Every outcome is recorded in the block tracker, so you can
    see which method lasts longest before a site pushes back.

    Profiles come from browser.profiles in config.yaml, for example:
      profiles:
        - {name: edge, channel: msedge}
        - {name: chrome, channel: chrome}
        - {name: my-chrome, cdp_url: "http://127.0.0.1:9222"}
    """

    DEFAULT_REST_S = {"rate_limit": 300, "challenge": 900, "denied": 1800}

    def __init__(self, raw_cfg: dict, data_dir: str, log: logging.Logger,
                 on_human=None, on_verified=None, tracker=None):
        self.bcfg = raw_cfg.get("browser") or {}
        self.log = log
        self.tracker = tracker
        self.rest: dict[tuple[str, str], float] = {}
        self.cursor: dict[str, int] = {}
        self.workers: list[BrowserWorker] = []
        profiles = self.bcfg.get("profiles") or [{"name": "edge", "channel": self.bcfg.get("channel") or "msedge"}]
        seen = set()
        for i, prof in enumerate(profiles):
            if not isinstance(prof, dict):
                continue
            name = "".join(ch for ch in str(prof.get("name") or f"profile{i + 1}") if ch.isalnum() or ch in "-_") or f"p{i}"
            if name in seen:
                continue
            seen.add(name)
            folder = os.path.join(data_dir, "browser-profile" if not self.workers else os.path.join("browser-profiles", name))
            self.workers.append(BrowserWorker(
                raw_cfg, data_dir, log, on_human, on_verified, name=name,
                channel=str(prof.get("channel") or ""), cdp_url=str(prof.get("cdp_url") or ""),
                profile_dir=folder))

    # ---- state the rest of the app reads --------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.bcfg.get("enabled", True))

    @property
    def usable(self) -> bool:
        return self.enabled and any(w.usable for w in self.workers)

    @property
    def failed(self) -> str:
        bad = [w.failed for w in self.workers if w.failed]
        return bad[0] if bad and len(bad) == len(self.workers) else ""

    @property
    def thread(self):
        return next((w.thread for w in self.workers if w.thread and w.thread.is_alive()), None)

    @property
    def on_reopen(self):
        return self.workers[0].on_reopen if self.workers else None

    @on_reopen.setter
    def on_reopen(self, fn) -> None:
        for w in self.workers:
            w.on_reopen = fn

    def waiting_domains(self) -> list[dict]:
        return [d for w in self.workers for d in w.waiting_domains()]

    def names(self) -> list[str]:
        return [w.name for w in self.workers]

    def resting(self) -> list[dict]:
        now = time.time()
        return [{"profile": p, "site": d, "minutes": int((t - now) / 60) + 1}
                for (p, d), t in self.rest.items() if t > now]

    # ---- checking -------------------------------------------------------------------
    def fetch(self, url: str, timeout: float = 120) -> FetchResult:
        domain = urlsplit(url).netloc.lower()
        site = domain.removeprefix("www.")
        now = time.time()
        live = [w for w in self.workers if w.usable]
        if not live:
            raise BrowserUnavailable(self.failed or "Browser checking is off or Playwright is not installed")
        start = self.cursor.get(domain, 0) % len(live)
        order = live[start:] + live[:start]
        ready = [w for w in order if self.rest.get((w.name, domain), 0) <= now
                 and not any(p["domain"] == domain for p in w.waiting_domains())]
        waiting = [w for w in order if any(p["domain"] == domain for p in w.waiting_domains())]
        last: FetchResult | None = None
        for n, w in enumerate(ready):
            res = w.fetch(url, timeout, ask=(n == len(ready) - 1 and not waiting))
            last = res
            blocked = bool(res.block and res.block.kind != "queue")
            if self.tracker:
                self.tracker.record(w.name, site, not blocked, res.block.kind if res.block else "")
            if not blocked:
                self.cursor[domain] = (order.index(w) + 1 + start) % len(live)
                return res
            kind = res.block.kind
            rest = res.block.retry_after or self.DEFAULT_REST_S.get(kind, 900)
            if res.block.hard:
                rest = max(rest, 6 * 3600)
            self.rest[(w.name, domain)] = time.time() + rest
            self.log.info("%s: profile '%s' was blocked (%s); resting it for %d min and trying another",
                          site, w.name, res.block.message(site), rest // 60)
        if last is not None:
            return last
        # Every profile is resting or waiting on a person: report the soonest return.
        if waiting:
            return waiting[0].fetch(url, timeout)
        soonest = min(t for (p, d), t in self.rest.items() if d == domain) - now
        return FetchResult(0, "", url, BlockInfo("Generic", "rate_limit", False, retry_after=max(60, soonest)),
                           via="pool")

    def show_window(self) -> None:
        for w in self.workers:
            w.show_window()

    def open_url(self, url: str) -> None:
        for w in self.workers:
            w.open_url(url)

    def stop(self) -> None:
        for w in self.workers:
            w.stop()
