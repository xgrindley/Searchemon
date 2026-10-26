"""A/B trials for the app's own features, so you can see whether each one actually helps.

With the trial on, each check randomly runs with or without a feature (about half each). The
outcome (loaded or blocked) is counted under "with" or "without", saved in data/feature-stats.json,
and shown in the Methods lab. With it off, every feature simply follows its setting.
"""
from __future__ import annotations

import os
import random
import threading

from .util import atomic_write_json, read_json

FEATURES = {
    "learned_routing": "Learned routing (reliable methods go first)",
    "tab_rotation": "Tab rotation (several tabs per store)",
}
MIN_FOR_VERDICT = 30      # checks on each side before a verdict is offered


class FeatureTrial:
    def __init__(self, data_dir: str, raw_getter=lambda: {}):
        self.path = os.path.join(data_dir, "feature-stats.json")
        self.lock = threading.Lock()
        self.data: dict = read_json(self.path, {})
        self.raw_getter = raw_getter
        self.dirty = 0

    def active(self) -> bool:
        return bool((self.raw_getter().get("browser") or {}).get("feature_trial", True))

    def decide(self, feature: str, configured: bool = True) -> bool:
        """True when the feature should be used for this check."""
        if not configured:
            return False
        return random.random() < 0.5 if self.active() else True

    def record(self, feature: str, used: bool, ok: bool) -> None:
        if not self.active():
            return
        with self.lock:
            e = self.data.setdefault(feature, {}).setdefault("with" if used else "without", {"checks": 0, "blocks": 0})
            e["checks"] += 1
            e["blocks"] += 0 if ok else 1
            self.dirty += 1
            flush = self.dirty >= 20
        if flush:
            self.save()

    def save(self) -> None:
        with self.lock:
            self.dirty = 0
            atomic_write_json(self.path, self.data)

    def rows(self) -> list[dict]:
        out = []
        with self.lock:
            for key, label in FEATURES.items():
                d = self.data.get(key) or {}
                w, wo = d.get("with") or {"checks": 0, "blocks": 0}, d.get("without") or {"checks": 0, "blocks": 0}
                out.append({"feature": key, "label": label, "with_checks": w["checks"], "with_blocks": w["blocks"],
                            "without_checks": wo["checks"], "without_blocks": wo["blocks"],
                            "verdict": self.verdict(w, wo)})
        return out

    @staticmethod
    def verdict(w: dict, wo: dict) -> str:
        if w["checks"] < MIN_FOR_VERDICT or wo["checks"] < MIN_FOR_VERDICT:
            return "Too early to say"
        rw, rwo = w["blocks"] / w["checks"], wo["blocks"] / wo["checks"]
        if abs(rw - rwo) < 0.03:
            return "No clear difference"
        return "Helping" if rw < rwo else "Not helping"
