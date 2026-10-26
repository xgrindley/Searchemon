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

import dataclasses
import importlib.util
import logging
import os
import queue
import random
import socket
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from .blocks import BlockInfo, classify, wants_person

OFFSCREEN = -32000
HUMAN_WAIT_REMIND_S = 1800
SAME_SITE_GAP_S = 1.0   # never load two pages of one store closer together than this


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


def patchright_installed() -> bool:
    """Patchright is a drop-in Playwright build with the automation markers removed (stealth)."""
    return importlib.util.find_spec("patchright") is not None



def _force_foreground(hint: str) -> None:
    """Windows only. Bring the Chrome or Edge window whose title contains `hint` to the front.
    Windows normally refuses to let a background program take focus, so a plain
    bring_to_front only blinks the taskbar; a tapped Alt key lets the switch through."""
    if os.name != "nt" or not hint:
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found: list = []
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, cls, 64)
                size = user32.GetWindowTextLengthW(hwnd)
                if cls.value == "Chrome_WidgetWin_1" and size:
                    title = ctypes.create_unicode_buffer(size + 1)
                    user32.GetWindowTextW(hwnd, title, size + 1)
                    if hint.lower() in title.value.lower():
                        found.append(hwnd)
            return True

        user32.EnumWindows(enum_proc(visit), 0)
        if found:
            hwnd = found[0]
            user32.ShowWindow(hwnd, 9)                 # SW_RESTORE: undo minimized
            user32.keybd_event(0x12, 0, 0, 0)          # Alt down
            user32.SetForegroundWindow(hwnd)
            user32.keybd_event(0x12, 0, 2, 0)          # Alt up
    except Exception:
        pass

OWN_CHROME = "my-chrome"
OWN_EDGE = "my-edge"
# Stores that always try your own Chrome first (added to browser.own_chrome_sites).
DEFAULT_OWN_SITES = ("cvs.com", "dickssportinggoods.com", "gamestop.com")


