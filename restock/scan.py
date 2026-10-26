"""Find stock near a ZIP: a scan you start by hand.

Type a ZIP and a radius and press Scan. The app asks each store that publishes shelf stock
(Target, Best Buy, Kroger, GameStop, CVS) which stores around that ZIP have your products,
and lists them nearest first. It runs once per press, never on a timer, sends no Discord
alerts, and keeps the results in memory only (nothing is written to disk).

The ZIP and radius are used for this scan only. They do not change your areas or settings.
"""
from __future__ import annotations

import copy
import dataclasses
import threading
import time

from .geo import Area, clean_zip, miles, nearest_area, place_point, zip_place, zip_point
from .models import StockResult
from .retailers import REGISTRY, route_url
from .retailers.base import Blocked
from .tcg import type_settings
from .util import clean_url, normalize_upc

SCAN_STORES = ("target", "bestbuy", "kroger", "gamestop", "cvs")   # the stores that publish shelf stock
MAX_PRODUCTS = 30            # products asked about per store in one scan
CHUNK = 10                   # product ids per request batch
MAX_RADIUS = 100


class ZipScan:
    def __init__(self, mon):
        self.mon = mon
        self.lock = threading.Lock()
        self.cancel_flag = threading.Event()
        self.thread: threading.Thread | None = None
        self.job: dict = {}

    # ---- control -----------------------------------------------------------------
    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, zip_code, radius, stores=None, include_online: bool = False) -> tuple[bool, str]:
        z = clean_zip(zip_code)
        if not z:
            return False, "Enter a 5 digit ZIP code."
        point = zip_point(z)
        if not point:
            return False, "That ZIP was not found. Check it and try again."
        try:
            radius = float(radius)
        except (TypeError, ValueError):
            return False, "Pick a radius."
        radius = max(1.0, min(float(MAX_RADIUS), radius))
        if self.running:
            return False, "A scan is already running."
        wanted = [s for s in (stores or SCAN_STORES) if s in SCAN_STORES] or list(SCAN_STORES)
        self.cancel_flag.clear()
        with self.lock:
            self.job = {
                "zip": z, "place": zip_place(z), "radius": radius, "online": bool(include_online),
                "started": time.time(), "finished": 0, "state": "running", "cancelled": False,
                "stores": {s: {"name": REGISTRY[s].display, "status": "Waiting", "products": 0, "found": 0, "state": "wait"}
                           for s in wanted},
                "rows": [],
            }
        self.thread = threading.Thread(target=self._run, args=(z, point, radius, wanted, bool(include_online)),
                                       name="zip-scan", daemon=True)
        self.thread.start()
        return True, "Scan started."

    def cancel(self) -> None:
        self.cancel_flag.set()

    def snapshot(self) -> dict:
        with self.lock:
            job = copy.deepcopy(self.job)
        job["running"] = self.running
        job["max_radius"] = MAX_RADIUS
        job["available"] = list(SCAN_STORES)
        job["names"] = {s: REGISTRY[s].display for s in SCAN_STORES}
        return job

    # ---- the scan ------------------------------------------------------------------
    def _set(self, store: str, **kw) -> None:
        with self.lock:
            if self.job.get("stores", {}).get(store) is not None:
                self.job["stores"][store].update(kw)

    def _run(self, z: str, point: tuple[float, float], radius: float, stores: list[str], online: bool) -> None:
        mon = self.mon
        try:
            area = Area("Scan", z, radius, point[0], point[1])
            raw = copy.deepcopy(mon.cfg.raw)
            raw["location"] = {"zip": z, "radius_miles": radius}
            raw["settings"]["in_store"] = True
            cfg = dataclasses.replace(mon.cfg, raw=raw, areas=[area])
            workers = [threading.Thread(target=self._one, args=(s, cfg, area, online), daemon=True) for s in stores]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
        except Exception as exc:  # never leave the page spinning
            mon.log.warning("ZIP scan failed: %s", exc)
        finally:
            with self.lock:
                self.job["state"] = "cancelled" if self.cancel_flag.is_set() else "done"
                self.job["cancelled"] = self.cancel_flag.is_set()
                self.job["finished"] = time.time()
                self.job["rows"].sort(key=lambda r: (r["distance"] is None, r["distance"] or 0, r["store"]))

    def _ids(self, r, cfg) -> dict[str, dict]:
        """Product ids to ask this store about: your watchlist first, then what discovery found."""
        mon = self.mon
        out: dict[str, dict] = {}
        for w in mon.cfg.watchlist:
            if not w.enabled or not w.wants(r.name):
                continue
            ident = ""
            for url in w.urls:
                rname, found = route_url(clean_url(url))
                if rname == r.name:
                    ident = found
                    break
            ident = ident or w.ids.get(r.name, "")
            if not ident and w.upc and r.name in ("target", "bestbuy", "walmart"):
                try:
                    ident = mon.resolve(r, w.upc) or ""
                except Exception:
                    ident = ""
            if ident:
                out.setdefault(ident, {"name": w.name, "msrp": w.msrp})
        items = sorted(mon.catalog.tracked(r.name, type_settings(mon.cfg.raw)),
                       key=lambda v: (-(v.get("last_in_stock") or 0) // 3600, v.get("priority", 9), v.get("title", "")))
        for item in items:
            if len(out) >= MAX_PRODUCTS:
                break
            out.setdefault(item["id"], {"name": item.get("title", ""), "msrp": item.get("msrp")})
        return dict(list(out.items())[:MAX_PRODUCTS])

    def _one(self, name: str, cfg, area: Area, online: bool) -> None:
        mon = self.mon
        if name not in mon.cfg.enabled_retailers():
            self._set(name, status="Turned off in Stores & keys" if name != "bestbuy" else "Needs a Best Buy API key",
                      state="skip")
            return
        try:
            r = REGISTRY[name](cfg, mon.log, mon.browser)
            ids = self._ids(r, cfg)
            if not ids:
                self._set(name, status="No products to look for yet. Add some in My products or wait for discovery.",
                          state="skip")
                return
            self._set(name, status=f"Checking {len(ids)} products", products=len(ids), state="run")
            keys = list(ids)
            found = 0
            for i in range(0, len(keys), CHUNK):
                if self.cancel_flag.is_set():
                    self._set(name, status="Cancelled", state="skip")
                    return
                results = r.check_ids(keys[i:i + CHUNK], True)
                for ident, res in results.items():
                    found += self._rows(res, ids.get(ident) or {}, area, cfg, online)
                self._set(name, found=found)
            self._set(name, status=f"Done: {found} store listing(s) with stock" if found else "Done: nothing in stock in range",
                      state="ok" if found else "none")
        except Blocked as exc:
            self._set(name, status=f"Blocked: {exc}", state="bad")
        except Exception as exc:
            mon.log.info("ZIP scan, %s: %s", name, exc)
            self._set(name, status=f"Could not check: {str(exc)[:120]}", state="bad")

    def _rows(self, res: StockResult, meta: dict, area: Area, cfg, online: bool) -> int:
        """Keep stores with stock inside the radius, add them to the results. Returns how many were added."""
        min_qty = int(cfg.settings.get("min_store_qty") or 1)
        excluded = set(cfg.settings.get("excluded_stores") or [])
        msrp = meta.get("msrp") or res.msrp
        tol = float(cfg.settings.get("msrp_tolerance_pct") or 0)
        over = bool(res.price and msrp and res.price > msrp * (1 + tol / 100))
        base = {"retailer": res.retailer, "retailer_name": res.retailer_name, "product": res.title or meta.get("name", ""),
                "url": clean_url(res.url), "price": res.price, "msrp": msrp, "over_msrp": over}
        added = []
        for st in res.stores:
            if f"{st.chain or res.retailer}:{st.store_id}" in excluded:
                continue
            if st.qty is not None and st.qty < min_qty:
                continue
            pt = place_point(st.lat, st.lon, st.zip)
            if pt:
                dist = miles(pt, (area.lat, area.lon))   # type: ignore[arg-type]
                if dist is None or dist > area.radius:
                    continue
            else:
                _, dist = nearest_area(None, [area], st.distance, area)
                if dist is None:
                    continue
            added.append({**base, "store": st.name or f"Store {st.store_id}", "address": st.address,
                          "distance": round(dist, 1) if dist is not None else None,
                          "stock": st.stock_text(), "qty": st.qty, "pickup": st.pickup, "online": False})
        if online and res.online:
            added.append({**base, "store": "Online", "address": "", "distance": None,
                          "stock": res.online_status or "in stock", "qty": None, "pickup": None, "online": True})
        with self.lock:
            self.job["rows"].extend(added)
        return len([a for a in added if not a["online"]])
