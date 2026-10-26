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

from .util import atomic_write_json, read_json

TRACE_FILE = "trial-log.jsonl"
STATE_FILE = "trial-state.json"
KEEP_EVENTS = 30
MIN_FOR_BEST = 10          # checks a method needs before it can be called one of the best
MIN_BALANCE = 6            # recent checks at a store before auto-balance trusts a method's numbers
DECAY = 0.97               # older results count a little less each check (about the last 30 checks matter most)
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
    # A trial method is stopped by itself once it has had MORE than stop_after attempts since it was
    # switched on and stop_fail_pct percent or more of them failed or were blocked.
    "auto_stop": True,
    "stop_after": 25,
    "stop_fail_pct": 50,
    # Auto-balance: at each store, methods that have been working get longer turns and methods that have been
    # failing get shorter ones (never fewer than min_share of a normal turn, so they can recover and be re-judged).
    "auto_balance": True,
    "min_share": 0.25,
}


class TrialPlan:
    """Decides which arm each store uses for its next check, one at a time."""

    def __init__(self, raw_cfg: dict, data_dir: str, log=None, tracker=None):
        self.dir = data_dir
        self.log = log
        self.tracker = tracker
        self.lock = threading.Lock()
        self.state: dict[str, dict] = {}   # store -> {"idx", "used", "rest": {arm: until}, "current"}
        self.unavailable: dict[str, str] = {}  # arm key -> why it cannot run on this PC
        # Saved between runs (data/trial-state.json): which methods are on, the attempts counted since each
        # was switched on, which ones were stopped by themselves, and a short history.
        self.saved: dict = read_json(os.path.join(data_dir, STATE_FILE), {}) or {}
        self.saved.setdefault("window", {})
        self.saved.setdefault("stopped", {})
        self.saved.setdefault("events", [])
        self.saved.setdefault("balance", {})
        self.attach(raw_cfg)

    def attach(self, raw_cfg: dict) -> None:
        """Use these settings, but keep the saved on/off choices: after the first change made with the
        buttons, the saved list wins over config.yaml, so a restart brings back what you had."""
        self.raw = raw_cfg
        if "active" in self.saved:
            raw_cfg.setdefault("trials", {})["active"] = list(self.saved["active"])

    def _save(self) -> None:
        try:
            atomic_write_json(os.path.join(self.dir, STATE_FILE), self.saved)
        except OSError:
            pass

    def _event(self, kind: str, key: str, detail: str = "") -> None:
        self.saved["events"] = (self.saved["events"] + [{"t": round(time.time()), "kind": kind, "arm": key,
                                                          "detail": detail}])[-KEEP_EVENTS:]

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

    # ---- auto-balance -------------------------------------------------------------
    def _rate(self, store: str, key: str) -> tuple[float | None, float]:
        """(recent success rate, recent weight of evidence) for a method at a store, or (None, n) when too few checks."""
        ok, bad = self.saved["balance"].get(store, {}).get(key, (0.0, 0.0))
        n = ok + bad
        return ((ok + 1) / (n + 2) if n >= MIN_BALANCE else None), n

    def _weights(self, store: str, arms: list[Arm]) -> dict[str, float]:
        """How long a turn each method gets, as a multiple of a normal turn. Everyone is 1.0 until there is
        enough to go on; after that the better a method has been doing against the best one here, the longer."""
        floor = max(0.05, min(1.0, float(self.cfg.get("min_share") or 0.25)))
        scores = {a.key: self._rate(store, a.key)[0] for a in arms}
        known = [v for v in scores.values() if v is not None]
        if not self.cfg.get("auto_balance", True) or not known:
            return {a.key: 1.0 for a in arms}
        top = max(known)
        out = {}
        for a in arms:
            sc = scores[a.key]
            out[a.key] = 1.0 if sc is None else floor + (2.0 - floor) * ((sc / top) ** 3 if top > 0 else 0)
        return out

    def _turn_length(self, store: str, arms: list[Arm], arm: Arm) -> int:
        base = int(self.cfg.get("slice_checks") or 20)
        return max(1, round(base * self._weights(store, arms)[arm.key]))

    def _balance_note(self, store: str, key: str, ok: bool) -> None:
        row = self.saved["balance"].setdefault(store, {}).setdefault(key, [0.0, 0.0])
        row[0] *= DECAY
        row[1] *= DECAY
        row[0 if ok else 1] += 1.0
        self._save_soon()

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
            arm = arms[st["idx"] % len(arms)]
            if st["used"] >= self._turn_length(store, arms, arm):
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
            self._balance_note(store, arm.key, ok)
            if not arm.control:
                self._count(arm, ok, kind)
        if self.tracker and not arm.control:
            self.tracker.record(arm.key, store, ok, kind)

    def fail(self, store: str, arm: Arm, why: str = "error") -> None:
        """The method itself failed to load a page (not a block, and not 'cannot run here'). Counts
        against it for the auto-stop rule, and it takes a short rest at this store."""
        if arm.control:
            return
        with self.lock:
            st = self.state.setdefault(store, {"idx": 0, "used": 0, "rest": {}, "current": ""})
            st["rest"][arm.key] = time.time() + 60
            st["idx"] += 1
            st["used"] = 0
            self._trace(store, arm.key, "failed", why)
            self._balance_note(store, arm.key, False)
            self._count(arm, False, why)

    def _count(self, arm: Arm, ok: bool, kind: str) -> None:
        """Add one attempt to the arm's count since it was switched on, and stop it if it is failing
        too often. Call with the lock held."""
        w = self.saved["window"].setdefault(arm.key, {"attempts": 0, "fails": 0, "since": round(time.time())})
        w["attempts"] += 1
        if not ok:
            w["fails"] += 1
            w["last_kind"] = kind
        c = self.cfg
        if (c.get("auto_stop", True) and arm.key in self.active_keys() and w["attempts"] > int(c.get("stop_after") or 25)
                and 100.0 * w["fails"] / w["attempts"] >= float(c.get("stop_fail_pct") or 50)):
            pct = round(100.0 * w["fails"] / w["attempts"])
            self._turn_off(arm.key)
            self.saved["stopped"][arm.key] = {"at": round(time.time()), "attempts": w["attempts"], "fails": w["fails"],
                                               "pct": pct, "last_kind": w.get("last_kind", "")}
            self._event("auto_stop", arm.key, f"{w['fails']} of {w['attempts']} failed or were blocked ({pct}%)")
            self._trace("-", arm.key, "auto_stopped", f"{w['fails']}/{w['attempts']}")
            if self.log:
                self.log.info("Trial method '%s' was stopped automatically: %d of %d attempts failed or were blocked (%d%%). "
                              "Switch it back on in the Methods lab if you want to try it again.",
                              arm.key, w["fails"], w["attempts"], pct)

    def _save_soon(self) -> None:
        """Counters change on every check, so write them out every 10 attempts, not every time."""
        self._pending = getattr(self, "_pending", 0) + 1
        if self._pending >= 10:
            self._pending = 0
            self._save()

    # ---- switching methods on and off (the buttons) ----------------------------------------
    def _turn_off(self, key: str) -> None:
        active = [k for k in self.active_keys() if k != key]
        self.saved["active"] = active
        self.raw.setdefault("trials", {})["active"] = list(active)
        self._save()

    def set_active(self, key: str, on: bool) -> tuple[bool, str]:
        arm = BY_KEY.get(key)
        if arm is None or arm.control:
            return False, "That method is always on."
        with self.lock:
            active = [k for k in self.active_keys() if k != key]
            if on:
                active.append(key)
                self.saved["window"][key] = {"attempts": 0, "fails": 0, "since": round(time.time())}   # a fresh count
                self.saved["stopped"].pop(key, None)
                self.unavailable.pop(key, None)
                for st in self.state.values():
                    st["rest"].pop(key, None)
            self.saved["active"] = active
            self.raw.setdefault("trials", {})["active"] = list(active)
            self._event("on" if on else "off", key, "by you")
            self._trace("-", key, "switched_on" if on else "switched_off", "by you")
            self._save()
        return True, f"{arm.label} is {'on' if on else 'off'}."

    def best_keys(self, n: int = 3) -> list[str]:
        """Trial methods with the lowest failure rate so far (at least MIN_FOR_BEST checks), best first."""
        agg: dict[str, list[int]] = {}
        if self.tracker:
            for r in self.tracker.rows():
                a = agg.setdefault(r["method"], [0, 0])
                a[0] += r["checks"]
                a[1] += r["blocks"]
        ranked = [(agg[a.key][1] / agg[a.key][0], -agg[a.key][0], a.key) for a in CATALOG
                  if not a.control and a.key in agg and agg[a.key][0] >= MIN_FOR_BEST]
        return [k for _, _, k in sorted(ranked)[:n]]

    def keep_best(self, n: int = 3) -> tuple[bool, str]:
        best = self.best_keys(n)
        if not best:
            return False, f"Not enough data yet. A method needs {MIN_FOR_BEST} checks before it can be ranked."
        for a in CATALOG:
            if not a.control:
                self.set_active(a.key, a.key in best)
        return True, "Kept on: " + ", ".join(BY_KEY[k].label for k in best) + "."

    def all_off(self) -> tuple[bool, str]:
        for a in CATALOG:
            if not a.control:
                self.set_active(a.key, False)
        return True, "All trial methods are off. The normal methods carry on."

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

    def _balance_view(self) -> list[dict]:
        """For each store that has numbers: how the checks are being shared out right now."""
        out = []
        with self.lock:
            for store, rows in sorted(self.saved["balance"].items()):
                arms = [BY_KEY[k] for k in rows if k in BY_KEY and (BY_KEY[k].control or k in self.active_keys())]
                if len(arms) < 2:
                    continue
                w = self._weights(store, arms)
                total = sum(w.values()) or 1.0
                out.append({"store": store, "arms": [
                    {"key": a.key, "label": a.label, "share": round(100 * w[a.key] / total),
                     "rate": None if self._rate(store, a.key)[0] is None else round(100 * self._rate(store, a.key)[0]),
                     "n": round(self._rate(store, a.key)[1])} for a in sorted(arms, key=lambda x: -w[x.key])]})
        return out

    # ---- view for the control panel ------------------------------------------------
    def snapshot(self) -> dict:
        now = time.time()
        with self.lock:
            current = {s: st["current"] for s, st in self.state.items() if st["current"]}
            resting = [{"store": s, "arm": k, "minutes": int((t - now) / 60) + 1}
                       for s, st in self.state.items() for k, t in st["rest"].items() if t > now]
            active = set(self.active_keys())
            win = {k: dict(v) for k, v in self.saved["window"].items()}
            stopped = {k: dict(v) for k, v in self.saved["stopped"].items()}
            events = list(self.saved["events"])
            best = self.best_keys(3)
        c = self.cfg
        bal = self._balance_view()
        return {
            "auto_balance": bool(c.get("auto_balance", True)),
            "balance": bal,
            "enabled": self.enabled,
            "slice_checks": int(self.cfg.get("slice_checks") or 20),
            "auto_stop": bool(c.get("auto_stop", True)),
            "stop_after": int(c.get("stop_after") or 25),
            "stop_fail_pct": int(c.get("stop_fail_pct") or 50),
            "arms": [{"key": a.key, "label": a.label, "family": a.family, "idea": a.idea, "source": a.source,
                      "control": a.control, "on": a.control or a.key in active,
                      "unavailable": self.unavailable.get(a.key, ""),
                      "attempts": win.get(a.key, {}).get("attempts", 0), "fails": win.get(a.key, {}).get("fails", 0),
                      "stopped": stopped.get(a.key), "best": a.key in best} for a in CATALOG],
            "events": events[-12:],
            "current": current,
            "resting": resting,
        }