def _port_open(port: int) -> bool:
    """True when something on this PC is listening on the port (your own Chrome, ready for DevTools)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


class BrowserWorker:
    def __init__(self, raw_cfg: dict, data_dir: str, log: logging.Logger,
                 on_human: Callable[[str, str, BlockInfo], None] | None = None,
                 on_verified: Callable[[str], None] | None = None,
                 name: str = "edge", channel: str = "", cdp_url: str = "", profile_dir: str = "",
                 stealth: bool = False):
        self.stealth = stealth           # runs on patchright instead of playwright; only used by the stealth trial
        self.raw = raw_cfg
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
        self.pages: dict = {}            # domain -> the tab used most recently for that store
        self.tabs: dict[str, list] = {}  # domain -> the tabs its pages rotate through
        self.tab_turn: dict[str, int] = {}
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
        lib = patchright_installed() if self.stealth else playwright_installed()
        return self.enabled and lib and not self.failed

    @property
    def keep_hidden(self) -> bool:
        # An attached Chrome is your own window: never slide it off screen.
        return not self.cdp_url and not self.bcfg.get("show_window", False)

    def waiting_domains(self) -> list[dict]:
        return [{"domain": d, "url": p["url"], "since": p["since"], "profile": self.name}
                for d, p in list(self.pending.items())]

    # ---- public API (any thread) ---------------------------------------------------
    def fetch(self, url: str, timeout: float = 120, ask: bool = True, post: dict | None = None,
              referer: str = "", page_get: bool = False) -> FetchResult:
        """Load a page. With `post` (JSON) or `page_get`, call `url` from inside a page on the
        store's own site, so the site's cookies and session go with it, and return the answer."""
        if post is not None or page_get:
            res = self._submit(lambda: self._in_page("POST" if post is not None else "GET", url, post, referer, ask),
                               timeout)
        else:
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

    def request_stop(self) -> None:
        if self.thread and self.thread.is_alive():
            while True:                       # checks still waiting in line are dropped, not waited for
                try:
                    job = self.jobs.get_nowait()
                except queue.Empty:
                    break
                if job:
                    job[1].set_exception(BrowserUnavailable("The app is closing"))
            self.jobs.put(None)

    def stop(self) -> None:
        self.request_stop()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=15)

    def _close_own_browser(self) -> None:
        """Your own Chrome or Edge (started by start-my-chrome.ps1 / start-my-edge.ps1) belongs to this app:
        close its windows when the app closes. The profile keeps your sign-ins for next time."""
        browser = getattr(self, "_cdp_browser", None)
        if not (self.cdp_url and browser) or not self.bcfg.get("close_own_on_exit", True):
            return
        try:
            browser.new_browser_cdp_session().send("Browser.close")
            self.log.info("Closed '%s' (the app was closed)", self.name)
        except Exception:
            pass     # already closed, or it went away on its own

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
            if self.stealth:
                from patchright.sync_api import sync_playwright
            else:
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
        self._close_own_browser()
        try:
            if not self.cdp_url:
                ctx.close()
        except Exception:
            pass
        finally:
            try:
                pw.stop()
            except Exception:
                pass

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
        self.tabs.clear()
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
            self._cdp_browser = browser
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

    def tab_count(self) -> int:
        if getattr(self, "single_tab", False):       # feature trial: this check runs without tab rotation
            return 1
        try:
            n = int(self.bcfg.get("tabs_per_site", 3))
        except (TypeError, ValueError):
            n = 3
        return max(1, min(6, n))

    def link_gap(self) -> float:
        """Seconds to leave between two page loads on the same store (the delay-between-links
        setting, plus up to half again at random)."""
        try:
            base = float((self.raw.get("settings") or {}).get("link_delay_seconds", 4) or 0)
        except (TypeError, ValueError):
            base = 4.0
        base = max(0.0, min(base, 120.0))
        return random.uniform(base, base * 1.5) if base else 0.0

    def _page_for(self, domain: str):
        """The next tab in this store's rotation. Tabs are opened as needed, up to the
        tabs-per-site setting, so a store's pages are not all loaded in one tab."""
        want = self.tab_count()
        tabs = [t for t in self.tabs.get(domain, []) if not t.is_closed()]
        while len(tabs) > want:
            extra = tabs.pop()
            try:
                extra.close()
            except Exception:
                pass
        if len(tabs) < want:
            page = self.ctx.new_page()
            if self.keep_hidden:
                self._bounds(page, {"left": OFFSCREEN, "top": OFFSCREEN, "width": 1280, "height": 900})
            tabs.append(page)
            turn = len(tabs) - 1
        else:
            turn = self.tab_turn.get(domain, 0) % len(tabs)
        self.tab_turn[domain] = turn + 1
        self.tabs[domain] = tabs
        page = tabs[turn]
        self.pages[domain] = page
        return page

    def _in_page(self, method: str, url: str, payload: dict | None, referer: str, ask: bool = True) -> FetchResult:
        """Call a JSON address from a page on the store's own site, the way the site's own scripts do."""
        domain = urlsplit(referer or url).netloc.lower()
        if domain in self.pending:
            return self._fetch(referer or url, ask)       # a person is still being asked to verify
        gap = max(SAME_SITE_GAP_S, self.link_gap()) - (time.time() - self.last_load.get(domain, 0))
        if gap > 0:
            time.sleep(gap)
        page = self._page_for(domain)
        if urlsplit(page.url).netloc.lower() != domain:
            page.goto(referer or f"https://{domain}/", wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
        same_origin = urlsplit(url).netloc.lower() == domain
        out = page.evaluate(
            """async ([m, u, body, creds]) => {
                 const o = {method: m, credentials: creds, headers: {'accept': 'application/json'}};
                 if (body !== null) { o.headers['content-type'] = 'application/json'; o.body = JSON.stringify(body); }
                 const r = await fetch(u, o);
                 return {status: r.status, text: await r.text()};
               }""", [method, url, payload, "include" if same_origin else "omit"])
        self.last_load[domain] = time.time()
        status, text = int(out.get("status") or 0), out.get("text") or ""
        info = classify(status, text) if status >= 400 or text.lstrip().startswith("<") else None
        return FetchResult(status, text, url, info, via=self.name)

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

        gap = max(SAME_SITE_GAP_S, self.link_gap()) - (now - self.last_load.get(domain, 0))
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

        if wants_person(info) and ask and self.bcfg.get("ask_me_to_verify", True):
            self.pending[domain] = {"page": page, "since": time.time(), "url": url, "reminded": time.time()}
            self.pages.pop(domain, None)  # keep this tab for the person; checks use a fresh one later
            self.tabs[domain] = [t for t in self.tabs.get(domain, []) if t is not page]
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
        if not self.cdp_url:
            self._bounds(page, {"left": 80, "top": 60, "width": 1280, "height": 900})
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            _force_foreground(page.title())
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
        self._raw = raw_cfg
        self._bcfg = raw_cfg.get("browser") or {}
        self._data_dir = data_dir
        self._on_human, self._on_verified = on_human, on_verified
        self._own_looked = 0.0
        self.trial = None             # set by the engine: FeatureTrial, for A/B counts of the app's features
        self.prefer = None            # set by the engine: site -> {method: share of side-by-side runs that loaded}
        self._attach_lock = threading.Lock()
        self.stopping = False
        self.log = log
        self.tracker = tracker
        self.rest: dict[tuple[str, str], float] = {}
        self.cursor: dict[str, int] = {}
        self.workers: list[BrowserWorker] = []
        profiles = list(self.bcfg.get("profiles") or [{"name": "edge", "channel": self.bcfg.get("channel") or "msedge"}])
        port = int(self.bcfg.get("own_chrome_port") or 0)
        if port and not any(isinstance(p, dict) and p.get("cdp_url") for p in profiles) and _port_open(port):
            profiles.append({"name": OWN_CHROME, "cdp_url": f"http://127.0.0.1:{port}"})
            log.info("Your own Chrome is running on port %d, so it joins the checking browsers", port)
        trial = self.raw.get("trials") or {}
        if trial.get("enabled", True) and "browser-stealth" in (trial.get("active") or []) \
                and not any(isinstance(p, dict) and p.get("stealth") for p in profiles):
            profiles.append({"name": "stealth", "channel": "chrome", "stealth": True})
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
                profile_dir=folder, stealth=bool(prof.get("stealth"))))

    # ---- settings reload ---------------------------------------------------------------
    @property
    def bcfg(self) -> dict:
        return self._bcfg

    @bcfg.setter
    def bcfg(self, value: dict) -> None:
        self._bcfg = value
        for w in self.workers:
            w.bcfg = value

    @property
    def raw(self) -> dict:
        return self._raw

    @raw.setter
    def raw(self, value: dict) -> None:
        self._raw = value
        self._bcfg = value.get("browser") or {}
        for w in self.workers:
            w.raw, w.bcfg = value, self._bcfg

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

    # ---- your own Chrome ---------------------------------------------------------------
    def _own_chrome_sites(self) -> list[str]:
        mine = [str(x).lower() for x in (self.bcfg.get("own_chrome_sites") or [])]
        return mine + [d for d in DEFAULT_OWN_SITES if d not in mine]

    def _uses_own_chrome(self, site: str) -> bool:
        return any(site == x or site.endswith("." + x) for x in self._own_chrome_sites())

    def _own_browsers(self) -> list[tuple[str, int, str]]:
        """(profile name, DevTools port, display name) for each of your own browsers that is switched on."""
        out = []
        for name, key, label in ((OWN_CHROME, "own_chrome_port", "Chrome"), (OWN_EDGE, "own_edge_port", "Edge")):
            port = int(self.bcfg.get(key) or 0)
            if port:
                out.append((name, port, label))
        return out

    def _maybe_attach_own_chrome(self) -> None:
        """If you start your own Chrome or Edge after the app is already running, join it here, so
        nothing needs restarting. Looks at most every 15 seconds."""
        with self._attach_lock:
            if self.stopping:
                return
            now = time.time()
            wanted = self._own_browsers()
            if not wanted or now - self._own_looked < 15:
                return
            # A browser that was closed leaves a dead entry behind; drop it so a new one can join.
            self.workers = [w for w in self.workers if not (getattr(w, "cdp_url", "") and w.failed)]
            self._own_looked = now
            for name, port, label in wanted:
                if any(w.name == name for w in self.workers):
                    continue
                if _port_open(port):
                    self._attach_own(port, name, label)

    def _attach_own(self, port: int, name: str = OWN_CHROME, label: str = "Chrome") -> None:
        worker = BrowserWorker(
            self._raw, self._data_dir, self.log, self._on_human, self._on_verified, name=name,
            cdp_url=f"http://127.0.0.1:{port}", profile_dir=os.path.join(self._data_dir, "browser-profiles", name))
        worker.on_reopen = self.on_reopen
        self.workers.append(worker)
        self.log.info("Your own %s is running on port %d, so it joined the checking browsers", label, port)

    # ---- checking -------------------------------------------------------------------
    def fetch(self, url: str, timeout: float = 120, post: dict | None = None, referer: str = "",
              page_get: bool = False, pick: str = "", label: str = "") -> FetchResult:
        """Load a page in one of the checking browsers.

        pick is for trial methods: "solo" stays on one steady profile instead of rotating, "own" uses
        only your own Chrome or Edge, "stealth" uses the stealth profile. label is the name the result
        is recorded under (a trial method's name) instead of the profile's own name."""
        domain = urlsplit(referer or url).netloc.lower()
        site = domain.removeprefix("www.")
        in_page = post is not None or page_get
        extra = {"post": post, "referer": referer, "page_get": page_get} if in_page else {}
        if post is None:
            extra.pop("post", None)
        now = time.time()
        self._maybe_attach_own_chrome()
        # The stealth profile is only for its own trial; normal checks never touch it.
        live = [w for w in self.workers if w.usable and (bool(getattr(w, "stealth", False)) == (pick == "stealth"))]
        if not live:
            raise BrowserUnavailable(self.failed or "Browser checking is off or Playwright is not installed")
        start = self.cursor.get(domain, 0) % len(live)
        order = live[start:] + live[:start]
        use_route = use_tabs = True
        if self.trial and not in_page:
            use_route = self.trial.decide("learned_routing", bool(self.bcfg.get("learn_from_compare", True)))
            use_tabs = self.trial.decide("tab_rotation", int(self.bcfg.get("tabs_per_site", 3) or 1) > 1)
        rates = self.prefer(site) if (self.prefer and not in_page and use_route) else {}
        if rates:
            # What the side-by-side tests found: methods that load this store reliably go first,
            # untested ones keep their turn, methods that are mostly refused go last.
            order.sort(key=lambda w: 0 if rates.get(w.name, 0.5) >= 0.9 else (2 if rates.get(w.name, 0.5) < 0.5 else 1))
        mine = [w for w in live if getattr(w, "cdp_url", "")]
        sites = self._own_chrome_sites()
        if mine and any(site == x or site.endswith("." + x) for x in sites):
            order = mine + [w for w in order if w not in mine]
        ready = [w for w in order if self.rest.get((w.name, domain), 0) <= now
                 and not any(p["domain"] == domain for p in w.waiting_domains())]
        if pick == "stealth":
            pass
        elif pick == "own":
            ready = [w for w in ready if getattr(w, "cdp_url", "")]
        elif pick == "solo":
            steady = [w for w in self.workers if w in ready]
            steady = [w for w in steady if getattr(w, "cdp_url", "")] + [w for w in steady if not getattr(w, "cdp_url", "")] \
                if (mine and any(site == x or site.endswith("." + x) for x in sites)) else steady
            ready = steady[:1]
        waiting = [w for w in order if any(p["domain"] == domain for p in w.waiting_domains())]
        last: FetchResult | None = None
        for n, w in enumerate(ready):
            try:
                w.single_tab = not use_tabs
                res = w.fetch(url, timeout, ask=(n == len(ready) - 1 and not waiting), **extra)
            except Exception as exc:
                if not getattr(w, "cdp_url", ""):
                    raise
                # Your own Chrome was closed or went away. Forget it; it rejoins when it is running again.
                w.failed = f"Your own Chrome is not reachable: {str(exc).splitlines()[0][:100]}"
                self.log.info("Your own Chrome stopped answering (%s); it rejoins when it is running again",
                              str(exc).splitlines()[0][:80])
                continue
            last = res
            blocked = bool(res.block and res.block.kind != "queue")
            if self.trial and not in_page and not pick and not res.waiting_for_human:
                if self.prefer and self.bcfg.get("learn_from_compare", True):
                    self.trial.record("learned_routing", use_route, not blocked)
                if int(self.bcfg.get("tabs_per_site", 3) or 1) > 1:
                    self.trial.record("tab_rotation", use_tabs, not blocked)
            if self.tracker and not label:
                self.tracker.record(w.name + ("+page" if in_page else ""), site, not blocked,
                                    res.block.kind if res.block else "")
            if not blocked:
                if not pick:
                    self.cursor[domain] = (order.index(w) + 1 + start) % len(live)
                return res
            kind = res.block.kind
            rest = res.block.retry_after or self.DEFAULT_REST_S.get(kind, 900)
            if res.block.hard:
                rest = max(rest, 6 * 3600)
            self.rest[(w.name, domain)] = time.time() + rest
            self.log.info("%s: profile '%s' was blocked (%s); resting it for %d min and trying another",
                          site, w.name, res.block.message(site), rest // 60)
        need_own = self._uses_own_chrome(site) and not any(getattr(w, "cdp_url", "") for w in live)
        tip = ("This store usually allows your own Chrome. Start it with start-my-chrome.ps1 "
               "and checks join it within seconds") if need_own else ""
        if last is not None:
            if tip and last.block is not None:
                last.block = dataclasses.replace(last.block, hint=tip)
            return last
        # Every profile is resting or waiting on a person: report the soonest return.
        if waiting:
            return waiting[0].fetch(url, timeout, **extra)
        rests = [t for (p, d), t in self.rest.items() if d == domain]
        soonest = (min(rests) - now) if rests else 60
        return FetchResult(0, "", url, BlockInfo("Generic", "rate_limit", False, retry_after=max(60, soonest), hint=tip),
                           via="pool")

    def show_window(self) -> None:
        """Bring forward the browser that is waiting for you. With nothing waiting, all of them."""
        waiting = [w for w in self.workers if w.waiting_domains()]
        for w in (waiting or self.workers):
            w.show_window()

    def open_url(self, url: str) -> None:
        for w in self.workers:
            w.open_url(url)

    def stop(self) -> None:
        """Close every browser the app opened or joined. All of them are told at once, so closing the
        app does not wait for each one in turn."""
        self.stopping = True
        for w in self.workers:
            w.request_stop()
        deadline = time.time() + 15
        for w in self.workers:
            if w.thread and w.thread.is_alive():
                w.thread.join(timeout=max(0.5, deadline - time.time()))
