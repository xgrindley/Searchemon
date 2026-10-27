"""Other identities and other addresses: rotating User-Agents, proxies (a VPN's SOCKS5 or HTTP proxy works too) and a
VPN reconnect command.

Everything here is used through the trial methods (see trials.py), so each one is checked, scored against the
others at every store, rotated toward whatever works best there, and stopped by itself if it keeps failing:

- direct-ua       plain requests that each go out as a different, current desktop browser
- direct-proxy    plain requests through your proxies, a different one each check; a proxy a store blocks rests there
- browser-proxy   a separate browser profile ("proxy", never signed in to anything) that goes through your proxies and
                  moves to the next proxy after a block

The VPN reconnect command (config.yaml only, network: vpn_reconnect_command) runs when a store has been blocked several
times in a row, so the whole PC gets a new address from your VPN app. It is not editable from the control panel, because
anything typed there could then run a program on this PC.

Proxies see which store pages you check. Use ones you trust.
"""
from __future__ import annotations

import os
import random
import shlex
import subprocess
import threading
import time
from urllib.parse import quote, unquote, urlsplit

# Current desktop browsers (Windows and Mac; Chrome, Edge, Firefox, Safari).
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) Gecko/20100101 Firefox/144.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:144.0) Gecko/20100101 Firefox/144.0",
]
PROXY_REST_S = 2 * 3600         # a proxy a store blocked sits out at that store for this long
VPN_AFTER_BLOCKS = 3
VPN_MIN_MINUTES = 30


def net_cfg(raw: dict) -> dict:
    c = raw.get("network") if isinstance(raw, dict) else None
    return c if isinstance(c, dict) else {}


def user_agents(raw: dict) -> list[str]:
    own = [str(u).strip() for u in net_cfg(raw).get("user_agents") or [] if str(u).strip()]
    return own or list(USER_AGENTS)


def normalize_proxy(text: str) -> str:
    """'host:port', 'host:port:user:pass', 'user:pass@host:port' or a full URL -> 'scheme://[user:pass@]host:port'.
    Returns "" for something that is not a proxy."""
    t = str(text or "").strip()
    if not t or t.startswith("#"):
        return ""
    if "://" not in t:
        parts = t.split(":", 3)
        if len(parts) == 4 and parts[1].isdigit():          # the host:port:user:pass form most proxy sellers hand out
            host, port, user, pw = parts
            t = f"{quote(user, safe='')}:{quote(pw, safe='')}@{host}:{port}"
        t = "http://" + t
    p = urlsplit(t)
    if p.scheme not in ("http", "https", "socks5", "socks5h", "socks4") or not p.hostname or not p.port:
        return ""
    return t


def proxies(raw: dict) -> list[str]:
    out = []
    for line in net_cfg(raw).get("proxies") or []:
        p = normalize_proxy(line)
        if p and p not in out:
            out.append(p)
    return out


def label(proxy: str) -> str:
    """A proxy without its password, for logs and the control panel."""
    p = urlsplit(proxy)
    return f"{p.scheme}://{p.hostname}:{p.port}" + (f" ({unquote(p.username)})" if p.username else "")


def playwright_proxy(proxy: str) -> dict:
    p = urlsplit(proxy)
    out = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        out["username"] = unquote(p.username)
        out["password"] = unquote(p.password or "")
    return out


def socks_ready() -> bool:
    try:
        import socks  # noqa: F401  (PySocks, needed by requests for socks5 proxies)
        return True
    except ImportError:
        return False


class ProxyPool:
    """Hands out proxies in turn, skipping ones a store recently blocked; counts how each does at each store."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.lock = threading.Lock()
        self.turn = 0
        self.rest: dict[tuple[str, str], float] = {}
        self.stats: dict[str, dict] = {}

    def attach(self, raw: dict) -> None:
        self.raw = raw

    def all(self) -> list[str]:
        return proxies(self.raw)

    def pick(self, store: str) -> str:
        """The next proxy not resting at this store, or "" when none is free (or none is set)."""
        now = time.time()
        with self.lock:
            items = self.all()
            for i in range(len(items)):
                p = items[(self.turn + i) % len(items)]
                if self.rest.get((p, store), 0) <= now:
                    self.turn = (self.turn + i + 1) % len(items)
                    return p
        return ""

    def note(self, proxy: str, store: str, ok: bool) -> None:
        with self.lock:
            s = self.stats.setdefault(label(proxy), {"checks": 0, "blocks": 0})
            s["checks"] += 1
            if not ok:
                s["blocks"] += 1
                self.rest[(proxy, store)] = time.time() + PROXY_REST_S

    def view(self) -> list[dict]:
        now = time.time()
        with self.lock:
            out = []
            for p in self.all():
                s = self.stats.get(label(p), {"checks": 0, "blocks": 0})
                out.append({"proxy": label(p), "checks": s["checks"], "blocks": s["blocks"],
                            "resting_at": sorted(st for (q, st), t in self.rest.items() if q == p and t > now)})
            return out


class VpnSwitch:
    """Runs your VPN app's reconnect command after a store has been blocked several times in a row."""

    def __init__(self, raw: dict, log):
        self.raw = raw
        self.log = log
        self.last = 0.0
        self.runs = 0
        self.last_result = ""
        self.lock = threading.Lock()

    @property
    def command(self) -> str:
        return str(net_cfg(self.raw).get("vpn_reconnect_command") or "").strip()

    def maybe(self, store: str, block_streak: int) -> bool:
        c = net_cfg(self.raw)
        if not self.command or block_streak < int(c.get("vpn_after_blocks") or VPN_AFTER_BLOCKS):
            return False
        with self.lock:
            if time.time() - self.last < float(c.get("vpn_min_minutes") or VPN_MIN_MINUTES) * 60:
                return False
            self.last = time.time()
        return self.run(f"{store} was blocked {block_streak} times in a row")

    def run(self, why: str) -> bool:
        try:
            args = shlex.split(self.command, posix=(os.name != "nt"))
            args = [a.strip('"') for a in args]
            done = subprocess.run(args, capture_output=True, text=True, timeout=90,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.runs += 1
            self.last_result = f"exit code {done.returncode}"
            self.log.info("VPN reconnect (%s): ran your command, %s", why, self.last_result)
            time.sleep(random.uniform(8, 15))     # give the VPN a moment to come back up
            return done.returncode == 0
        except Exception as exc:
            self.last_result = str(exc)[:120]
            self.log.info("VPN reconnect (%s) failed: %s", why, self.last_result)
            return False

    def view(self) -> dict:
        c = net_cfg(self.raw)
        return {"set": bool(self.command), "after_blocks": int(c.get("vpn_after_blocks") or VPN_AFTER_BLOCKS),
                "min_minutes": int(c.get("vpn_min_minutes") or VPN_MIN_MINUTES), "runs": self.runs,
                "last": self.last, "last_result": self.last_result}
