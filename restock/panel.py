"""Local web control panel: edit products, searches, filters and alerts from a browser.

By default it only listens on this PC (127.0.0.1). Setting control_panel.allow_lan
lets your phone on the same Wi-Fi reach it, and then a PIN is required.
"""
from __future__ import annotations

import copy
import hmac
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .config import KeywordFilter
from .filters import passes, price_limit
from .geo import clean_zip, geocoder_ready, zip_place, zip_point
from .tcg import TYPES, classify, type_settings
from .models import StockResult
from .panel_page import PAGE
from .retailers.browser import playwright_installed
from .trust import build as trust_build, missing_feeds
from .util import app_version, clean_url, version_label

MAX_BODY = 1_000_000


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the LAN interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def store_domains(name: str) -> tuple[str, ...]:
    """Web domains behind a store name, for matching block statistics."""
    from .retailers import _KROGER_HOSTS, SITE_CLASSES
    fixed = {"target": ("target.com",), "bestbuy": ("bestbuy.com",), "walmart": ("walmart.com",),
             "kroger": tuple(_KROGER_HOSTS)}
    if name in fixed:
        return fixed[name]
    for cls in SITE_CLASSES:
        if cls.name == name:
            return tuple(cls.domains)
    return ()


class PanelServer:
    def __init__(self, monitor):
        self.monitor = monitor
        pcfg = monitor.cfg.raw.get("control_panel") or {}
        self.port = int(pcfg.get("port") or 8765)
        self.pin = str(pcfg.get("pin") or "").strip()
        self.lan = bool(pcfg.get("allow_lan")) and len(self.pin) >= 4
        if pcfg.get("allow_lan") and not self.lan:
            monitor.info("Control panel: allow_lan needs a pin of 4+ characters, staying on this PC only")
        self.token = secrets.token_urlsafe(24)
        self.httpd: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def lan_url(self) -> str | None:
        return f"http://{lan_ip()}:{self.port}/" if self.lan else None

    def start(self) -> bool:
        host = "0.0.0.0" if self.lan else "127.0.0.1"
        handler = type("Handler", (_Handler,), {"panel": self})
        try:
            self.httpd = ThreadingHTTPServer((host, self.port), handler)
        except OSError as exc:
            self.monitor.info(f"Control panel could not start on port {self.port}: {exc}")
            return False
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="panel").start()
        self.monitor.info(f"Control panel: {self.url}" + (f"  (phone: {self.lan_url})" if self.lan else ""))
        return True

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    # ---- API logic (kept out of the handler so it is easy to test) ---------------
    def status(self) -> dict:
        m = self.monitor
        muted = set(m.cfg.settings.get("ignored_items") or [])
        with m.snap_lock:
            latest = list(m.latest.values())
            alerts = list(m.alert_log)
            activity = list(m.activity)[:100]
            rstatus = dict(m.retailer_status)
        items = []
        fresh = [x for x in latest if time.time() - x[0] < 3600]  # hide listings not seen for an hour
        for checked, r in sorted(fresh, key=lambda x: (not x[1].in_stock, x[1].retailer_name, x[1].title)):
            items.append({
                "key": r.key, "retailer": r.retailer, "retailer_name": r.retailer_name,
                "title": r.title, "url": clean_url(r.url), "price": r.price,
                "msrp": r.msrp or price_limit(r, m.cfg), "online": r.online,
                "status": r.status_text(), "in_stock": r.in_stock, "note": r.note,
                "source": r.watch_name or r.source, "checked": checked,
                "stores": [s.label() for s in r.stores], "muted": r.key in muted,
                "store_points": [{"id": s.store_id, "name": s.name, "label": s.label(), "area": s.area,
                                  "distance": s.distance, "pickup": bool(s.pickup), "low": s.low,
                                  "point": _point(s)} for s in r.stores],
                "type": r.type_label, "preorder": r.preorder, "confirmed": r.confirmed,
                "pickup": len(r.pickup_stores),
            })
        now = time.time()

        def health(name: str) -> dict:
            h = m.health.get(name) or {}
            recent = list(h.get("recent") or [])
            return {
                "success": round(100 * sum(recent) / len(recent)) if recent else None,
                "checks": len(recent),
                "mode": h.get("mode") or "",
                "slow": round(h.get("slow", 1.0), 1),
                "next_in": max(0, int(h["next"] - now)) if h.get("next") else None,
                "notes": h.get("notes") or "",
                "last_block": h.get("last_block") or "",
            }
        browser = m.browser
        retailer_rows = [
            {"name": n, "display": r.display, "status": rstatus.get(n, "Waiting for first check"),
             "fetch_mode": r.fetch_mode, "using_browser": r.using_browser(), **health(n)}
            for n, r in m.retailers.items()
        ]
        cmp_rows = getattr(m, "compare", None).rows() if getattr(m, "compare", None) else []
        trk_rows = m.tracker.rows() if m.tracker else []
        trust = {
            "stores": trust_build(retailer_rows, cmp_rows, trk_rows, store_domains, m.cfg.retailer_cfg),
            "feeds": missing_feeds(m.cfg.retailer_cfg, set(m.retailers)),
        }
        return {
            "running": m.running,
            "paused": bool(m.cfg.settings.get("alerts_paused")),
            "now": time.time(),
            "version": app_version(),
            "version_label": version_label(),
            "retailers": retailer_rows,
            "trust": trust,
            "human_checks": list(m.human_checks.values()),
            "browser": {
                "installed": playwright_installed(),
                "running": bool(browser and browser.thread and browser.thread.is_alive()),
                "problem": (browser.failed if browser else "") or "",
            },
            "sessions": {"rows": trk_rows,
                         "profiles": browser.names() if browser else [],
                         "resting": browser.resting() if browser else [],
                         "compare": cmp_rows,
                         "features": getattr(m, "trial", None).rows() if getattr(m, "trial", None) else []},
            "trials": m.trials.snapshot() if m.trials else None,
            "history_total": len(m.history.events),
            "areas": [{"name": a.name, "zip": a.zip, "radius": a.radius, "lat": a.lat, "lon": a.lon,
                       "place": zip_place(a.zip)} for a in m.cfg.areas],
            "geocoder": geocoder_ready(),
            "catalog_total": len(m.catalog.items),
            "places_total": len(m.places.places),
            "items": items,
            "alerts": alerts,
            "activity": activity,
            "muted": sorted(muted),
            "lan_url": self.lan_url,
        }

    def test_filter(self, body: dict) -> dict:
        cfg = self.monitor.cfg
        title = str(body.get("title") or "")
        price = body.get("price")
        price = float(price) if price not in (None, "") else None
        search_name = body.get("search") or ""
        kw: KeywordFilter = cfg.keywords
        search_max = None
        if search_name:
            s = next((s for s in cfg.searches if s.name == search_name), None)
            if s:
                kw, search_max = cfg.keywords.merged(s.keywords), s.max_price
        res = StockResult(retailer="test", retailer_name="Test", product_id="x", title=title,
                          url="", price=price, online=True, third_party=bool(body.get("third_party")))
        c = classify(title, allow_non_english=bool(cfg.settings.get("allow_non_english")))
        if search_name and not c.is_tcg:
            ok, why = False, f"not a sealed card product ({c.reason}), so searches and discovery skip it"
        else:
            ok, why = passes(res, cfg, kw, search_max)
        cap = price_limit(res, cfg, search_max)
        tol = float(cfg.settings.get("msrp_tolerance_pct") or 0)
        if body.get("retailer"):
            from .filters import tolerance_pct
            tol = tolerance_pct(cfg, str(body.get("retailer")))
        return {
            "alert": ok,
            "reason": why or "Passes every filter. This would alert when in stock.",
            "price_cap": round(cap * (1 + tol / 100), 2) if cap else None,
            "msrp": cap,
            "type": c.type_label if c.is_tcg else "",
            "is_tcg": c.is_tcg,
            "why_not_tcg": "" if c.is_tcg else c.reason,
        }

    def catalog(self) -> dict:
        m = self.monitor
        types = type_settings(m.cfg.raw)
        groups = m.catalog.groups()
        for g in groups:
            for l in g["listings"]:
                l["url"] = clean_url(l.get("url", ""))
                l["type_alert"] = types.get(l.get("type") or "other", {}).get("alert", True)
        d = m.cfg.raw.get("discovery") or {}
        return {"groups": groups, "runs": m.catalog.runs, "enabled": bool(d.get("enabled", True)),
                "retailers": d.get("retailers") or []}

    def places(self) -> dict:
        m = self.monitor
        data = m.places.summary()
        excluded = set(m.cfg.settings.get("excluded_stores") or [])
        for p in data["places"]:
            p["excluded"] = p["key"] in excluded
        data["areas"] = [{"name": a.name, "zip": a.zip, "radius": a.radius, "lat": a.lat, "lon": a.lon}
                         for a in m.cfg.areas]
        data["geocoder"] = geocoder_ready()
        return data

    @staticmethod
    def types() -> list[dict]:
        return [{"key": t.key, "label": t.label, "msrp": t.msrp} for t in TYPES] + \
               [{"key": "other", "label": "Other card product", "msrp": None}]


