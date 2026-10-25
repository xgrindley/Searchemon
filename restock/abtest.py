"""Side-by-side test of checking methods: which one gets blocked last?

Every method (plain requests, plus each browser profile in browser.profiles)
loads the same list of product pages at the same gentle pace, all at the same
time. Outcomes go to the block tracker, and a table at the end shows, for each
method, how many loads it got through and when the first block came.

It loads ordinary public product pages a few times a minute, about what a person
refreshing a tab would do. It does not try to get around a block: a method that
gets blocked rests for the length of the block like in normal use.
"""
from __future__ import annotations

import random
import threading
import time
from urllib.parse import urlsplit

import requests

from .retailers.base import UA
from .retailers.blocks import classify
from .retailers.browser import FetchResult  # noqa: F401  (documented type of browser results)


def default_urls(mon) -> list[str]:
    """Pages from your own watchlist and found products, one or two per store."""
    urls: list[str] = []
    for w in mon.cfg.watchlist:
        urls.extend(u for u in w.urls if u.startswith("http"))
    for item in mon.catalog.items.values():
        if str(item.get("url", "")).startswith("http"):
            urls.append(item["url"])
    per_site: dict[str, list[str]] = {}
    for u in urls:
        per_site.setdefault(urlsplit(u).netloc.lower(), []).append(u)
    return [u for lst in per_site.values() for u in lst[:2]]


class Run:
    def __init__(self, mon, urls: list[str], rounds: int, delay: float, say=print):
        self.mon, self.urls, self.rounds, self.delay, self.say = mon, urls, rounds, delay, say
        self.results: dict[str, dict] = {}
        self.lock = threading.Lock()

    def note(self, method: str, url: str, blocked: bool, kind: str = "") -> None:
        site = urlsplit(url).netloc.lower().removeprefix("www.")
        with self.lock:
            e = self.results.setdefault(method, {"loads": 0, "blocks": 0, "first_block": None, "kinds": set()})
            e["loads"] += 1
            if blocked:
                e["blocks"] += 1
                e["kinds"].add(kind)
                if e["first_block"] is None:
                    e["first_block"] = e["loads"]
        if self.mon.tracker:
            self.mon.tracker.record(method, site, not blocked, kind)
        self.say(f"  [{method}] {site}: {'BLOCKED (' + kind + ')' if blocked else 'ok'}")

    def worker(self, method: str, load) -> None:
        for _ in range(self.rounds):
            for url in self.urls:
                try:
                    blocked, kind = load(url)
                except Exception as exc:
                    blocked, kind = False, ""
                    self.say(f"  [{method}] error: {str(exc)[:80]}")
                    continue
                self.note(method, url, blocked, kind)
                time.sleep(self.delay * random.uniform(0.8, 1.3))

    def direct(self, url: str):
        resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=25)
        info = classify(resp.status_code, resp.text, resp.headers)
        return bool(info and info.kind != "queue"), info.kind if info else ""

    def run(self) -> dict:
        threads = [threading.Thread(target=self.worker, args=("direct", self.direct), daemon=True)]
        pool = self.mon.browser
        if pool and pool.usable:
            for w in pool.workers:
                if not w.usable:
                    continue

                def load(url, w=w):
                    res = w.fetch(url, ask=False)
                    return bool(res.block and res.block.kind != "queue"), res.block.kind if res.block else ""
                threads.append(threading.Thread(target=self.worker, args=(w.name, load), daemon=True))
        self.say(f"Testing {len(threads)} method(s) on {len(self.urls)} page(s), {self.rounds} round(s), "
                 f"about {self.delay:.0f}s between loads per method.")
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if self.mon.tracker:
            self.mon.tracker.save()
        return self.results

    def table(self) -> str:
        lines = [f"{'method':<14}{'loads':>7}{'blocks':>8}{'first block at':>16}   kinds"]
        for m, e in sorted(self.results.items(), key=lambda kv: (kv[1]["blocks"], -kv[1]["loads"])):
            first = f"load {e['first_block']}" if e["first_block"] else "none"
            lines.append(f"{m:<14}{e['loads']:>7}{e['blocks']:>8}{first:>16}   {', '.join(sorted(e['kinds']))}")
        return "\n".join(lines)
