"""Which store accounts are signed in, and whether they are still working.

The checking browsers keep their cookies between runs (each in its own folder under data\\), so signing in once
lasts. This module looks at those cookies from time to time and remembers, in data\\accounts.json, which store
and which browser profile has a sign-in saved. It never reads or stores a cookie's value: only names are
matched in memory, and what is saved is counts, dates and the expiry of the sign-in cookie.

A sign-in is recognised by cookies that only exist once you are logged in (names like loggedin, customerid,
access_token). Stores that hide that behind an ordinary-looking name are not detected, so there is also a
"I signed in" button that records your word for it until the cookies disappear.
"""
from __future__ import annotations

import os
import re
import threading
import time
from urllib.parse import urlsplit

from .util import atomic_write_json, read_json

FILE = "accounts.json"

SIGN_IN = {
    "walmart": "https://www.walmart.com/", "pokemoncenter": "https://www.pokemoncenter.com/",
    "amazon": "https://www.amazon.com/", "dicks": "https://www.dickssportinggoods.com/",
    "safeway": "https://www.safeway.com/", "costco": "https://www.costco.com/",
    "samsclub": "https://www.samsclub.com/", "gamestop": "https://www.gamestop.com/",
    "barnesandnoble": "https://www.barnesandnoble.com/", "booksamillion": "https://www.booksamillion.com/",
    "raleys": "https://www.raleys.com/", "walgreens": "https://www.walgreens.com/", "cvs": "https://www.cvs.com/",
}

# Cookies that mean "this browser is logged in", as opposed to ordinary session or tracking cookies.
STRONG = re.compile(r"(logged_?in|isloggedin|signed_?in|customer_?id|cust_?id|user_?id|userid|account_?id|member_?id|"
                    r"auth|access_?token|id_?token|refresh_?token|jwt|login_?state|myaccount)", re.I)
# Bot-check, analytics and ad cookies that can look similar but say nothing about a login.
IGNORE = re.compile(r"^(_px|px|_abck|bm_|ak_|cf_|__cf|datadome|incap|nlbi|visid|_ga|_gid|_fb|_uet|optanon|_gcl|_cs_|"
                    r"fs_|__utm|_hj|_pin|_tt)", re.I)


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


DOMAINS = {site: domain_of(url) for site, url in SIGN_IN.items()}


def classify(cookies: list[dict], domain: str, now: float | None = None) -> dict:
    """Counts only. `cookies` are Playwright cookie dicts; values are never looked at."""
    now = now or time.time()
    total = strong = 0
    expires = 0.0
    for c in cookies:
        host = str(c.get("domain") or "").lstrip(".").lower()
        if not (host == domain or host.endswith("." + domain) or domain.endswith("." + host)):
            continue
        exp = float(c.get("expires") or -1)
        if 0 < exp < now:
            continue                       # already expired
        total += 1
        name = str(c.get("name") or "")
        if STRONG.search(name) and not IGNORE.search(name):
            strong += 1
            if exp > 0:
                expires = exp if not expires else min(expires, exp)
    return {"total": total, "strong": strong, "expires": round(expires)}


class AccountTracker:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, FILE)
        self.lock = threading.Lock()
        data = read_json(self.path, {}) or {}
        self.sites: dict[str, dict] = data.get("sites", {}) if isinstance(data, dict) else {}

    def _row(self, site: str, profile: str) -> dict:
        return self.sites.setdefault(site, {}).setdefault(profile, {
            "state": "none", "since": 0, "last_seen": 0, "strong": 0, "total": 0, "expires": 0, "confirmed": 0, "lost": 0})

    def update(self, report: dict[str, dict[str, dict]], now: float | None = None) -> list[str]:
        """report: {profile: {site: classify()-result}}. Returns plain-words changes worth logging."""
        now = now or time.time()
        notes = []
        self.last_lost = []
        with self.lock:
            for profile, sites in report.items():
                for site, info in sites.items():
                    row = self._row(site, profile)
                    was = row["state"]
                    row.update({"strong": info["strong"], "total": info["total"], "expires": info["expires"], "last_seen": round(now)})
                    if info["strong"] > 0:
                        row["state"] = "signed_in"
                        row["since"] = row["since"] or round(now)
                        row["lost"] = 0
                    elif row["confirmed"] and info["total"] > 0:
                        row["state"] = "confirmed"
                        row["since"] = row["since"] or row["confirmed"]
                    else:
                        row["state"] = "none"
                        row["confirmed"] = 0
                        if was in ("signed_in", "confirmed"):
                            row["lost"] = round(now)
                            row["since"] = 0
                            self.last_lost.append((site, profile))
                            notes.append(f"{site}: the sign-in saved in the {profile} browser is gone (expired or signed out)")
                    if was not in ("signed_in", "confirmed") and row["state"] in ("signed_in", "confirmed"):
                        notes.append(f"{site}: signed in and saved in the {profile} browser")
        if notes or report:
            self.save()
        return notes

    def confirm(self, site: str) -> bool:
        """You say you signed in: counts for every profile that holds cookies for the site, until they vanish."""
        now = round(time.time())
        hit = False
        with self.lock:
            for profile, row in self.sites.get(site, {}).items():
                if row["total"] > 0:
                    row["confirmed"] = now
                    if row["state"] == "none":
                        row["state"] = "confirmed"
                        row["since"] = now
                    hit = True
        if hit:
            self.save()
        return hit

    def forget(self, site: str) -> None:
        with self.lock:
            self.sites.pop(site, None)
        self.save()

    def forget_profile(self, profile: str) -> None:
        """A browser's saved state was wiped: drop what was recorded for it."""
        with self.lock:
            for site in list(self.sites):
                self.sites[site].pop(profile, None)
                if not self.sites[site]:
                    del self.sites[site]
        self.save()

    def save(self) -> None:
        with self.lock:
            data = {"sites": {s: {p: dict(r) for p, r in rows.items()} for s, rows in self.sites.items()}}
        try:
            atomic_write_json(self.path, data)
        except OSError:
            pass

    def view(self, health_of, display_of) -> list[dict]:
        """One entry per store you can sign in to. `health_of(site)` is that store's health dict or None."""
        out = []
        with self.lock:
            for site in SIGN_IN:
                profiles = self.sites.get(site, {})
                signed = {p: r for p, r in profiles.items() if r["state"] in ("signed_in", "confirmed")}
                best = max(signed.values(), key=lambda r: r["since"] or 0) if signed else None
                lost = max([r["lost"] for r in profiles.values()] + [0])
                h = health_of(site) or {}
                success = h.get("success")
                last_ok = h.get("last_ok") or 0
                working = None
                if signed and h.get("checks"):
                    working = bool(success is not None and success >= 80 and time.time() - last_ok < 3600)
                out.append({
                    "site": site, "display": display_of(site), "state": "signed_in" if signed else "none",
                    "profiles": sorted(signed), "checked_profiles": sorted(profiles),
                    "since": best["since"] if best else 0, "expires": min([r["expires"] for r in signed.values() if r["expires"]] or [0]),
                    "confirmed": bool(best and best["state"] == "confirmed"),
                    "lost": lost if not signed else 0, "last_seen": max([r["last_seen"] for r in profiles.values()] + [0]),
                    "working": working, "success": success, "last_ok": last_ok,
                })
        return out
