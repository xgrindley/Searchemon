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
from .filters import annotate, passes
from .geo import nearest_area, place_point
from .history import History, Schedule
from .places import PlaceFinder
from .models import StockResult
from .notify import DiscordNotifier, Toaster
from .retailers import REGISTRY, route_url
from .retailers.base import Blocked, Retailer
from .retailers.blocks import BlockInfo
from .compare import SideBySide
from .features import FeatureTrial
from .retailers.base import set_tracker, set_trials
from .retailers.browser import BrowserPool
from .sessions import BlockTracker
from .scan import ZipScan
from .accounts import AccountTracker
from .history_store import StoreHistory
from .trials import TrialPlan
from .rules import allow_kind, decide
from .state import StateStore
from .tcg import classify, type_settings
from .util import atomic_write_json, clean_url, normalize_upc, read_json

UPC_RESOLVERS = ("bestbuy", "target", "walmart", "kroger")
MAX_CONFIRMS_PER_CYCLE = 5
CONFIRM_GAP_S = 4
RESOLVE_RETRY_S = 6 * 3600
MAX_BACKOFF_S = 1800
MAX_SLOWDOWN = 8.0


def make_logger(data_dir: str, console: bool = False) -> logging.Logger:
    log = logging.getLogger("restock")
    log.setLevel(logging.INFO)
    if not log.handlers:
        os.makedirs(data_dir, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(data_dir, "restock.log"), maxBytes=1_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        if console:
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
        self._confirms_left = MAX_CONFIRMS_PER_CYCLE
        self._from_upc: set[str] = set()
        self.scan = ZipScan(self)      # the by-hand ZIP stock scan
        self.load()

    # ---- setup ----------------------------------------------------------------
    def load(self) -> None:
        self.cfg: Config = load_config(self.config_path)
        self.store_history = StoreHistory(self.cfg.data_dir)
        self._discovery_tried: set[str] = set()
        self.accounts = AccountTracker(self.cfg.data_dir)
        self._accounts_lock = threading.Lock()
        self.log = make_logger(self.cfg.data_dir, self.console)
        with self.snap_lock:
            self.retailer_status.clear()
        self.notifier = DiscordNotifier(self.cfg.discord, self.log, self.cfg.areas)
        self.toaster = Toaster(bool(self.cfg.settings.get("windows_toast")))
        self.state = StateStore(self.cfg.data_dir)
        self.resolved_path = os.path.join(self.cfg.data_dir, "resolved.json")
        self.resolved: dict = read_json(self.resolved_path, {})
        self.history = History(self.cfg.data_dir)
        self.catalog = Catalog(self.cfg.data_dir)
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
        if getattr(self, "compare", None) is None:
            self.compare = SideBySide(self.cfg.data_dir, self.log, self.browser)
        else:
            self.compare.browser = self.browser
        self.browser.prefer = self.compare.rates
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

    def set_product_status(self, key: str, status: str) -> None:
        self.catalog.set_status(key, status)
        self.info(f"{'Ignoring' if status == 'ignored' else 'Tracking'} {key}")

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
        if (self.cfg.raw.get("browser") or {}).get("notify_discord") and self.notifier.enabled:
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

    def scan_accounts(self) -> None:
        """Look at the cookies the checking browsers have saved and update which accounts are signed in."""
        if not (self.browser and self.browser.usable) or not self._accounts_lock.acquire(blocking=False):
            return
        try:
            for note in self.accounts.update(self.browser.cookie_report()):
                self.info(note)
        except Exception as exc:
            self.log.debug("Account check failed: %s", exc)
        finally:
            self._accounts_lock.release()

    def _accounts_loop(self, stop: threading.Event) -> None:
        if stop.wait(60):
            return
        while not stop.is_set():
            self.scan_accounts()
            stop.wait(180)

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
        if self.browser:
            self.browser.stopping = True            # no new browsers join while the app is closing
        self.stop()
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
            self.info(f"Monitoring started: {', '.join(r.display for r in self.retailers.values()) or 'no retailers enabled'}")

    def stop(self) -> None:
        with self.run_lock:
            self.stop_event.set()
            for ev in self.wake.values():
                ev.set()
            for t in self.threads:
                t.join(timeout=5)
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
                    for n, h in self.health.items() if h["slow"] > 1.05}
            try:
                os.makedirs(self.cfg.data_dir, exist_ok=True)
                tmp = self._pacing_path() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(rows, fh)
                os.replace(tmp, self._pacing_path())
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
            started = time.time()
            try:
                self._confirms_left = MAX_CONFIRMS_PER_CYCLE
                count = self.run_cycle(r)
                backoff = 0.0
                h["recent"].append(1)
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
                    h["last_block"] = str(exc)
                    h["slow"] = min(MAX_SLOWDOWN, h["slow"] * 2)  # back off harder each time
                    # Normal blocks back off up to 30 min; a hard ban asks for longer and gets it.
                    backoff = max(exc.retry_after, min(backoff * 2 or 120, MAX_BACKOFF_S))
                    backoff *= random.uniform(0.8, 1.2)
                    self.info(f"{exc}. Pausing {r.display} for {int(backoff // 60)} min.")
                    mins = int(backoff // 60)
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
            self.state.save()
            self._save_pacing()
            self.store_history.save()
            delay, notes = self._next_delay(r, h, time.time() - started)
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
                    "(a block or an empty search; see the Methods lab)")
        if not r.supports_search:
            return "No automatic search for this store yet. Add product links (Control panel > My products)"
        return "Product search is off for this store (Stores & keys). Add product links (My products) to check it"

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
        self.resolved[key] = {"id": found, "ts": time.time()}
        atomic_write_json(self.resolved_path, self.resolved)
        if found:
            self.info(f"{retailer.display}: UPC {upc} is item {found}")
        return found

    def _discovery_on(self, r: Retailer) -> bool:
        d = self.cfg.raw.get("discovery") or {}
        return bool(d.get("enabled", True)) and r.supports_search and r.name in (d.get("retailers") or [])

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
            n = int((d.get("items_per_cycle") or {}).get(r.name, 6))
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
            self.localize(res)
        if results and getattr(self, "compare", None):
            sample = next((x.url for x in results.values() if x.url and x.url.startswith("http")), "")
            if sample and r.name not in ("target", "bestbuy", "kroger"):    # these use official or JSON calls, not pages
                self.compare.maybe_run(r.name, sample)
        return results

    def _discover(self, r: Retailer, d: dict) -> None:
        """Search the store's catalog for Pokemon products and remember what it finds."""
        limit = int(self.cfg.settings.get("max_search_results") or 24)
        found: list[StockResult] = []
        for q in d.get("queries") or ["pokemon trading card game"]:
            found.extend(r.search(q, max(limit, 48)))
        if not found:
            found = r.seed_products()
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
        if not self.catalog.tracked(r.name, type_settings(self.cfg.raw)):
            hours = min(hours, 0.5)
        first_try = (self._discovery_on(r) and r.name not in self._discovery_tried
                     and not self.catalog.tracked(r.name, type_settings(self.cfg.raw)))
        if self._discovery_on(r) and (self.catalog.due(r.name, hours) or first_try):
            self._discovery_tried.add(r.name)       # a store with nothing found is tried again after each restart
            try:
                self._discover(r, d)
            except Blocked:
                raise
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
        return count

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

    @staticmethod
    def pause_between_checks() -> None:
        time.sleep(CONFIRM_GAP_S)

    def handle(self, res: StockResult, kw: KeywordFilter | None, search_max: float | None,
               r: Retailer | None = None, check_type: bool = True) -> None:
        s = self.cfg.settings
        annotate(res, self.cfg)
        if res.key in (s.get("ignored_items") or []):
            res.note = "muted"
            self.emit("result", res)
            return
        ok, why = passes(res, self.cfg, kw, search_max, check_type=check_type)
        if res.in_stock and not ok:
            # Track as not-available so it alerts later if it becomes eligible (price drop, etc).
            self.state.evaluate(dataclasses.replace(res, online=False, stores=[]),
                                float(s.get("alert_cooldown_minutes") or 0) * 60, bool(s.get("alert_on_startup")))
            res.note = f"ignored: {why}"
            self.emit("result", res)
            return

        if res.in_stock:
            res = self._confirm(res, r)
        self.catalog.note_stock(res)
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
                sent = self.notifier.restock(res, change.reason, rule.store_ids, rule.ping) if self.notifier.enabled else False
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
        sources = [r.stores_near for name, r in self.retailers.items() if name in ("target", "bestbuy", "kroger", "walgreens")]
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