class _Handler(BaseHTTPRequestHandler):
    panel: PanelServer
    server_version = "RestockPanel"
    sys_version = ""

    def log_message(self, *args):  # keep the console quiet
        pass

    # ---- plumbing ---------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding tricks: only answer to our own addresses.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        allowed = {"127.0.0.1", "localhost"}
        if self.panel.lan:
            allowed.add(lan_ip())
        return host in allowed

    def _authed(self) -> bool:
        given = self.headers.get("X-Token") or ""
        if hmac.compare_digest(given, self.panel.token):
            return True
        return bool(self.panel.pin) and hmac.compare_digest(given, self.panel.pin)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Request too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        return data

    def _is_local_client(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    # ---- routes ---------------------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"Forbidden", "text/plain")
        path = urlsplit(self.path).path
        if path == "/":
            # The page served to this PC carries the session token. Other devices log in with the PIN.
            token = self.panel.token if self._is_local_client() else ""
            html = PAGE.replace("__TOKEN__", json.dumps(token))
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        if not self._authed():
            return self._json(401, {"error": "PIN required"})
        if path == "/api/scan":
            return self._json(200, self.panel.monitor.scan.snapshot())
        if path == "/api/status":
            return self._json(200, self.panel.status())
        if path == "/api/config":
            return self._json(200, copy.deepcopy(self.panel.monitor.cfg.raw))
        if path == "/api/geo":
            q = parse_qs(urlsplit(self.path).query)
            z = clean_zip((q.get("zip") or [""])[0])
            pt = zip_point(z) if z else None
            return self._json(200, {"zip": z, "lat": pt[0] if pt else None, "lon": pt[1] if pt else None,
                                    "place": zip_place(z) if pt else "", "ready": geocoder_ready()})
        if path == "/api/catalog":
            return self._json(200, self.panel.catalog())
        if path == "/api/places":
            return self._json(200, self.panel.places())
        if path == "/api/types":
            return self._json(200, self.panel.types())
        if path == "/api/patterns":
            q = parse_qs(urlsplit(self.path).query)
            retailer = (q.get("retailer") or [""])[0] or None
            place = (q.get("place") or [""])[0] or None
            return self._json(200, self.panel.monitor.history.patterns(retailer, place))
        return self._json(404, {"error": "Not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, b"Forbidden", "text/plain")
        if not self._authed():
            return self._json(401, {"error": "PIN required"})
        path = urlsplit(self.path).path
        m = self.panel.monitor
        try:
            body = self._body()
            if path == "/api/config":
                m.save_settings(body)
                return self._json(200, {"ok": True})
            if path == "/api/action":
                action = body.get("action")
                if action == "start":
                    m.start()
                elif action == "stop":
                    threading.Thread(target=m.stop, daemon=True).start()
                elif action == "check":
                    m.check_now()
                elif action == "show_browser":
                    m.show_browser()
                elif action == "refresh_places":
                    threading.Thread(target=_safe(m, m.refresh_places), daemon=True).start()
                elif action == "scan_start":
                    ok, msg = m.scan.start(body.get("zip"), body.get("radius"), body.get("stores"),
                                           bool(body.get("online")), bool(body.get("everything")))
                    return self._json(200, {"ok": ok, "message": msg})
                elif action == "trial_toggle":
                    ok, msg = m.trials.set_active(str(body.get("key")), bool(body.get("on")))
                    return self._json(200, {"ok": ok, "message": msg})
                elif action == "trial_bulk":
                    ok, msg = m.trials.keep_best(3) if body.get("mode") == "best" else m.trials.all_off()
                    return self._json(200, {"ok": ok, "message": msg})
                elif action == "scan_cancel":
                    m.scan.cancel()
                elif action == "rediscover":
                    m.rediscover()
                elif action == "exclude_store":
                    m.set_store_excluded(str(body.get("key")), bool(body.get("excluded", True)))
                elif action == "product_status":
                    m.set_product_status(str(body.get("key")), str(body.get("status")))
                elif action == "pause":
                    m.set_paused(bool(body.get("paused")))
                elif action == "mute":
                    m.set_muted(str(body.get("key")), bool(body.get("muted", True)))
                elif action == "test_discord":
                    if not m.notifier.enabled:
                        return self._json(200, {"ok": False, "message": "No webhook saved yet"})
                    results = m.notifier.test()
                    return self._json(200, {"ok": all(results.values()), "results": results})
                else:
                    return self._json(400, {"error": f"Unknown action {action}"})
                return self._json(200, {"ok": True})
            if path == "/api/test-filter":
                return self._json(200, self.panel.test_filter(body))
            return self._json(404, {"error": "Not found"})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:
            m.log.exception("panel error")
            return self._json(500, {"error": f"{exc.__class__.__name__}: {exc}"})


def _point(store) -> list | None:
    from .geo import place_point
    pt = place_point(store.lat, store.lon, store.zip)
    return [round(pt[0], 5), round(pt[1], 5)] if pt else None


def _safe(monitor, fn):
    def run():
        try:
            fn()
        except Exception as exc:
            monitor.info(f"Store finder: {exc}")
    return run
