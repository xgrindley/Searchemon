"""Trial methods: try ways of loading pages one at a time and trace which lasts longest.

The Methods lab already counts how long each way of loading a page lasts before a
store pushes back. This module adds more ways to try, without running them all at
once. For each store only ONE method is in use at a time. Each gets a slice of
checks (default 20), then the next one takes over, and the plain existing method
(the "control") takes its turn too so the comparison is fair. A method a store
blocks rests for a while and sits out of the rotation.

Every method here is an ordinary, honest way to load a page: the same visible
browser or plain client, the same headers, no disguised fingerprints, no
CAPTCHA solving, no proxy rotation. See RESOURCES.md for where each idea came from.

Results go into the block tracker under the method's key (shown in the Methods
lab), and each switch or block is appended to data/trial-log.jsonl so a run can
be traced afterwards.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass

TRACE_FILE = "trial-log.jsonl"
TRACE_KEEP_LINES = 500
TRACE_MAX_BYTES = 400_000


@dataclass(frozen=True)
class Arm:
    key: str
    label: str
    family: str            # "direct" (plain page requests) or "browser" (the checking browsers)
    idea: str              # what it does, in plain words
    source: str            # where the idea came from
    control: bool = False  # the way the app already worked; always takes its turn for a fair comparison
    interval_factor: float = 1.0


CATALOG: list[Arm] = [
    Arm("direct", "Plain requests", "direct",
        "The app's normal page request: one Python session, honest headers.",
        "Existing method (control)", control=True),
    Arm("direct-h2", "Plain requests over HTTP/2", "direct",
        "The same honest request, spoken over HTTP/2 the way every current browser does. "
        "Changes only the protocol, not the headers or the identity.",
        "PortSwigger/bypass-bot-detection: the HTTP/1 versus HTTP/2 observation only. "
        "Its cipher and fingerprint mimicry is not used."),
    Arm("direct-warm", "Plain requests, arrive via the front page", "direct",
        "Loads the store's front page first, keeps its cookies, then opens the product with the "
        "front page as the Referer, like a person clicking through.",
        "SeleniumBase: the session warm-up idea, minus its stealth modes"),
    Arm("direct-impersonate", "Plain requests, Chrome TLS fingerprint", "direct",
        "Plain requests sent through curl_cffi, which reproduces Chrome's TLS and HTTP/2 handshake, so the "
        "connection looks like Chrome's rather than Python's.",
        "PortSwigger/bypass-bot-detection: TLS fingerprint impersonation (stealth)"),
    Arm("browser-rotate", "Browser, rotating profiles", "browser",
        "The app's normal browser checking: pages rotate across all browser profiles.",
        "Existing method (control)", control=True),
    Arm("browser-solo", "Browser, one steady profile", "browser",
        "Stays on one browser profile instead of rotating, so one session sees steady low traffic.",
        "CrowdSec: steady, low-volume traffic from one real session draws less attention"),
    Arm("browser-own", "Browser, your own Chrome only", "browser",
        "Uses only your own signed-in Chrome (start-my-chrome.ps1) when it is running.",
        "SeleniumBase CDP mode: driving a real Chrome over the DevTools Protocol, kept visible"),
    Arm("browser-stealth", "Browser, stealth build (patchright)", "browser",
        "Runs on Patchright, a Playwright build with the automation markers removed, in its own separate "
        "profile ('stealth'). Needs Chrome installed.",
        "undetected-chromedriver / SeleniumBase UC mode / CloakBrowser: hiding automation markers (stealth)"),
    Arm("browser-slow", "Browser, half the pace", "browser",
        "Rotating profiles, but checks this store half as often.",
        "CrowdSec: slower traffic is blocked less", interval_factor=2.0),
]
BY_KEY = {a.key: a for a in CATALOG}

# The stealth methods (direct-impersonate, browser-stealth) are off until you switch them on.
# Only a few are on by default, so each can be traced on its own. Turn others on in the
# Methods lab, or in config.yaml under trials: active.
DEFAULT_ACTIVE = ["direct-h2", "browser-solo", "browser-own"]
DEFAULTS = {
    "enabled": True,
    "slice_checks": 20,       # checks an arm gets before the next takes over
    "rest_minutes": 90,       # how long a blocked arm sits out of the rotation for that store
    "active": DEFAULT_ACTIVE,
    "stores": [],             # empty = every store; otherwise only these store keys
}


class TrialPlan:
    """Decides which arm each store uses for its next check, one at a time."""

    def __init__(self, raw_cfg: dict, data_dir: str, log=None, tracker=None):
        self.raw = raw_cfg
        self.dir = data_dir
        self.log = log
        self.tracker = tracker
        self.lock = threading.Lock()
        self.state: dict[str, dict] = {}   # store -> {"idx", "used", "rest": {arm: until}, "current"}
        self.unavailable: dict[str, str] = {}  # arm key -> why it cannot run on this PC

    # ---- settings ----------------------------------------------------------------
    @property
    def cfg(self) -> dict:
        merged = dict(DEFAULTS)
        merged.update(self.raw.get("trials") or {})
        return merged

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled"))

    def active_keys(self) -> list[str]:
        keys = [str(k) for k in (self.cfg.get("active") or []) if str(k) in BY_KEY]
        return [k for k in keys if not BY_KEY[k].control]

    def _covers(self, store: str) -> bool:
        only = [str(s) for s in (self.cfg.get("stores") or [])]
        return not only or store in only

    # ---- rotation ----------------------------------------------------------------
    def _lineup(self, store: str, family: str, now: float) -> list[Arm]:
        st = self.state.setdefault(store, {"idx": 0, "used": 0, "rest": {}, "current": ""})
        arms = [a for a in CATALOG if a.family == family and a.control]
        for key in self.active_keys():
            a = BY_KEY[key]
            if a.family == family and key not in self.unavailable and st["rest"].get(key, 0) <= now:
                arms.append(a)
        return arms

    def arm_for(self, store: str, family: str) -> Arm | None:
        """The arm to use for this store's next check, or None to just run the normal way."""
        if not (self.enabled and self._covers(store)):
            return None
        now = time.time()
        with self.lock:
            arms = self._lineup(store, family, now)
            if len(arms) < 2:
                return None            # nothing to compare against right now
            st = self.state[store]
            if st["used"] >= int(self.cfg.get("slice_checks") or 20):
                st["idx"] += 1
                st["used"] = 0
            arm = arms[st["idx"] % len(arms)]
            if st["current"] != arm.key:
                st["current"] = arm.key
                self._trace(store, arm.key, "switch")
            return arm

    def note(self, store: str, arm: Arm, ok: bool, kind: str = "") -> None:
        """Record one finished check. A blocked trial arm rests; a blocked control just moves on."""
        with self.lock:
            st = self.state.setdefault(store, {"idx": 0, "used": 0, "rest": {}, "current": ""})
            st["used"] += 1
            if not ok:
                if not arm.control:
                    st["rest"][arm.key] = time.time() + float(self.cfg.get("rest_minutes") or 90) * 60
                st["idx"] += 1
                st["used"] = 0
                self._trace(store, arm.key, "blocked", kind)
        if self.tracker and not arm.control:
            self.tracker.record(arm.key, store, ok, kind)

    def skip(self, store: str, arm: Arm, why: str, minutes: float = 5) -> None:
        """The arm could not run just now (for example your own Chrome is not open). Move on
        without counting a check, and look at it again in a few minutes."""
        with self.lock:
            st = self.state.setdefault(store, {"idx": 0, "used": 0, "rest": {}, "current": ""})
            st["rest"][arm.key] = time.time() + minutes * 60
            st["idx"] += 1
            st["used"] = 0
            st["current"] = ""
            self._trace(store, arm.key, "skipped", why)

    def mark_unavailable(self, key: str, why: str) -> None:
        with self.lock:
            if key not in self.unavailable:
                self.unavailable[key] = why
                if self.log:
                    self.log.info("Trial method '%s' is skipped: %s", key, why)
                self._trace("-", key, "unavailable", why)

    def interval_factor(self, store: str, family: str = "browser") -> float:
        """How much slower this store should be checked right now (the half-pace arm doubles it)."""
        if not (self.enabled and self._covers(store)):
            return 1.0
        with self.lock:
            st = self.state.get(store)
            arm = BY_KEY.get(st["current"]) if st else None
        return arm.interval_factor if arm and arm.family == family else 1.0

    # ---- trace -------------------------------------------------------------------
    def _trace(self, store: str, arm: str, event: str, detail: str = "") -> None:
        path = os.path.join(self.dir, TRACE_FILE)
        line = json.dumps({"t": round(time.time()), "store": store, "arm": arm, "event": event, "detail": detail[:120]})
        try:
            os.makedirs(self.dir, exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > TRACE_MAX_BYTES:
                with open(path, encoding="utf-8") as fh:
                    keep = fh.readlines()[-TRACE_KEEP_LINES:]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(keep)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    # ---- view for the control panel ------------------------------------------------
    def snapshot(self) -> dict:
        now = time.time()
        with self.lock:
            current = {s: st["current"] for s, st in self.state.items() if st["current"]}
            resting = [{"store": s, "arm": k, "minutes": int((t - now) / 60) + 1}
                       for s, st in self.state.items() for k, t in st["rest"].items() if t > now]
        active = set(self.active_keys())
        return {
            "enabled": self.enabled,
            "slice_checks": int(self.cfg.get("slice_checks") or 20),
            "arms": [{"key": a.key, "label": a.label, "family": a.family, "idea": a.idea, "source": a.source,
                      "control": a.control, "on": a.control or a.key in active,
                      "unavailable": self.unavailable.get(a.key, "")} for a in CATALOG],
            "current": current,
            "resting": resting,
        }
