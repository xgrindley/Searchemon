"""Loads config.yaml into typed objects with sane defaults."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .geo import Area, build_areas
from .util import normalize_text

ALL_RETAILERS = ("bestbuy", "target", "kroger", "walmart", "pokemoncenter", "gamestop", "costco", "samsclub",
                 "barnesandnoble", "booksamillion", "amazon", "dicks", "safeway", "raleys", "walgreens", "cvs", "web")

DEFAULTS: dict[str, Any] = {
    "discord": {
        "webhooks": {"default": "", "online": "", "in_store": ""},
        "mention_role_id": "",
        "mention_user_id": "",
        "username": "Restock Monitor",
    },
    "location": {"zip": "", "radius_miles": 25},
    "areas": [],
    "settings": {
        "alert_on_startup": True,
        "alert_cooldown_minutes": 30,
        "notify_sold_out": False,
        "msrp_tolerance_pct": 5,
        "retailer_sold_only": True,
        "windows_toast": True,
        "in_store": True,
        "max_search_results": 24,
        "debug_dump": False,
        "alerts_paused": False,
        "ignored_items": [],
        "excluded_stores": [],
        "confirm_restocks": True,
        "min_store_qty": 1,
        # Wait this long (plus up to 50% random) before the next page on the same store.
        "link_delay_seconds": 4,
        "allow_non_english": False,
    },
    "control_panel": {"enabled": True, "port": 8765, "allow_lan": False, "pin": ""},
    "browser": {
        "enabled": True,
        "channel": "msedge",
        # Each profile is its own browser with its own cookies. Checks rotate across them.
        "profiles": [{"name": "edge", "channel": "msedge"}, {"name": "chrome", "channel": "chrome"}],
        "show_window": False,
        # How many tabs a store's pages rotate through, so one tab is not reloaded over and over.
        "tabs_per_site": 3,
        "headless": False,
        "ask_me_to_verify": True,
        # Your own Chrome, started with start-my-chrome.ps1. Whenever it is running it joins
        # the profiles and gets these stores first, since a real Chrome is refused least.
        "own_chrome_port": 9222,
        # Your own Edge (start-my-edge.ps1): a second real browser to compare against Chrome. 0 turns it off.
        "own_edge_port": 9223,
        # When a store refuses a plain data request, repeat it from inside the store's own page in a real browser.
        "page_fetch": True,
        # Every N minutes, per store, load one page through every method at once and record the outcome (0 = off).
        "compare_every_minutes": 15,
        # Use what the side-by-side tests found: methods that load a store reliably get its checks first.
        "learn_from_compare": True,
        # Run about half of the checks without each new feature and count the blocks, so Methods lab can show whether it helps.
        "feature_trial": True,
        "close_own_on_exit": True,
        "own_chrome_sites": ["cvs.com", "dickssportinggoods.com", "gamestop.com"],
        "notify_discord": False,
        "min_interval_seconds": 120,
    },
    "schedule": {
        "learn_from_history": True,
        "fast_factor": 0.5,
        "slow_factor": 3,
        "min_interval_seconds": 30,
        "fast_windows": [],
        "slow_windows": [],
    },
    "keywords": {
        "include_any": [],
        "include_all": [],
        "exclude": [],
        "apply_to_watchlist": False,
    },
    "price_rules": [],
    "retailers": {
        "bestbuy": {"enabled": False, "api_key": "", "interval_seconds": 60},
        "target": {
            "enabled": True,
            "api_key": "9f36aeafbe60771e321a7cc95a78140772ab3e96",
            "store_ids": [],
            "interval_seconds": 90,
        },
        "kroger": {"enabled": False, "client_id": "", "client_secret": "", "interval_seconds": 300,
                   "max_stores": 5, "store_ids": []},
        "walmart": {"enabled": True, "interval_seconds": 180, "fetch_mode": "auto",
                    "consumer_id": "", "private_key_file": "", "key_version": "1", "publisher_id": ""},
        "pokemoncenter": {"enabled": True, "interval_seconds": 900, "fetch_mode": "browser", "watch_queue": True},
        "gamestop": {"enabled": True, "interval_seconds": 240, "fetch_mode": "auto"},
        "costco": {"enabled": True, "interval_seconds": 300, "fetch_mode": "auto"},
        "samsclub": {"enabled": True, "interval_seconds": 300, "fetch_mode": "auto"},
        "barnesandnoble": {"enabled": True, "interval_seconds": 300, "fetch_mode": "auto"},
        "booksamillion": {"enabled": True, "interval_seconds": 300, "fetch_mode": "auto"},
        "amazon": {"enabled": True, "interval_seconds": 300, "fetch_mode": "browser"},
        "dicks": {"enabled": True, "interval_seconds": 300, "fetch_mode": "browser"},
        "safeway": {"enabled": True, "interval_seconds": 300, "fetch_mode": "browser"},
        "raleys": {"enabled": True, "interval_seconds": 300, "fetch_mode": "auto"},
        "walgreens": {"enabled": True, "api_key": "", "interval_seconds": 240, "fetch_mode": "auto"},
        "cvs": {"enabled": True, "interval_seconds": 240, "fetch_mode": "auto"},
        "web": {"enabled": True, "interval_seconds": 180, "fetch_mode": "auto"},
    },
    "jitter_seconds": 20,
    "watchlist": [],
    "searches": [],
    "product_types": {},
    "notify": {},
    "discovery": {
        "enabled": True,
        "retailers": ["target", "bestbuy", "walmart", "kroger", "dicks"],
        "queries": ["pokemon trading card game", "pokemon tcg"],
        "refresh_hours": 6,
        "alert_new_listings": True,
        "items_per_cycle": {"target": 6, "bestbuy": 20, "kroger": 50, "walmart": 0, "dicks": 3},
        "places": True,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(v) for v in value if str(v).strip()]


@dataclass
class KeywordFilter:
    include_any: list[str] = field(default_factory=list)
    include_all: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict | None) -> "KeywordFilter":
        d = d or {}
        return cls(
            [normalize_text(x) for x in _as_list(d.get("include_any"))],
            [normalize_text(x) for x in _as_list(d.get("include_all"))],
            [normalize_text(x) for x in _as_list(d.get("exclude"))],
        )

    def merged(self, other: "KeywordFilter") -> "KeywordFilter":
        """Per-search filters add to (not replace) the global ones."""
        return KeywordFilter(
            list(dict.fromkeys(self.include_any + other.include_any)),
            list(dict.fromkeys(self.include_all + other.include_all)),
            list(dict.fromkeys(self.exclude + other.exclude)),
        )

    def matches(self, text: str) -> tuple[bool, str]:
        t = f" {normalize_text(text)} "
        for word in self.exclude:
            if f" {word} " in t or (len(word) > 4 and word in t):
                return False, f"excluded keyword '{word}'"
        for word in self.include_all:
            if word not in t:
                return False, f"missing required keyword '{word}'"
        if self.include_any and not any(word in t for word in self.include_any):
            return False, "no include keyword matched"
        return True, ""

    @property
    def empty(self) -> bool:
        return not (self.include_any or self.include_all or self.exclude)


@dataclass
class PriceRule:
    match: str
    max_price: float


@dataclass
class Watch:
    name: str
    upc: str = ""
    msrp: float | None = None
    ids: dict[str, str] = field(default_factory=dict)
    urls: list[str] = field(default_factory=list)
    retailers: list[str] = field(default_factory=list)
    in_store: bool = True
    enabled: bool = True
    auto: bool = False             # created by product discovery, not by you

    def wants(self, retailer: str) -> bool:
        return not self.retailers or retailer in self.retailers


@dataclass
class Search:
    name: str
    query: str
    retailers: list[str]
    keywords: KeywordFilter
    max_price: float | None = None
    in_store: bool = False
    enabled: bool = True


@dataclass
class Config:
    path: str
    raw: dict
    watchlist: list[Watch]
    searches: list[Search]
    keywords: KeywordFilter
    price_rules: list[PriceRule]
    areas: list[Area] = field(default_factory=list)

    @property
    def data_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(self.path)), "data")

    @property
    def settings(self) -> dict:
        return self.raw["settings"]

    @property
    def discord(self) -> dict:
        return self.raw["discord"]

    @property
    def location(self) -> dict:
        return self.raw["location"]

    def retailer_cfg(self, name: str) -> dict:
        return self.raw["retailers"].get(name, {})

    def enabled_retailers(self) -> list[str]:
        return [r for r in ALL_RETAILERS if self.retailer_cfg(r).get("enabled")]

    def price_limit_for(self, title: str) -> float | None:
        t = f" {normalize_text(title)} "
        for rule in self.price_rules:
            if rule.match and f" {rule.match} " in t:
                return rule.max_price
        return None


def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as fh:
        user = yaml.safe_load(fh) or {}
    raw = _merge(DEFAULTS, user)

    watchlist = []
    for i, w in enumerate(raw.get("watchlist") or []):
        if not isinstance(w, dict):
            continue
        ids = {k: str(v).strip() for k, v in (w.get("ids") or {}).items() if v not in (None, "")}
        watchlist.append(
            Watch(
                name=str(w.get("name") or f"Watch {i + 1}"),
                upc=str(w.get("upc") or "").strip(),
                msrp=float(w["msrp"]) if w.get("msrp") not in (None, "") else None,
                ids=ids,
                urls=_as_list(w.get("urls")),
                retailers=[r.lower() for r in _as_list(w.get("retailers"))],
                in_store=bool(w.get("in_store", True)),
                enabled=bool(w.get("enabled", True)),
            )
        )

    searches = []
    for i, s in enumerate(raw.get("searches") or []):
        if not isinstance(s, dict) or not s.get("query"):
            continue
        searches.append(
            Search(
                name=str(s.get("name") or s["query"]),
                query=str(s["query"]),
                retailers=[r.lower() for r in _as_list(s.get("retailers"))] or ["target", "bestbuy", "walmart"],
                keywords=KeywordFilter.from_dict(s.get("keywords")),
                max_price=float(s["max_price"]) if s.get("max_price") not in (None, "") else None,
                in_store=bool(s.get("in_store", False)),
                enabled=bool(s.get("enabled", True)),
            )
        )

    rules = [
        PriceRule(normalize_text(r.get("match", "")), float(r["max_price"]))
        for r in raw.get("price_rules") or []
        if isinstance(r, dict) and r.get("max_price") not in (None, "")
    ]

    return Config(
        path=path,
        raw=raw,
        watchlist=[w for w in watchlist if w.enabled],
        searches=[s for s in searches if s.enabled],
        keywords=KeywordFilter.from_dict(raw.get("keywords")),
        price_rules=rules,
        areas=build_areas(raw),
    )


def save_config(path: str, raw: dict, backup_dir: str | None = None) -> Config:
    """Validate a full settings dict, back up the old file, then write it.
    Raises ValueError with a readable message if the settings do not load."""
    import shutil
    import tempfile

    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("# Saved by the Restock Monitor control panel. See config.example.yaml for notes.\n")
            yaml.safe_dump(raw, fh, sort_keys=False, allow_unicode=True, width=1000)
        try:
            cfg = load_config(tmp)
        except Exception as exc:
            raise ValueError(f"Settings were not saved: {exc}") from exc
        if backup_dir and os.path.exists(path):
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy(path, os.path.join(backup_dir, "config.backup.yaml"))
        os.replace(tmp, path)
        cfg.path = path
        return cfg
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def validate(cfg: Config) -> list[str]:
    """Human-readable problems worth showing at startup."""
    problems = []
    hooks = {k: v for k, v in cfg.discord.get("webhooks", {}).items() if v}
    hooks.update({f"area {a.name}": a.webhook for a in cfg.areas if a.webhook})
    if not hooks:
        problems.append("No Discord webhook set: alerts will only show in the app.")
    for name, url in hooks.items():
        if not str(url).startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")):
            problems.append(f"Webhook '{name}' does not look like a Discord webhook URL.")
    wm = cfg.retailer_cfg("walmart")
    if wm.get("consumer_id") and not wm.get("private_key_file"):
        problems.append("Walmart.io Consumer ID is set but the private key file is empty, so the website is used instead.")
    if wm.get("private_key_file") and not os.path.exists(os.path.expanduser(str(wm.get("private_key_file")).strip('"'))):
        problems.append("The Walmart.io private key file was not found at that path.")
    if cfg.retailer_cfg("bestbuy").get("enabled") and not cfg.retailer_cfg("bestbuy").get("api_key"):
        problems.append("Best Buy is enabled but has no api_key (free at developer.bestbuy.com).")
    if cfg.settings.get("in_store") and not cfg.areas:
        problems.append("No area set (a ZIP code and radius), so in-store checks are off.")
    elif cfg.areas and not any(a.located for a in cfg.areas):
        problems.append("ZIP lookup is unavailable (run setup.ps1 to install the zipcodes package); "
                        "distances come from each store's own finder instead.")
    k = cfg.retailer_cfg("kroger")
    if k.get("enabled") and not (k.get("client_id") and k.get("client_secret")):
        problems.append("Kroger is on but has no client_id/client_secret (free at developer.kroger.com).")
    if not cfg.watchlist and not cfg.searches and not (cfg.raw.get("discovery") or {}).get("enabled", True):
        problems.append("Product list, searches and automatic discovery are all empty or off: nothing to check.")
    return problems
