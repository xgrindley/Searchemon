"""Local web control panel: edit products, searches, filters and alerts from a browser.

By default it only listens on this PC (127.0.0.1). Setting control_panel.allow_lan
lets your phone on the same Wi-Fi reach it, and then a PIN is required.
"""
from __future__ import annotations

import copy
import hmac
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .accounts import SIGN_IN
from .config import KeywordFilter
from .filters import passes, price_limit
from .geo import clean_zip, geocoder_ready, zip_place, zip_point
from .tcg import TYPES, classify, type_settings
from .models import StockResult
from .panel_page import PAGE
from .retailers.browser import playwright_installed
from .trust import build as trust_build, missing_feeds
from .util import app_version, clean_url, version_label

FONT_FILES = {"sora.woff2": "sora-latin-wght-normal.woff2", "inter.woff2": "inter-latin-wght-normal.woff2",
              "mono.woff2": "jetbrains-mono-latin-wght-normal.woff2"}
SIGN_IN_NAMES = {"walmart": "Walmart", "pokemoncenter": "Pokemon Center", "amazon": "Amazon", "dicks": "Dick's Sporting Goods",
                 "safeway": "Safeway", "costco": "Costco", "samsclub": "Sam's Club", "gamestop": "GameStop",
                 "barnesandnoble": "Barnes & Noble", "booksamillion": "Books-A-Million", "raleys": "Raley's",
                 "walgreens": "Walgreens", "cvs": "CVS", "macys": "Macy's", "kohls": "Kohl's"}

MAX_BODY = 1_000_000


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the LAN interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


_HOME_NETS = None


def _home_net(ip) -> bool:
    """True for the three ranges home routers use (RFC 1918): 10.x, 172.16 to 31.x and 192.168.x."""
    global _HOME_NETS
    import ipaddress
    if _HOME_NETS is None:
        _HOME_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    return ip.version == 4 and any(ip in n for n in _HOME_NETS)


def lan_addresses() -> list[str]:
    """Every private IPv4 address of this PC (home Wi-Fi first), so the phone link is right even with a VPN, WSL or
    Hyper-V adapter present. 169.254.x (no network) and 127.x are left out."""
    found: list[str] = []
    candidates = [lan_ip()]
    try:
        candidates += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    try:
        candidates += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    import ipaddress
    for c in candidates:
        try:
            ip = ipaddress.ip_address(c)
        except ValueError:
            continue
        if _home_net(ip) and c not in found:
            found.append(c)
    # 192.168.x is what home routers hand out; put it first, then 10.x, then 172.16 to 31 (often virtual adapters).
    found.sort(key=lambda x: (0 if x.startswith("192.168.") else 1 if x.startswith("10.") else 2))
    return found


