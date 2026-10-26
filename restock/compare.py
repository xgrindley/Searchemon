"""Side-by-side comparison of loading methods on the same page at the same moment.

Every so often, per store, one product page is loaded by every available method at once: a plain
request, each of the app's browser profiles, and your own Chrome and Edge when they are running.
Only real, unmodified browsers and ordinary requests take part. The outcome of each (loaded or
blocked, how it was blocked, how long it took) is kept in data/compare.json so the Methods lab can
show a like-for-like table. A blocked profile rests for that store exactly as it does during
normal checking.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests

from .retailers.base import UA
from .retailers.blocks import classify
from .util import atomic_write_json, read_json

KEEP = 40          # recent runs kept per store and method


class SideBySide:
    def __init__(self, data_dir: str, log, browser=None):
        self.path = os.path.join(data_dir, "compare.json")
        self.log = log
        self.browser = browser
        self.lock = threading.Lock()
        self.data: dict = read_json(self.path, {})        # store -> method -> [ {t, ok, kind, ms} ]; "_domains" maps store -> site
        self.last_run: dict[str, float] = {}
        self.running: set[str] = set()

    # ---- when to run -------------------------------------------------------------------
    def every_s(self) -> float:
        raw = getattr(self.browser, "raw", None) or {}
        try:
            return float((raw.get("browser") or {}).get("compare_every_minutes", 15) or 0) * 60
        except (TypeError, ValueError):
            return 0.0

    def maybe_run(self, store: str, url: str) -> bool:
        """Start a comparison in the background when this store is due. Never blocks the checking loop."""
        every = self.every_s()
        now = time.time()
        if not every or not url.startswith("http") or store in self.running:
            return False
        if now - self.last_run.get(store, 0) < every:
            return False
        if not (self.browser and any(w.usable for w in self.browser.workers)):
            return False
        self.last_run[store] = now
        self.running.add(store)
        threading.Thread(target=self._guarded, args=(store, url), daemon=True, name=f"compare-{store}").start()
        return True

    def _guarded(self, store: str, url: str) -> None:
        try:
            self.run(store, url)
        except Exception as exc:                      # a comparison must never hurt normal checking
            self.log.debug("side-by-side test for %s failed: %s", store, exc)
        finally:
            self.running.discard(store)

    # ---- one comparison ----------------------------------------------------------------
    def _plain(self, url: str) -> tuple[bool, str]:
        resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                                          "Cache-Control": "no-cache"}, timeout=25)
        info = classify(resp.status_code, resp.text, resp.headers)
        if info is None and resp.status_code >= 500:
            return False, "server_error"
        return (info is None or info.kind == "queue"), (info.kind if info else "")

    def _browser(self, w, url: str) -> tuple[bool, str]:
        res = w.fetch(url, 90, ask=False)
        if res.waiting_for_human:
            return False, "needs_person"
        blocked = bool(res.block and res.block.kind != "queue")
        if blocked:
            pool = self.browser
            domain = urlsplit(url).netloc.lower()
            rest = res.block.retry_after or pool.DEFAULT_REST_S.get(res.block.kind, 900)
            if res.block.hard:
                rest = max(rest, 6 * 3600)
            pool.rest[(w.name, domain)] = time.time() + rest
        return (not blocked), (res.block.kind if res.block else "")

    def run(self, store: str, url: str) -> dict:
        pool = self.browser
        domain = urlsplit(url).netloc.lower()
        now = time.time()
        jobs = {"direct": lambda: self._plain(url)}
        for w in pool.workers:
            if not w.usable or pool.rest.get((w.name, domain), 0) > now:
                continue
            if any(p["domain"] == domain for p in w.waiting_domains()):
                continue
            jobs[w.name] = (lambda w=w: self._browser(w, url))
        out: dict[str, dict] = {}

        def timed(name, fn):
            t0 = time.time()
            try:
                ok, kind = fn()
            except Exception as exc:
                ok, kind = False, "error:" + exc.__class__.__name__
            return name, {"t": time.time(), "ok": bool(ok), "kind": kind, "ms": int((time.time() - t0) * 1000)}

        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            for name, r in ex.map(lambda kv: timed(*kv), jobs.items()):
                out[name] = r
        with self.lock:
            self.data.setdefault("_domains", {})[store] = domain.removeprefix("www.")
            for name, r in out.items():
                runs = self.data.setdefault(store, {}).setdefault(name, [])
                runs.append(r)
                del runs[:-KEEP]
        atomic_write_json(self.path, self.data)
        self.log.info("Side-by-side test at %s: %s", store,
                      ", ".join(f"{n} {'ok' if r['ok'] else (r['kind'] or 'blocked')}" for n, r in out.items()))
        return out

    # ---- for the panel -----------------------------------------------------------------
    def rows(self) -> list[dict]:
        out = []
        with self.lock:
            for store, methods in self.data.items():
                if store.startswith("_"):
                    continue
                for method, runs in methods.items():
                    if not runs:
                        continue
                    ok = [r for r in runs if r["ok"]]
                    out.append({"store": store, "method": method, "runs": len(runs), "ok": len(ok),
                                "last_ok": runs[-1]["ok"], "last_kind": runs[-1]["kind"],
                                "avg_ms": int(sum(r["ms"] for r in ok) / len(ok)) if ok else None,
                                "last_t": runs[-1]["t"]})
        return out

    # ---- learning from the results -------------------------------------------------------
    MIN_RUNS = 5

    def rates(self, site: str) -> dict[str, float]:
        """Share of side-by-side runs that loaded, per method, for the store behind this site.
        Only methods with at least MIN_RUNS runs count."""
        with self.lock:
            stores = [st for st, d in (self.data.get("_domains") or {}).items()
                      if site == d or site.endswith("." + d) or d.endswith("." + site)]
            out: dict[str, float] = {}
            for st in stores:
                for method, runs in (self.data.get(st) or {}).items():
                    if len(runs) >= self.MIN_RUNS:
                        out[method] = sum(1 for r in runs if r["ok"]) / len(runs)
            return out
