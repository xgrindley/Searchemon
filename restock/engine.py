"""The monitor: one polling loop per retailer, alerting on stock changes."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import queue
import random
import threading
import time
import traceback
from collections import deque
from logging.handlers import RotatingFileHandler

from .catalog import Catalog
from .config import Config, KeywordFilter, Watch, load_config, save_config, validate
from .filters import annotate, display_msrp, passes
from .geo import nearest_area, place_point
from .history import History, Schedule
from .places import PlaceFinder
from .models import StockResult
from .notify import DiscordNotifier, Toaster, web_link
from .retailers import REGISTRY, route_url
from .retailers.base import Blocked, Retailer
from .retailers.blocks import BlockInfo
from .compare import SideBySide
from .features import FeatureTrial
from .retailers.base import set_proxies, set_tracker, set_trials
from . import captcha as captcha_mod
from .network import ProxyPool, VpnSwitch
from .retailers.browser import BrowserPool
from .sessions import BlockTracker
from .scan import ZipScan
from .sellers import SellerWatch
from .community import Community
from .stockwatch import StockWatch, fmt_minutes
from .review import ReviewQueue
from .market import Market, ebay_cfg
from .catalog import reviewable
from .accounts import AccountTracker
from .history_store import StoreHistory
from .trials import TrialPlan
from .rules import allow_kind, decide
from .state import StateStore
from .tcg import classify, type_settings
from .util import atomic_write_json, clean_url, normalize_text, normalize_upc, read_json

UPC_RESOLVERS = ("bestbuy", "target", "walmart", "kroger")
DISCOVER_REST_S = 2 * 3600
MAX_CONFIRMS_PER_CYCLE = 5
CONFIRM_GAP_S = 4
RESOLVE_RETRY_S = 6 * 3600
MAX_BACKOFF_S = 1800
MAX_SLOWDOWN = 8.0
TYPE_QUERIES = ("pokemon elite trainer box", "pokemon booster bundle", "pokemon booster box", "pokemon collection box",
                "pokemon tin", "pokemon blister", "pokemon premium collection", "pokemon booster pack",
                "pokemon ex box", "pokemon mini tin", "pokemon build and battle", "pokemon binder collection",
                "pokemon illustration collection", "pokemon poster collection")


def make_logger(data_dir: str, console: bool = False) -> logging.Logger:
    log = logging.getLogger("restock")
    log.setLevel(logging.INFO)
    path = os.path.abspath(os.path.join(data_dir, "restock.log"))
    for old in [h for h in log.handlers if isinstance(h, RotatingFileHandler)]:
        if os.path.abspath(old.baseFilename) != path:     # the config moved: log next to the new one
            log.removeHandler(old)
            old.close()
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        os.makedirs(data_dir, exist_ok=True)
        fh = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        if console and not any(type(h) is logging.StreamHandler for h in log.handlers):
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
            log.addHandler(ch)
    return log


class Monitor:
    def __init__(self, config_path: str, events: "queue.Queue | None" = None, console: bool = False):
        self.config_path = config_path
        self.events = events
        self.console = console
        self.threads: list[threading.Thread] = []
        self.stop_event = threading.Event()
        self.wake: dict[str, threading.Event] = {}
        self.run_lock = threading.RLock()        # start/stop/reload one at a time
        self._reload_wanted = False
        self._reload_thread: threading.Thread | None = None
        # Live snapshot read by the control panel.
        self.snap_lock = threading.Lock()
        self.latest: dict[str, tuple[float, StockResult]] = {}
        self.alert_log: deque = deque(maxlen=100)
        self.activity: deque = deque(maxlen=300)
        self.retailer_status: dict[str, str] = {}
        self.health: dict[str, dict] = {}
        self._close_lock = threading.Lock()
        self._closed = False
        self.human_checks: dict[str, dict] = {}
        self._pacing_lock = threading.Lock()
        self.browser: BrowserPool | None = None
        self.tracker: BlockTracker | None = None
        self.trials: TrialPlan | None = None
        self.queue_state: dict[str, dict] = {}
        self._tl = threading.local()   # per-store-thread: confirm budget and ids found by UPC this cycle
        self._discover_gate = threading.Semaphore(2)
        self._type_turn: dict[str, int] = {}
        self.panel_base = ""          # the control panel's address, set by the panel (for Accept / Mute links)
        self._discover_rest: dict[str, float] = {}   # store -> no searches before this time (its search was refused)
        self.scan = ZipScan(self)      # the by-hand ZIP stock scan
        self.load()

    # Each store's loop runs in its own thread. These two values belong to one cycle of one store, so they are
    # kept per thread; shared, one store's cycle could reset them while another store was using them.
    @property
    def _confirms_left(self) -> int:
        return getattr(self._tl, "confirms_left", MAX_CONFIRMS_PER_CYCLE)

    @_confirms_left.setter
    def _confirms_left(self, value: int) -> None:
        self._tl.confirms_left = value

    @property
    def _from_upc(self) -> set:
        if not hasattr(self._tl, "from_upc"):
            self._tl.from_upc = set()
        return self._tl.from_upc

    @_from_upc.setter
    def _from_upc(self, value: set) -> None:
        self._tl.from_upc = value

    # ---- setup ----------------------------------------------------------------
    def load(self) -> None:
        self.cfg: Config = load_config(self.config_path)
        # Saving settings reloads. What the app has learned while running (which stock it already saw and
        # alerted on, the product list, sign-ins, cooldowns) is kept, so a save never re-sends alerts or
        # re-posts status messages. Only a different data folder starts fresh.
        fresh = getattr(self, "_data_dir", None) != self.cfg.data_dir
        self._data_dir = self.cfg.data_dir
        if fresh:
            self._status_lock = threading.Lock()
            self._accounts_lock = threading.Lock()
            self._resolved_lock = threading.Lock()
            self._discovery_tried: set[str] = set()
            self._status_sent: dict[tuple[str, str], float] = {}
            self.store_history = StoreHistory(self.cfg.data_dir)
            self.accounts = AccountTracker(self.cfg.data_dir)
            self.state = StateStore(self.cfg.data_dir)
            self.resolved_path = os.path.join(self.cfg.data_dir, "resolved.json")
            self.resolved: dict = read_json(self.resolved_path, {})
            self.history = History(self.cfg.data_dir)
            self.catalog = Catalog(self.cfg.data_dir)
            self.sellers = SellerWatch(self.cfg.data_dir)
            self.stockwatch = StockWatch(self.cfg.data_dir)
            self.review = ReviewQueue(self.cfg.data_dir)
            self.catalog.review = self.review
        else:
            self._discovery_tried.clear()       # settings changed: let discovery try again with them
        self.log = make_logger(self.cfg.data_dir, self.console)
        if fresh or not hasattr(self, "market"):
            from .util import app_version as _v
            self.market = Market(self.cfg.raw, self.cfg.data_dir, self.log, _v() or "5")
        self.market.attach(self.cfg.raw, getattr(self, "browser", None))
        self.market.log = self.log
        if fresh or not hasattr(self, "community"):
            from .util import app_version
            self.community = Community(self.cfg.data_dir, self.log, app_version() or "4")
        self.community.log = self.log
        with self.snap_lock:
            self.retailer_status.clear()
        self.notifier = DiscordNotifier(self.cfg.discord, self.log, self.cfg.areas)
        self.toaster = Toaster(bool(self.cfg.settings.get("windows_toast")))
        self.places = PlaceFinder(self.cfg.data_dir, self.log)
        self.places.assign(self.cfg.areas)
        self.schedule = Schedule(self.cfg.raw, self.history)
        if self.tracker is None:
            self.tracker = BlockTracker(self.cfg.data_dir)
            self.tracker.on_record = lambda method, site, ok, kind: self.store_history.record_method(method, ok)
            set_tracker(self.tracker)
        if self.trials is None:
            self.trials = TrialPlan(self.cfg.raw, self.cfg.data_dir, self.log, self.tracker)
            set_trials(self.trials)
            self.trials.on_event = self._trial_event
        else:
            self.trials.attach(self.cfg.raw)
        if self.browser is None:
            # The checking browsers (one per profile) are kept across settings reloads.
            # Each only launches the first time a site actually needs it.
            self.browser = BrowserPool(self.cfg.raw, self.cfg.data_dir, self.log,
                                       on_human=self._human_needed, on_verified=self._human_done,
                                       tracker=self.tracker)
            self.browser.on_reopen = self._browser_reopened
        else:
            self.browser.raw = self.cfg.raw
        self.market.browser = self.browser
        if getattr(self, "compare", None) is None:
            self.compare = SideBySide(self.cfg.data_dir, self.log, self.browser)
        else:
            self.compare.browser = self.browser
        self.browser.prefer = self.compare.rates
        # Other identities and addresses, and the CAPTCHA service (network.py, captcha.py).
        if getattr(self, "proxies", None) is None:
            self.proxies = ProxyPool(self.cfg.raw)
            self.vpn = VpnSwitch(self.cfg.raw, self.log)
            self.solver = captcha_mod.Solver(self.cfg.raw, self.cfg.data_dir, self.log, self.tracker)
        else:
            self.proxies.attach(self.cfg.raw)
            self.vpn.raw, self.vpn.log = self.cfg.raw, self.log
            self.solver.attach(self.cfg.raw)
        set_proxies(self.proxies)
        captcha_mod.SOLVER = self.solver
        if getattr(self, "trial", None) is None:
            self.trial = FeatureTrial(self.cfg.data_dir, lambda: self.cfg.raw)
        self.browser.trial = self.trial
        self.retailers: dict[str, Retailer] = {
            name: REGISTRY[name](self.cfg, self.log, self.browser) for name in self.cfg.enabled_retailers()
        }
        for problem in validate(self.cfg):
            self.info(f"Config: {problem}")

    def emit(self, *event) -> None:
        kind, now = event[0], time.time()
        with self.snap_lock:
            if kind == "result":
                self.latest[event[1].key] = (now, event[1])
            elif kind == "alert":
                res = event[1]
                pts = []
                for st in res.stores:
                    pt = place_point(st.lat, st.lon, st.zip)
                    pts.append({"id": st.store_id, "name": st.name, "pickup": bool(st.pickup),
                                "point": [pt[0], pt[1]] if pt else None})
                self.alert_log.appendleft({
                    "time": now, "retailer": res.retailer_name, "title": res.title,
                    "url": clean_url(res.url), "reason": event[2], "sent": event[3],
                    "price": res.price, "key": res.key, "online": res.online,
                    "points": pts if (pts and not res.online) else None,
                })
            elif kind == "status":
                self.retailer_status[event[1]] = event[2]
            elif kind == "log":
                self.activity.appendleft({"time": now, "msg": event[1]})
            elif kind == "new_listing":
                item = event[1]
                self.alert_log.appendleft({
                    "time": now, "retailer": item["retailer_name"], "title": item["title"],
                    "url": clean_url(item["url"]), "reason": f"new listing ({item.get('type_label') or 'Pokemon product'})",
                    "sent": self.notifier.enabled, "price": item.get("price"), "key": f"{item['retailer']}:{item['id']}",
                    "kind": "new",
                })
            elif kind == "queue":
                sig = event[1]
                self.alert_log.appendleft({
                    "time": now, "retailer": sig["display"], "title": f"{sig['display']} queue is open",
                    "url": sig["url"], "reason": "drop likely starting", "sent": event[2], "price": None,
                    "key": f"queue:{sig['site']}", "kind": "queue",
                })
        if self.events is not None:
            self.events.put(event)

    # ---- live settings changes from the control panel -----------------------------
    def save_settings(self, raw: dict) -> None:
        """Validate and write new settings, then restart polling with them."""
        # Mutes and pause are changed by their own buttons; never let a stale page undo them.
        raw = dict(raw)
        raw["settings"] = dict(raw.get("settings") or {})
        raw["settings"]["ignored_items"] = list(self.cfg.settings.get("ignored_items") or [])
        raw["settings"]["alerts_paused"] = bool(self.cfg.settings.get("alerts_paused"))
        raw["settings"]["excluded_stores"] = list(self.cfg.settings.get("excluded_stores") or [])
        # The VPN reconnect command runs a program, so it is only ever set in config.yaml, never from the panel.
        raw["network"] = dict(raw.get("network") or {}) if isinstance(raw.get("network"), dict) else {}
        raw["network"]["vpn_reconnect_command"] = str((self.cfg.raw.get("network") or {}).get("vpn_reconnect_command") or "")
        save_config(self.config_path, raw, backup_dir=self.cfg.data_dir)
        self.info("Settings saved")
        self.request_reload()

    def set_paused(self, paused: bool) -> None:
        self.cfg.raw["settings"]["alerts_paused"] = bool(paused)
        save_config(self.config_path, self.cfg.raw, backup_dir=self.cfg.data_dir)
        self.info("Alerts paused (still checking)" if paused else "Alerts resumed")

    def set_muted(self, key: str, muted: bool) -> None:
        items = list(self.cfg.raw["settings"].get("ignored_items") or [])
        if muted and key not in items:
            items.append(key)
        elif not muted:
            items = [k for k in items if k != key]
        self.cfg.raw["settings"]["ignored_items"] = items
        save_config(self.config_path, self.cfg.raw, backup_dir=self.cfg.data_dir)
        self.info(f"{'Muted' if muted else 'Unmuted'} {key}")

    def set_store_excluded(self, key: str, excluded: bool) -> None:
        items = [k for k in (self.cfg.raw["settings"].get("excluded_stores") or []) if k != key]
        if excluded:
            items.append(key)
        self.cfg.raw["settings"]["excluded_stores"] = items
        save_config(self.config_path, self.cfg.raw, backup_dir=self.cfg.data_dir)
        self.info(f"{'Skipping' if excluded else 'Checking'} store {key}")

    def set_product_status(self, key: str, status: str) -> int:
        n = self.catalog.set_status(key, status)
        title = (self.catalog.items.get(key) or {}).get("title") or key
        self.info(f"{'Ignoring' if status == 'ignored' else 'Tracking'} {title[:70]}"
                  + (f" at {n} listing{'s' if n != 1 else ''}" if n > 1 else ""))
        return n

    def info(self, msg: str) -> None:
        self.log.info(msg)
        self.emit("log", msg)

    # ---- human verification (called from the browser thread) ----------------------
    def _human_needed(self, domain: str, url: str, info: BlockInfo) -> None:
        profile = ""
        try:
            profile = next((w["profile"] for w in self.browser.waiting_domains() if w["domain"] == domain), "")
        except Exception:
            pass
        self.human_checks[domain] = {"domain": domain, "url": clean_url(url), "vendor": info.vendor, "since": time.time(),
                                     "profile": profile}
        site = domain.removeprefix("www.")
        where = f"the {profile} browser window" if profile else "the browser window that just opened"
        self.info(f"{site} wants a quick human check. Finish it in {where}.")
        self.toaster.message(f"{site} needs a quick check",
                             "Finish the check in the browser window and restock checks continue.")
        self.status("human", domain, f"Verification needed: {site}",
                    f"{site} wants a quick human check before the monitor can keep checking it. "
                    f"Finish it in {where} on your PC; checks resume by themselves afterwards.", ping=True)
        if not self.notifier.status_enabled and (self.cfg.raw.get("browser") or {}).get("notify_discord") and self.notifier.enabled:
            self.notifier.note(f"{site} wants a human check before the monitor can keep checking it. "
                               "Finish it in the browser window on your PC.")
        self.emit("human_check", domain, url)

    def _human_done(self, domain: str) -> None:
        self.human_checks.pop(domain, None)
        self.info(f"{domain.removeprefix('www.')} verified, checks resumed")
        self.emit("human_done", domain)

    def _browser_reopened(self) -> None:
        for domain in list(self.human_checks):
            self.human_checks.pop(domain, None)
            self.emit("human_done", domain)
        self.info("The checking browser window was closed, so it was reopened. "
                  "Minimize that window instead of closing it.")

    def show_browser(self) -> None:
        def run():
            try:
                self.browser.show_window()
            except Exception as exc:
                self.info(f"Browser: {exc}")
        if self.browser:
            threading.Thread(target=run, daemon=True).start()

    # ---- status channel (everything that is not stock) --------------------------------
    STATUS_KINDS = ("blocked", "recovered", "human", "signin", "autostop", "browser")

    def status(self, kind: str, key: str, title: str, text: str, ping: bool = False) -> None:
        """Post to the status webhook if one is set, this kind is switched on, and the same message about the same
        thing has not been sent within the cooldown. Posting runs in its own thread so a slow Discord never delays checks."""
        d = self.cfg.raw.get("discord") or {}
        if not self.notifier.status_enabled or not (d.get("status_kinds") or {}).get(kind, True):
            return
        now = time.time()
        cooldown = float(d.get("status_cooldown_minutes") or 60) * 60
        with self._status_lock:
            if now - self._status_sent.get((kind, key), 0) < cooldown:
                return
            self._status_sent[(kind, key)] = now
        threading.Thread(target=lambda: self.notifier.status(title, text, kind, ping), daemon=True).start()

    def _trial_event(self, kind: str, arm: str, detail: str) -> None:
        self.status("autostop", arm, f"Method switched off: {arm}",
                    f"The trial method '{arm}' was stopped automatically: {detail}. "
                    "Switch it back on under Advanced > Connection methods if you want to try it again.")

    def _check_browser_problems(self) -> None:
        for w in list(getattr(self.browser, "workers", []) or []):
            if getattr(w, "failed", ""):
                self.status("browser", w.name, f"Checking browser '{w.name}' has a problem",
                            f"{w.failed}\nStores that need a browser will be skipped until it starts.")

    def scan_accounts(self) -> None:
        """Look at the cookies the checking browsers have saved and update which accounts are signed in."""
        if not (self.browser and self.browser.usable) or not self._accounts_lock.acquire(blocking=False):
            return
        try:
            for note in self.accounts.update(self.browser.cookie_report()):
                self.info(note)
            for site, profile in getattr(self.accounts, "last_lost", []):
                self.status("signin", f"{site}:{profile}", f"Sign in needed: {site}",
                            f"The saved {site} sign-in in the '{profile}' browser is gone (expired or signed out). "
                            "Open the control panel, Accounts, and press Sign in for that store.", ping=True)
        except Exception as exc:
            self.log.debug("Account check failed: %s", exc)
        finally:
            self._accounts_lock.release()

    def _accounts_loop(self, stop: threading.Event) -> None:
        if stop.wait(60):
            return
        while not stop.is_set():
            self.scan_accounts()
            self._check_browser_problems()
            stop.wait(180)

    # ---- signals from outside the stores (see community.py) ------------------------------------
    def _community_cfg(self) -> dict:
        c = self.cfg.raw.get("community") or {}
        return c if isinstance(c, dict) else {}

    def _community_loop(self, stop: threading.Event) -> None:
        if stop.wait(45):
            return
        while not stop.is_set():
            try:
                self.community_tick()
            except Exception as exc:          # never let a feed problem stop anything else
                self.log.info("Community tips: %s", exc)
            stop.wait(60)

    def _market_loop(self, stop: threading.Event) -> None:
        if stop.wait(90):
            return
        last = 0.0
        while not stop.is_set():
            c = ebay_cfg(self.cfg.raw)
            if c.get("enabled") and time.time() - last >= max(10, float(c.get("interval_minutes") or 30)) * 60:
                last = time.time()
                try:
                    self.market_tick()
                except Exception as exc:
                    self.log.info("eBay check failed: %s", exc)
            stop.wait(60)

    def wanted_products(self, n: int = 30) -> list[dict]:
        """The products worth pricing on eBay: what the stores list, most wanted types first, ignored ones left out."""
        out, seen = [], set()
        for g in self.catalog.groups():
            if all(l.get("status") == "ignored" for l in g["listings"]) or g.get("priority", 9) > 6:
                continue
            key = normalize_text(g["title"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": g["title"], "msrp": g.get("msrp")})
            if len(out) >= n:
                break
        return out

    def market_tick(self) -> list[dict]:
        self.market.refresh_tcg()
        deals = self.market.check(self.wanted_products())
        if deals:
            self.info(f"eBay: {len(deals)} listing(s) under fair value from low-risk sellers (Products > eBay deals)")
            if self.notifier.ebay_url:
                threading.Thread(target=lambda: self.notifier.ebay(deals), daemon=True).start()
        return deals

    def community_tick(self) -> list[dict]:
        c = self._community_cfg()
        if c.get("new_sets", True):
            self.community.refresh_sets()
        if not c.get("reddit", True):
            return []
        tips = self.community.poll_feed()
        for tip in tips:
            self.use_tip(tip)
        return tips

    def use_tip(self, tip: dict) -> None:
        """A restock post: add a linked product at one of your stores to Found for you, and check the matching
        listings at the stores it names right away (and every cycle for an hour)."""
        stores = [s for s in tip.get("stores") or [] if s in self.retailers]
        added: list[str] = []
        link = tip.get("link") or ""
        if link:
            name, pid = route_url(link)
            if name in self.retailers and name != "web" and pid:
                r = self.retailers[name]
                res = StockResult(name, r.display, str(pid), tip.get("product") or tip.get("title", ""), link,
                                  online_status="UNCHECKED", source="community tip")
                key = f"{name}:{pid}"
                known = key in self.catalog.items
                self.catalog.merge(name, [res], self.cfg.raw, mark_run=False)
                if not known and key in self.catalog.items:
                    self.catalog.items[key]["found_via"] = "community tip"
                    added.append(key)
                if name not in stores:
                    stores.append(name)
        woke = self.catalog.wake_matching(stores, tip.get("product") or tip.get("title", ""))
        for key in added:
            if key not in woke:
                woke.append(key)
                self.catalog.items[key]["next_due"] = 0
        self.community.note_used(tip, len(woke), added)
        names = ", ".join(self.retailers[s].display for s in stores) or "no store you monitor"
        self.info(f"Community tip ({names}): {tip.get('title', '')[:120]}"
                  + (f". Checking {len(woke)} matching listing(s) now." if woke else "."))
        if self._community_cfg().get("discord", False) and self.notifier.status_enabled:
            text = (f"{tip.get('title', '')}\n" + (f"Store link: {web_link(link)}\n" if link else "")
                    + (f"Post: {tip['post']}\n" if tip.get("post") else "")
                    + (f"Checking {len(woke)} matching listing(s) at {names} now." if woke else
                       "None of your found listings match it yet."))
            threading.Thread(target=lambda: self.notifier.status("Community tip", text, "tip"), daemon=True).start()
        for s in stores:
            ev = self.wake.get(s)
            if ev is not None and woke and not (self.health.get(s) or {}).get("block_streak"):
                ev.set()                      # check now, unless that store is pushing back

    def profile_clear_bot(self, profile: str, site: str | None = None) -> tuple[bool, str]:
        """Delete the cookies stores use to remember a bad opinion of a checking browser (Akamai, PerimeterX,
        Cloudflare). Sign-ins stay."""
        if not (self.browser and self.browser.usable):
            return False, "The checking browser is off or not installed."
        ok, msg = self.browser.clear_bot_cookies(profile, site)
        self.info(msg)
        return ok, msg

    def profile_reset(self, profile: str) -> tuple[bool, str]:
        """Delete a checking browser's whole saved profile (cookies, sign-ins, cache). It starts fresh."""
        if not (self.browser and self.browser.usable):
            return False, "The checking browser is off or not installed."
        ok, msg = self.browser.reset_profile(profile)
        if ok:
            self.accounts.forget_profile(profile)
        self.info(msg)
        return ok, msg

    def open_in_browser(self, url: str) -> None:
        """Show a page in the checking browser (used for signing in to store accounts)."""
        def run():
            try:
                self.browser.open_url(url)
            except Exception as exc:
                self.info(f"Browser: {exc}")
            for wait in (20, 30, 45, 90):          # notice the sign-in soon after it happens
                if self.stop_event.wait(wait):
                    return
                self.scan_accounts()
        if self.browser and self.browser.usable:
            threading.Thread(target=run, daemon=True).start()
        else:
            self.info("The checking browser is off or not installed, so there is nothing to sign in to.")

    def close(self) -> None:
        """Stop everything, including every browser window the app opened or joined. Call when the app
        exits. Safe to call more than once."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.store_history.save()
        self.sellers.save()
        self.stockwatch.save()
        if self.browser:
            self.browser.begin_stop()               # no new browsers join; every browser starts closing now
        self.stop(wait=3.0)                          # ...while the checking loops wind down alongside
        if self.browser:
            self.browser.stop()
        if self.tracker:
            self.tracker.save()
        if getattr(self, "trial", None):
            self.trial.save()

    # ---- lifecycle --------------------------------------------------------------
    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self.threads)

    def start(self) -> None:
        with self.run_lock:
            if self.running:
                return
            # Each run gets its own stop signal and wake-ups. A loop still finishing a
            # slow check from the previous run keeps its old, already-set signal and
            # exits afterwards, so restarts never leave two loops checking one store.
            stop = threading.Event()
            self.stop_event = stop
            self.wake = {name: threading.Event() for name in self.retailers}
            self.threads = []
            for i, name in enumerate(self.retailers):
                t = threading.Thread(target=self._loop, args=(name, i * 3, stop, self.wake[name]),
                                     daemon=True, name=f"poll-{name}")
                t.start()
                self.threads.append(t)
            t = threading.Thread(target=self._places_loop, args=(stop,), daemon=True, name="places")
            t.start()
            self.threads.append(t)
            t = threading.Thread(target=self._accounts_loop, args=(stop,), daemon=True, name="accounts")
            t.start()
            self.threads.append(t)
            t = threading.Thread(target=self._community_loop, args=(stop,), daemon=True, name="community")
            t.start()
            self.threads.append(t)
            t = threading.Thread(target=self._market_loop, args=(stop,), daemon=True, name="market")
            t.start()
            self.threads.append(t)
            self.info(f"Monitoring started: {', '.join(r.display for r in self.retailers.values()) or 'no retailers enabled'}")

    def stop(self, wait: float = 5.0) -> None:
        """Stop the checking loops. They are all told at once and share one waiting budget (not `wait` each),
        so many stores no longer add up. A loop still in a slow web request is a daemon thread that finishes
        on its own and checks the stop signal afterwards, so nothing is cut off mid-write."""
        with self.run_lock:
            self.stop_event.set()
            for ev in self.wake.values():
                ev.set()
            deadline = time.time() + wait
            for t in self.threads:
                t.join(timeout=max(0.05, deadline - time.time()))
            self.threads = []
            self.state.save()
        self.info("Monitoring stopped")

    def check_now(self) -> None:
        for ev in self.wake.values():
            ev.set()

    def reload(self) -> None:
        with self.run_lock:
            was_running = self.running
            if was_running:
                self.stop()
            self.load()
            self.emit("reloaded")
            if was_running:
                self.start()

    def request_reload(self) -> None:
        """Reload soon, folding rapid saves into a single restart."""
        with self.run_lock:
            self._reload_wanted = True
            if self._reload_thread and self._reload_thread.is_alive():
                return

            def work():
                time.sleep(1.0)
                while True:
                    with self.run_lock:
                        if not self._reload_wanted:
                            return
                        self._reload_wanted = False
                    try:
                        self.reload()
                    except Exception as exc:
                        self.info(f"Reload failed: {exc}")
            self._reload_thread = threading.Thread(target=work, daemon=True, name="reload")
            self._reload_thread.start()

    def rediscover(self) -> None:
        """Search every store's catalog again on the next check."""
        self.catalog.runs.clear()
        self.catalog.save()
        self.info("Searching stores for Pokemon products now")
        self.check_now()

    def _health(self, name: str) -> dict:
        if name not in self.health:
            hist = self.store_history
            last, _t = hist.last_problem(name)
            self.health[name] = {"recent": deque(hist.recent(name), maxlen=40), "slow": self._saved_slow(name), "blocks": 0,
                                 "last_block": last, "last_ok": hist.last_ok(name), "mode": ""}
        return self.health[name]

    # A store that pushed back stays slowed after a restart, easing off with time, so
    # closing and reopening the app does not start hammering it again at full speed.
    PACING_HALF_LIFE_S = 1800

    def _pacing_path(self) -> str:
        return os.path.join(self.cfg.data_dir, "pacing.json")

    def _saved_slow(self, name: str) -> float:
        try:
            with open(self._pacing_path(), encoding="utf-8") as fh:
                row = json.load(fh).get(name) or {}
            slow = float(row.get("slow", 1.0))
            aged = max(0.0, time.time() - float(row.get("at", 0)))
            return max(1.0, min(MAX_SLOWDOWN, slow * 0.5 ** (aged / self.PACING_HALF_LIFE_S)))
        except (OSError, ValueError, TypeError):
            return 1.0

    def _save_pacing(self) -> None:
        with self._pacing_lock:
            rows = {n: {"slow": round(h["slow"], 3), "at": time.time()}
                    for n, h in list(self.health.items()) if h["slow"] > 1.05}
            try:
                atomic_write_json(self._pacing_path(), rows)
            except OSError:
                pass

    def _next_delay(self, r: Retailer, h: dict, elapsed: float) -> tuple[float, str]:
        """Base interval, sped up in likely restock windows, slowed after pushback."""
        interval = float(r.rcfg.get("interval_seconds") or 120)
        factor, why = self.schedule.factor(r.name)
        interval *= factor * h["slow"]
        floor = self.schedule.min_interval
        if r.using_browser():
            floor = max(floor, float((self.cfg.raw.get("browser") or {}).get("min_interval_seconds") or 120))
        interval = max(interval, floor)
        if r.using_browser() and self.trials:
            interval *= self.trials.interval_factor(r.name)   # the half-pace trial method
        jitter = random.uniform(0, float(self.cfg.raw.get("jitter_seconds") or 0))
        notes = [why] if why else []
        if h["slow"] > 1.05:
            notes.append(f"slowed x{h['slow']:.1f} after pushback")
        return max(interval - elapsed, 10) + jitter, ", ".join(notes)

    def _loop(self, name: str, stagger: float, stop: threading.Event, wake: threading.Event) -> None:
        r = self.retailers[name]
        h = self._health(name)
        backoff = 0.0
        if stop.wait(stagger):
            return
        while not stop.is_set():
            try:
                need = r.setup_needed()
            except Exception:
                need = ""
            if isinstance(need, str) and need:
                # Not a block and not the store's fault: say what is missing and look again later (a save reloads anyway).
                self.emit("status", name, need)
                h["notes"], h["next"] = need, time.time() + 3600
                wake.clear()
                wake.wait(3600)
                continue
            started = time.time()
            try:
                self._confirms_left = MAX_CONFIRMS_PER_CYCLE
                count = self.run_cycle(r)
                backoff = 0.0
                h["recent"].append(1)
                if h.get("block_notified"):
                    h["block_notified"] = False
                    self.status("recovered", name, f"Back to normal: {r.display}",
                                f"{r.display} is loading again after being blocked.")
                h["block_streak"] = 0
                self.store_history.record(name, True, ms=(time.time() - started) * 1000, products=count)
                h["slow"] = max(1.0, h["slow"] * 0.8)   # ease back toward normal speed
                h["last_ok"] = time.time()
                h["mode"] = "browser" if r.last_via == "browser" else "direct"
                status = self._ok_status(r, count)
            except Blocked as exc:
                if exc.waiting_for_human:
                    backoff = exc.retry_after
                    status = "Waiting for you to verify in the browser"
                else:
                    h["recent"].append(0)
                    self.store_history.record(name, False, str(exc), ms=(time.time() - started) * 1000)
                    h["blocks"] += 1
                    h["block_streak"] = h.get("block_streak", 0) + 1
                    h["last_block"] = str(exc)
                    h["slow"] = min(MAX_SLOWDOWN, h["slow"] * 2)  # back off harder each time
                    # Normal blocks back off up to 30 min; a hard ban asks for longer and gets it. A store that keeps
                    # refusing every browser has flagged this connection, and only a longer quiet spell clears that, so
                    # the cap grows with the streak: 30 min, then 1 h, 1.5 h ... up to 3 h.
                    cap = MAX_BACKOFF_S * min(6, max(1, h["block_streak"] - 1))
                    backoff = max(exc.retry_after, min(backoff * 2 or 120, cap))
                    backoff *= random.uniform(0.8, 1.2)
                    if self.vpn.maybe(r.display, h["block_streak"]):
                        backoff = min(backoff, 180)      # a new address from your VPN: try again soon
                        self.info(f"{r.display}: your VPN reconnected after {h['block_streak']} blocks in a row")
                    self.info(f"{exc}. Pausing {r.display} for {int(backoff // 60)} min.")
                    mins = int(backoff // 60)
                    if h["block_streak"] >= int((self.cfg.raw.get("discord") or {}).get("status_block_after") or 3):
                        h["block_notified"] = True
                        self.status("blocked", name, f"{r.display} is blocking the monitor",
                                    f"{h['block_streak']} checks in a row were blocked: {exc}\n"
                                    f"Pausing it for about {max(1, mins)} min. If it keeps happening, open the control panel, "
                                    "Accounts > Browser profiles, and press Clear bot-check cookies for the browser it uses.")
                    status = (f"Blocked, retry in {mins // 60} h {mins % 60} min" if mins >= 120
                              else f"Blocked, retry in {max(1, mins)} min")
            except Exception as exc:  # keep the loop alive no matter what
                if stop.is_set() or "has been closed" in str(exc):
                    # Settings were saved or the app is closing while a browser check was running. That is not
                    # the store's fault, so it is not logged as an error and does not count against its rating.
                    self.log.debug("%s check interrupted: %s", name, exc)
                    if stop.is_set() or stop.wait(15):
                        return
                    continue
                self.log.error("%s cycle failed: %s", name, traceback.format_exc())
                self.emit("log", f"{r.display}: error {exc}")
                h["recent"].append(0)
                self.store_history.record(name, False, f"error: {str(exc)[:80]}")
                status = f"Error: {str(exc)[:60]}"
                backoff = 60
            try:
                self.state.save()
                self._save_pacing()
                self.store_history.save()
                self.sellers.save()
                self.stockwatch.save()
            except Exception as exc:   # a locked or full disk must never stop this store's checks
                self.log.warning("%s: could not save progress: %s", name, exc)
            try:
                delay, notes = self._next_delay(r, h, time.time() - started)
            except (TypeError, ValueError) as exc:   # a bad number in the settings: keep checking at a safe pace
                self.log.warning("%s: bad interval setting (%s), using 2 minutes", name, exc)
                delay, notes = 120.0, ""
            if backoff:
                delay = backoff
            h["next"] = time.time() + delay
            h["notes"] = notes
            if stop.is_set():
                return
            self.emit("status", name, status + (f" ({notes})" if notes and not backoff else ""))
            wake.clear()
            wake.wait(delay)

    def _ok_status(self, r: Retailer, count: int) -> str:
        at = time.strftime("%I:%M %p").lstrip("0")
        if count:
            return f"OK, {count} product{'s' if count != 1 else ''} checked at {at}"
        if r.name == "pokemoncenter" and r.rcfg.get("watch_queue", True):
            return f"OK, watching for the queue (checked {at})"
        if self._discovery_on(r):
            return (f"OK at {at}, searched the store but no Pokemon products found yet "
                    "(the store may be blocking searches; see Advanced > Connection methods)")
        if not r.supports_search:
            return "No automatic search for this store yet. Add product links (Products > Your own links)"
        return "Product search is off for this store (Stores > Stores & keys). Add product links (Products > Your own links) to check it"

    # ---- work --------------------------------------------------------------------
    def resolve(self, retailer: Retailer, upc: str, force: bool = False) -> str | None:
        key = f"{retailer.name}:{normalize_upc(upc)}"
        hit = self.resolved.get(key)
        if not force and hit and (hit.get("id") or time.time() - hit.get("ts", 0) < RESOLVE_RETRY_S):
            return hit.get("id")
        found = None
        try:
            found = retailer.resolve_upc(upc)
        except Blocked:
            raise
        except Exception as exc:
            self.log.warning("UPC lookup %s failed: %s", key, exc)
        with self._resolved_lock:          # several store threads can look up UPCs at once
            self.resolved[key] = {"id": found, "ts": time.time()}
            try:
                atomic_write_json(self.resolved_path, self.resolved)
            except OSError as exc:
                self.log.warning("Could not save UPC lookups: %s", exc)
        if found:
            self.info(f"{retailer.display}: UPC {upc} is item {found}")
        return found

    def _discovery_on(self, r: Retailer) -> bool:
        d = self.cfg.raw.get("discovery") or {}
        if not (d.get("enabled", True) and r.supports_search):
            return False
        if r.name in (d.get("retailers") or []):
            return True
        # Stores with a search page get the same automatic product list, so no links need to be pasted.
        return bool(d.get("cross_store", True)) and bool(getattr(r, "search_url", ""))

    def targets_for(self, r: Retailer) -> dict[str, Watch]:
        """Every product id this retailer should check this cycle, mapped to its watch entry."""
        out: dict[str, Watch] = {}
        self._from_upc = set()
        for w in self.cfg.watchlist:
            for url in w.urls:
                rname, ident = route_url(clean_url(url))
                if rname == r.name:
                    out.setdefault(ident, w)
            if not w.wants(r.name):
                continue
            if w.ids.get(r.name):
                out.setdefault(w.ids[r.name], w)
            elif w.upc and r.name in UPC_RESOLVERS:
                found = self.resolve(r, w.upc)
                if found and found not in out:
                    out[found] = w
                    self._from_upc.add(found)
        if self._discovery_on(r):
            d = self.cfg.raw.get("discovery") or {}
            # Stores read through pages get few found products per check: each costs a page load (and at CVS a
            # shelf lookup per area), and a long list per check is what makes those stores start refusing.
            n = int((d.get("items_per_cycle") or {}).get(r.name, 2 if getattr(r, "search_url", "") else 6))
            types = type_settings(self.cfg.raw)
            for item in self.catalog.rotation(r.name, n, types):
                if item["id"] not in out:
                    out[item["id"]] = Watch(name=f"Found: {item.get('type_label') or 'Pokemon product'}",
                                            msrp=None, in_store=True, auto=True)
        return out

    def localize(self, res: StockResult) -> None:
        """Keep only stores inside one of your areas (and not excluded), with distance from the nearest area."""
        if not res.stores:
            return
        excluded = set(self.cfg.settings.get("excluded_stores") or [])
        min_qty = int(self.cfg.settings.get("min_store_qty") or 1)
        areas = self.cfg.areas
        by_name = {a.name: a for a in areas}
        kept = []
        for st in res.stores:
            chain = st.chain or res.retailer
            if f"{chain}:{st.store_id}" in excluded:
                continue
            if st.qty is not None and st.qty < min_qty:
                continue
            if areas:
                pt = place_point(st.lat, st.lon, st.zip)
                via = by_name.get(st.via_area)
                area, dist = nearest_area(pt, areas, st.distance, via)
                if area is None and pt is None and st.distance is None and via is not None:
                    area, dist = via, None   # the store finder already limited it to this area
                if area is None:
                    continue
                st.area = area.name
                st.distance = round(dist, 1) if dist is not None else st.distance
            kept.append(st)
        kept.sort(key=lambda s: s.distance if s.distance is not None else 999)
        res.stores = kept

    def _check(self, r: Retailer, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        results = r.check_ids(ids, in_store) if ids else {}
        for res in results.values():
            res.stores_checked = bool(in_store and r.supports_in_store and r.in_store_enabled())
            self.localize(res)
        if results and getattr(self, "compare", None):
            sample = next((x.url for x in results.values() if x.url and x.url.startswith("http")), "")
            h = self.health.get(r.name) or {}
            if sample and r.name not in ("target", "bestbuy", "kroger") and self._troubled(r.name) and not h.get("block_streak"):
                # Side-by-side tests load the page through every method at once. That extra traffic only pays off
                # at a store that has pushed back lately (a store that loads fine is left alone), and never while the
                # store is still refusing, when it would only prolong the block.
                self.compare.maybe_run(r.name, sample)
        return results

    def _troubled(self, name: str) -> bool:
        """True when the store was blocked or failed in the last 24 hours."""
        try:
            _why, t = self.store_history.last_problem(name)
            return bool(t) and time.time() - float(t) < 86400
        except Exception:
            return True

    def _discover(self, r: Retailer, d: dict) -> None:
        """Search the store's catalog for Pokemon products and remember what it finds."""
        limit = int(self.cfg.settings.get("max_search_results") or 24)
        found: list[StockResult] = []
        # Your discovery words, plus two product-type searches that rotate each refresh, so a store whose general
        # Pokemon search is thin still turns up its Elite Trainer Boxes, bundles and tins over a few refreshes.
        turn = self._type_turn.get(r.name, 0)
        self._type_turn[r.name] = turn + 2
        extra = [TYPE_QUERIES[(turn + i) % len(TYPE_QUERIES)] for i in range(2)]
        sets = self.community.set_names() if self._community_cfg().get("new_sets", True) else []
        if sets:
            # ...and one of the newest sets by name ("pokemon phantasmal flames"), also rotating.
            extra.append("pokemon " + sets[(turn // 2) % len(sets)].lower())
        queries = list(dict.fromkeys(list(d.get("queries") or ["pokemon trading card game"]) + extra))
        budget = getattr(r, "search_budget", 0)
        budget = budget if isinstance(budget, int) else 0
        if budget and len(queries) > budget:
            start = (turn // 2) % len(queries)
            queries = (queries[start:] + queries[:start])[:budget]     # a few searches per refresh, rotating
        failures = 0
        for q in queries:
            try:
                found.extend(r.search(q, max(limit, 48)))
            except Blocked:
                if not found:
                    raise
                break                     # keep what the earlier searches found
            except Exception as exc:
                failures += 1
                self.log.info("%s search '%s' failed: %s", r.display, q, exc)
        if failures == len(queries):
            raise ConnectionError(f"{r.display}: every product search failed")
        if getattr(r, "search_url", ""):
            # Stores without a product API: also look for what the other stores already list, by UPC or name.
            per = int(d.get("cross_per_refresh", 8))
            if getattr(r, "search_in_browser", False) or getattr(r, "_listing_needs_browser", False):
                per = min(per, 3)               # each of these is a full page load in the browser
            if budget:
                per = min(per, 1)
            for q in self.catalog.cross_queries(r.name, per, use_upc=getattr(r, "search_by_upc", True) is not False):
                try:
                    found.extend(r.search(q, 6))
                except Blocked:
                    raise
                except Exception as exc:
                    self.log.debug("%s lookup of '%s' failed: %s", r.name, q, exc)
        allow = bool(self.cfg.settings.get("allow_non_english"))
        if not any(classify(x.title, allow_non_english=allow).is_tcg for x in found):
            found = found + r.seed_products()
            if found:
                self.info(f"{r.display}: search came back empty, tracking {len(found)} known products instead")
        new = self.catalog.merge(r.name, found, self.cfg.raw, mark_run=True)
        tracked = len(self.catalog.tracked(r.name, type_settings(self.cfg.raw)))
        self.info(f"{r.display}: product discovery found {tracked} Pokemon products"
                  + (f", {len(new)} new" if new else ""))
        if new and d.get("alert_new_listings", True):
            send, ping = allow_kind("new_listing", self.cfg.raw)
            for item in new[:10]:
                self.emit("new_listing", item)
                if send and self.notifier.enabled and not self.cfg.settings.get("alerts_paused"):
                    self.notifier.new_listing(item, ping)

    def run_cycle(self, r: Retailer) -> int:
        count = 0
        d = self.cfg.raw.get("discovery") or {}
        # A store that came back empty is searched again after 30 minutes, not 6 hours.
        hours = float(d.get("refresh_hours") or 6)
        budget = getattr(r, "search_budget", 0)
        budget = budget if isinstance(budget, int) else 0
        if not self.catalog.tracked(r.name, type_settings(self.cfg.raw)):
            # ...except stores that punish bursts of searches (CVS, Walgreens): at most every 3 hours there.
            hours = max(min(hours, 0.5), 3.0 if budget else 0)
        first_try = (self._discovery_on(r) and r.name not in self._discovery_tried
                     and not self.catalog.tracked(r.name, type_settings(self.cfg.raw)))
        rested = time.time() >= self._discover_rest.get(r.name, 0)
        if self._discovery_on(r) and rested and (self.catalog.due(r.name, hours) or first_try):
            self._discovery_tried.add(r.name)       # a store with nothing found is tried again after each restart
            try:
                # At most two stores search at once: at startup every store wants to, and a burst of searches
                # (many through the browser) slows the PC and looks like a bot to the stores.
                with self._discover_gate:
                    if not self.stop_event.is_set():
                        self._discover(r, d)
            except Blocked as exc:
                # A refused search does not stop the product checks (at Walgreens plain product checks load while its
                # searches get refused); searching waits 2 hours, so it stops adding to the store's suspicion.
                self._discover_rest[r.name] = time.time() + DISCOVER_REST_S
                self.info(f"{r.display}: its search was refused ({str(exc)[:90]}). Product checks carry on; "
                          f"searching again in {DISCOVER_REST_S // 3600} hours.")
            except Exception as exc:
                self.log.warning("%s discovery failed: %s", r.name, exc)

        targets = self.targets_for(r)
        if targets:
            want_store = [i for i, w in targets.items() if w.in_store and r.supports_in_store]
            results = self._check(r, want_store, True)
            rest = [i for i in targets if i not in results]
            if rest:
                results.update(self._check(r, rest, False))
            kw = self.cfg.keywords if self.cfg.raw["keywords"].get("apply_to_watchlist") else None
            for ident, res in results.items():
                w = targets.get(ident)
                if w:
                    res.watch_name, res.msrp = (None, None) if w.auto else (w.name, w.msrp)
                    res.source = "auto" if w.auto else "watch"
                    if (ident in self._from_upc and res.upc
                            and normalize_upc(res.upc) != normalize_upc(w.upc)):
                        # The id found for this UPC points at a different product: look it up again.
                        self.resolve(r, w.upc, force=True)
                        res.note = f"ignored: barcode {res.upc} does not match {w.upc}"
                        self.emit("result", res)
                        continue
                self.handle(res, kw, None, r, check_type=w.auto if w else True)
                count += 1

        if self._discovery_on(r) and r.search_has_stock:
            # Stores whose search results carry stock: one search a cycle covers every listing.
            q = (d.get("queries") or ["pokemon trading card game"])[0]
            limit = int(self.cfg.settings.get("max_search_results") or 24)
            results = r.search(q, max(limit, 48))
            self.catalog.merge(r.name, results, self.cfg.raw, mark_run=False)
            seen = set(targets)
            allow = bool(self.cfg.settings.get("allow_non_english"))
            for res in results:
                if res.product_id in seen or res.online_status == "UNCHECKED":
                    continue
                c = classify(res.title, allow_non_english=allow)
                if not c.is_tcg:
                    continue
                res.type_key, res.type_label, res.source = c.type_key, c.type_label, "auto"
                self.localize(res)
                self.handle(res, None, None, None)
                count += 1

        if r.supports_search:
            limit = int(self.cfg.settings.get("max_search_results") or 24)
            for s in self.cfg.searches:
                if r.name not in s.retailers:
                    continue
                kw = self.cfg.keywords.merged(s.keywords)
                matched = []
                for cand in r.search(s.query, limit):
                    cand.source = f"search: {s.name}"
                    ok, _ = passes(cand, self.cfg, kw, s.max_price)
                    if ok and cand.key not in {f"{r.name}:{i}" for i in targets}:
                        matched.append(cand)
                needs_stock = [c for c in matched if c.online_status == "UNCHECKED"]
                if needs_stock or (s.in_store and r.supports_in_store):
                    ids = [c.product_id for c in (needs_stock or matched)][:15]
                    fresh = self._check(r, ids, s.in_store and r.supports_in_store)
                    matched = [fresh.get(c.product_id, c) for c in matched]
                for res in matched:
                    if res.online_status == "UNCHECKED":
                        continue
                    res.source = f"search: {s.name}"
                    self.localize(res)
                    self.handle(res, kw, s.max_price, r)
                    count += 1

        for sig in r.signals():
            self.handle_signal(sig)
        self.catalog.save()
        self.flush_review()
        return count

    # ---- products to review (review.py) ------------------------------------------------------------
    def rediscover_soon(self) -> None:
        """After you accept a product: search the stores again on their next cycle, so it is picked up."""
        self.catalog.runs.clear()
        self._discover_rest.clear()
    def note_skipped(self, retailer: str, res: StockResult, reason: str) -> dict | None:
        if self.review.status_of(res.title) in ("muted", "accepted"):
            return None
        name = self.retailers[retailer].display if retailer in self.retailers else (res.retailer_name or retailer)
        return self.review.add(retailer, name, res.title, clean_url(res.url), reason, res.price)

    def flush_review(self) -> int:
        """Skipped Pokemon merchandise found since the last look: list it, and post the new ones to the review channel."""
        new = []
        for retailer, res, why in self.catalog.take_skipped():
            entry = self.note_skipped(retailer, res, why)
            if entry:
                new.append(entry)
        new += self.__dict__.pop("_review_new", [])
        if new:
            self.review.save()
            base = self.panel_base or "http://127.0.0.1:8765/"
            out = [{"title": e["title"], "reason": e["reason"],
                    "store": ", ".join(st["name"] for st in e["stores"].values()),
                    "url": next(iter(e["stores"].values())).get("url", ""),
                    "price": next(iter(e["stores"].values())).get("price"),
                    "accept": self.review.link(base, e["id"], "accept"), "mute": self.review.link(base, e["id"], "mute")}
                   for e in new]
            if self.notifier.review_url:
                threading.Thread(target=lambda: self.notifier.review(out), daemon=True).start()
            self.info(f"To review: {len(new)} Pokemon product(s) skipped as not card product (Products > To review)")
        return len(new)

    def _sellout_hints(self, res: StockResult) -> None:
        """Put what past restocks say into the alert: how fast each store (and the website) sells out, and which
        store to go to first."""
        if not res.in_stock:
            return
        sw = self.stockwatch
        res.online_hint = sw.hint(res.retailer, "online") if res.online else ""
        timed = []
        for st in res.stores:
            st.hint = sw.hint(res.retailer, f"store:{st.store_id}")
            m, n = sw.sellout_minutes(res.retailer, f"store:{st.store_id}")
            if m is not None and n >= 2:
                timed.append((m, st))
        if len(timed) >= 2:
            timed.sort(key=lambda x: x[0])
            parts = [f"{st.name or 'Store ' + st.store_id} ({fmt_minutes(m)})" for m, st in timed[:3]]
            res.visit_plan = "Go first to the store that sells out fastest: " + ", then ".join(parts) + "."

    def handle_signal(self, sig: dict) -> None:
        if sig.get("kind") != "queue":
            return
        key = f"queue:{sig['site']}"
        was = self.queue_state.get(key, {"active": False, "alerted": 0})
        now = time.time()
        if sig["active"] and not was["active"]:
            self.info(f"{sig['display']} queue is open: a drop is likely starting")
            cooldown = float(self.cfg.settings.get("alert_cooldown_minutes") or 30) * 60
            send, ping = allow_kind("queue", self.cfg.raw)
            if send and now - was["alerted"] >= cooldown and not self.cfg.settings.get("alerts_paused"):
                sent = self.notifier.queue_open(sig, ping) if self.notifier.enabled else False
                self.toaster.message(f"{sig['display']} queue is open", "A drop is likely starting. Open the site to join the line.")
                was["alerted"] = now
                self.emit("queue", sig, sent)
        elif was["active"] and not sig["active"]:
            self.info(f"{sig['display']} queue closed")
        self.queue_state[key] = {"active": bool(sig["active"]), "alerted": was["alerted"]}

    def _confirm(self, res: StockResult, r: Retailer | None) -> StockResult:
        """Look at a fresh restock a second time before alerting, to rule out a one-off glitch."""
        if r is None or not self.cfg.settings.get("confirm_restocks", True):
            return res
        if self._confirms_left <= 0 or not self.state.would_alert(res):
            return res
        self._confirms_left -= 1
        try:
            self.pause_between_checks()
            again = r.check_ids([res.product_id], bool(res.stores)).get(res.product_id)
        except Exception as exc:
            self.log.info("confirm check for %s failed: %s", res.key, exc)
            return res
        if again is None:
            return res
        self.localize(again)
        for attr in ("watch_name", "msrp", "source", "type_key", "type_label"):
            setattr(again, attr, getattr(res, attr))
        again.confirmed = True
        if not again.in_stock:
            self.info(f"{res.retailer_name}: {res.title[:60]} showed stock once, but not on a second look; no alert")
        return again

    def _judge_seller(self, res: StockResult) -> tuple[bool, str]:
        """Record a marketplace seller's price against MSRP and say whether that seller is blocked (see sellers.py)."""
        if not (res.seller and res.third_party and res.price):
            return False, ""
        from .filters import tolerance_pct
        msrp = display_msrp(res, self.cfg)
        if msrp:
            limit = msrp * (1 + tolerance_pct(self.cfg, res.retailer) / 100)
            self.sellers.record(res.retailer, res.seller, res.price, msrp, limit, res.title)
        blocked, why = self.sellers.blocked(res.retailer, res.seller)
        return blocked, why

    @staticmethod
    def pause_between_checks() -> None:
        time.sleep(CONFIRM_GAP_S)

    def handle(self, res: StockResult, kw: KeywordFilter | None, search_max: float | None,
               r: Retailer | None = None, check_type: bool = True) -> None:
        s = self.cfg.settings
        annotate(res, self.cfg)
        try:
            self.stockwatch.observe(res)           # how much each place gets and how fast it goes (stockwatch.py)
        except Exception as exc:
            self.log.debug("stock timeline: %s", exc)
        if res.key in (s.get("ignored_items") or []):
            res.note = "muted"
            self.emit("result", res)
            return
        if not str(res.source or "").startswith("watch") and res.title:
            # Found by a search or automatically, but not card product (a t-shirt, a model kit): no alert, and it goes
            # to To review unless you accepted it there.
            c = classify(res.title, allow_non_english=True)
            if not c.is_tcg and reviewable(c.reason) and not self.review.accepted(res.title):
                entry = self.note_skipped(res.retailer, res, c.reason)
                if entry:
                    self.__dict__.setdefault("_review_new", []).append(entry)
                res.note = f"ignored: {c.reason} (see To review)"
                self.emit("result", res)
                return
        ok, why = passes(res, self.cfg, kw, search_max, check_type=check_type)
        seller_blocked, seller_why = self._judge_seller(res)
        if ok and seller_blocked:
            ok, why = False, f"seller {res.seller} is blocked ({seller_why})"
        if res.in_stock and not ok:
            # Track as not-available so it alerts later if it becomes eligible (price drop, etc).
            self.state.evaluate(dataclasses.replace(res, online=False, stores=[]),
                                float(s.get("alert_cooldown_minutes") or 0) * 60, bool(s.get("alert_on_startup")))
            res.note = f"ignored: {why}"
            # Priced past your limit (or by a blocked seller) counts as a miss, so it is checked less often.
            self.catalog.note_stock(res, over_cap=True)
            self.emit("result", res)
            return

        if res.in_stock:
            res = self._confirm(res, r)
        res.ref_msrp = display_msrp(res, self.cfg)
        self._sellout_hints(res)
        self.catalog.note_stock(res)
        if res.in_stock and self.catalog.boost_siblings(res):
            self.log.debug("%s restocked: its listings at other stores are checked every cycle for 2 hours", res.title[:50])
        change = self.state.evaluate(res, float(s.get("alert_cooldown_minutes") or 0) * 60,
                                     bool(s.get("alert_on_startup")))
        if not change.first_look:
            # Real restocks seen while running feed the restock-time patterns.
            if change.raw_new_online:
                self.history.record(res, None)
            by_id = {st.store_id: st for st in res.stores}
            for sid in change.raw_new_store_ids:
                self.history.record(res, by_id.get(sid))
        self.emit("result", res)
        if change.alert:
            paused = bool(s.get("alerts_paused"))
            rule = decide(res, change.new_online, change.new_store_ids, self.cfg.raw)
            sent = False
            if paused:
                self.info(f"PAUSED, not sent {res.retailer_name}: {res.title} ({change.reason})")
            elif not rule.send:
                self.info(f"Not sent ({rule.why_not}) {res.retailer_name}: {res.title} ({change.reason})")
            else:
                self.info(f"ALERT {res.retailer_name}: {res.title} ({change.reason})")
                self.store_history.note_alert(res.retailer)
                try:
                    sent = self.notifier.restock(res, change.reason, rule.store_ids, rule.ping) if self.notifier.enabled else False
                except Exception as exc:     # never lose a restock to a formatting or network surprise: retried next check
                    self.log.exception("Discord alert failed: %s", exc)
                    sent = False
                if s.get("windows_toast", True):
                    self.toaster.show(res, change.reason)
            wanted = rule.send and not paused and self.notifier.enabled
            if wanted and not sent:
                # Discord did not take it. Don't count it as seen, so the next check tries again.
                if self.state.undo_alert(res, change):
                    self.info(f"Discord did not accept the alert for {res.title[:60]}; will retry on the next check")
                else:
                    self.info(f"Discord still refused the alert for {res.title[:60]}; giving up on this one")
                    self.state.mark_alerted(res, change)
            else:
                self.state.clear_failures(res)
                self.state.mark_alerted(res, change)
            self.emit("alert", res, change.reason if rule.send else f"{change.reason} (not sent: {rule.why_not})", sent)
        elif change.sold_out and s.get("notify_sold_out") and self.notifier.enabled:
            self.notifier.sold_out(res)

    # ---- nearby stores -------------------------------------------------------------
    def places_due(self) -> bool:
        d = self.cfg.raw.get("discovery") or {}
        return bool(d.get("places", True)) and bool(self.cfg.areas) and self.places.stale(self.cfg.areas)

    def refresh_places(self) -> int:
        sources = [r.stores_near for name, r in self.retailers.items()
                   if name in ("target", "bestbuy", "kroger", "walgreens") and not r.setup_needed()]
        n = self.places.refresh(self.cfg.areas, sources)
        self.info(f"Found {n} stores near your areas"
                  + (f" (some sources failed: {self.places.last_error})" if self.places.last_error else ""))
        self.emit("places", n)
        return n

    def _places_loop(self, stop: threading.Event) -> None:
        if stop.wait(20):
            return
        while not stop.is_set():
            if self.places_due():
                try:
                    self.refresh_places()
                except Exception as exc:
                    self.info(f"Store finder: {exc}")
            if stop.wait(3600):
                return

    # ---- one-shot helpers for the command line ------------------------------------
    def run_once(self) -> list[StockResult]:
        collected: list[StockResult] = []
        original = self.emit

        def capture(*event):
            if event[0] == "result":
                collected.append(event[1])
            original(*event)

        self.emit = capture  # type: ignore[method-assign]
        try:
            for r in self.retailers.values():
                try:
                    self._confirms_left = MAX_CONFIRMS_PER_CYCLE
                    self.run_cycle(r)
                except Exception as exc:
                    print(f"  {r.display}: {exc}")
        finally:
            self.emit = original  # type: ignore[method-assign]
            self.state.save()
        return collected