def private_ip_literal(host: str) -> bool:
    """True for a raw private address such as 192.168.1.20. DNS rebinding needs a hostname, so an address typed as numbers is safe to
    answer when phone access is on, whichever of this PC's adapters the phone reached."""
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return _home_net(ip)


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
        self.listening_lan = False
        self.httpd: ThreadingHTTPServer | None = None
        self._fails: dict[str, list[float]] = {}     # wrong PINs per address, for the lockout
        self._fails_lock = threading.Lock()

    # A 4 digit PIN has only 10,000 values, so an address that guesses wrong 8 times in 10 minutes is
    # refused for 10 minutes. This PC itself never needs the PIN (it gets the session token).
    PIN_TRIES, PIN_WINDOW_S = 8, 600

    def locked_out(self, who: str) -> bool:
        with self._fails_lock:
            now = time.time()
            recent = [t for t in self._fails.get(who, []) if now - t < self.PIN_WINDOW_S]
            self._fails[who] = recent
            return len(recent) >= self.PIN_TRIES

    def pin_failed(self, who: str) -> None:
        with self._fails_lock:
            self._fails.setdefault(who, []).append(time.time())
            if len(self._fails[who]) == self.PIN_TRIES:
                self.monitor.info(f"Control panel: {self.PIN_TRIES} wrong PINs from {who}, refusing it for 10 minutes")

    def pin_ok(self, who: str) -> None:
        with self._fails_lock:
            self._fails.pop(who, None)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def lan_url(self) -> str | None:
        return f"http://{(lan_addresses() or [lan_ip()])[0]}:{self.port}/" if self.lan else None

    def phone_status(self) -> dict:
        """What the Phone access section shows: is it on, why not, and every address to try."""
        pcfg = self.monitor.cfg.raw.get("control_panel") or {}
        asked = bool(pcfg.get("allow_lan"))
        if not asked:
            state, why = "off", "Phone access is off. Switch it on, set a PIN, save, and restart the app."
        elif len(self.pin) < 4:
            state, why = "needs_pin", "Phone access needs a PIN of at least 4 characters. Set one, save, and restart the app."
        elif not self.httpd or not self.listening_lan:
            state, why = "restart", "Saved, but the app has not restarted since. Close and reopen it so the panel listens on your Wi-Fi."
        else:
            state, why = "on", "Listening on your home network."
        addrs = lan_addresses() if state == "on" else []
        return {"state": state, "message": why, "port": self.port,
                "urls": [f"http://{a}:{self.port}/" for a in addrs],
                "firewall": (f'New-NetFirewallRule -DisplayName "Searchemon control panel" -Direction Inbound -Protocol TCP '
                             f'-LocalPort {self.port} -Profile Private -Action Allow')}

    def start(self) -> bool:
        host = "0.0.0.0" if self.lan else "127.0.0.1"
        self.listening_lan = False
        handler = type("Handler", (_Handler,), {"panel": self})
        try:
            self.httpd = ThreadingHTTPServer((host, self.port), handler)
        except OSError as exc:
            self.monitor.info(f"Control panel could not start on port {self.port}: {exc}")
            return False
        self.httpd.daemon_threads = True
        self.listening_lan = self.lan
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.1), daemon=True, name="panel").start()
        self.monitor.info(f"Control panel: {self.url}" + (f"  (phone: {', '.join(f'http://{a}:{self.port}/' for a in lan_addresses()) or self.lan_url})" if self.lan else ""))
        if self.lan:
            self.monitor.info("If the phone cannot open it, Windows Firewall is the usual cause: see Stores & keys > Phone access for the one command that fixes it")
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
                                  "qty": s.qty, "address": s.address, "chain": s.chain, "stock": s.stock_text(),
                                  "point": _point(s)} for s in r.stores],
                "type": r.type_label, "preorder": r.preorder, "confirmed": r.confirmed,
                "pickup": len(r.pickup_stores),
            })
        now = time.time()

        def health(name: str) -> dict:
            h = m.health.get(name) or {}
            recent = list(h.get("recent") or [])
            d_ok, d_bad = m.store_history.window(name, 24)
            w_ok, w_bad = m.store_history.window(name, 24 * 7)
            return {
                "day_checks": d_ok + d_bad, "day_success": round(100 * d_ok / (d_ok + d_bad)) if d_ok + d_bad else None,
                "week_checks": w_ok + w_bad, "week_success": round(100 * w_ok / (w_ok + w_bad)) if w_ok + w_bad else None,
                "success": round(100 * sum(recent) / len(recent)) if recent else None,
                "checks": len(recent),
                "mode": h.get("mode") or "",
                "slow": round(h.get("slow", 1.0), 1),
                "next_in": max(0, int(h["next"] - now)) if h.get("next") else None,
                "notes": h.get("notes") or "",
                "last_block": h.get("last_block") or "",
                "last_ok": h.get("last_ok") or 0,
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
            "accounts": m.accounts.view(lambda site: health(site) if site in m.retailers else None,
                                        lambda site: SIGN_IN_NAMES.get(site, site)),
            "history": {
                "stores": [{"name": n, "display": r.display, "days": m.store_history.days(n, 30),
                            "totals": m.store_history.totals(n),
                            "tracked": len(m.catalog.tracked(n, type_settings(m.cfg.raw))),
                            "search": bool(r.supports_search)}
                           for n, r in m.retailers.items()],
                "methods": m.store_history.method_days(14),
            },
            "human_checks": list(m.human_checks.copy().values()),
            "browser": {
                "installed": playwright_installed(),
                "running": bool(browser and browser.thread and browser.thread.is_alive()),
                "problem": (browser.failed if browser else "") or "",
                "profiles": browser.profiles_info() if browser else [],
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
            "phone": self.phone_status(),
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
        if host in ("127.0.0.1", "localhost"):
            return True
        return self.panel.lan and (host == lan_ip() or private_ip_literal(host))

    def _authed(self) -> bool:
        given = self.headers.get("X-Token") or ""
        if hmac.compare_digest(given.encode(), self.panel.token.encode()):
            return True
        if not self.panel.pin:
            return False
        who = self.client_address[0]
        if self.panel.locked_out(who):
            return False
        if hmac.compare_digest(given.encode(), self.panel.pin.encode()):
            self.panel.pin_ok(who)
            return True
        if given:
            self.panel.pin_failed(who)
        return False

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
        if path.startswith("/fonts/") and path[7:] in FONT_FILES:
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", FONT_FILES[path[7:]]), "rb") as fh:
                    body = fh.read()
            except OSError:
                return self._send(404, b"Not found", "text/plain")
            self.send_response(200)
            self.send_header("Content-Type", "font/woff2")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=604800")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return self.wfile.write(body)
        if not self._authed():
            return self._json(401, {"error": "PIN required"})
        try:
            return self._get_api(path)
        except Exception as exc:
            self.panel.monitor.log.exception("panel error")
            return self._json(500, {"error": f"{exc.__class__.__name__}: {exc}"})

    def _get_api(self, path: str):
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
        if path == "/api/sellers":
            return self._json(200, {"rows": self.panel.monitor.sellers.rows()})
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
                elif action == "accounts_scan":
                    threading.Thread(target=_safe(m, m.scan_accounts), daemon=True).start()
                    return self._json(200, {"ok": True, "message": "Checking saved sign-ins"})
                elif action == "account_open":
                    site = str(body.get("store"))
                    if site not in SIGN_IN:
                        return self._json(200, {"ok": False, "message": "Unknown store."})
                    m.open_in_browser(SIGN_IN[site])
                    return self._json(200, {"ok": True, "message": "Opened in the checking browser. Sign in there; it is saved by itself."})
                elif action == "account_confirm":
                    site = str(body.get("store"))
                    ok = m.accounts.confirm(site)
                    return self._json(200, {"ok": ok, "message": "Saved: marked as signed in." if ok else
                                            "No saved cookies for that store yet. Open its sign-in page first."})
                elif action == "account_forget":
                    m.accounts.forget(str(body.get("store")))
                    return self._json(200, {"ok": True, "message": "Forgot the saved sign-in status (the browser's cookies are untouched)."})
                elif action == "profile_clear_bot":
                    ok, msg = m.profile_clear_bot(str(body.get("profile")), body.get("site") or None)
                    return self._json(200, {"ok": ok, "message": msg})
                elif action == "profile_reset":
                    ok, msg = m.profile_reset(str(body.get("profile")))
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
                    n = m.set_product_status(str(body.get("key")), str(body.get("status")))
                    ignored = str(body.get("status")) == "ignored"
                    return self._json(200, {"ok": True, "changed": n, "message":
                                            ("Ignored at every store. It stays ignored after restarts." if ignored
                                             else "Tracking it again at every store.")})
                elif action == "seller_mode":
                    ok = m.sellers.set_mode(str(body.get("key")), str(body.get("mode")))
                    return self._json(200, {"ok": ok, "message": {"block": "Seller blocked.", "allow": "Seller allowed.",
                                                                  "auto": "Seller is judged by its prices again."}.get(str(body.get("mode")), "")})
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
