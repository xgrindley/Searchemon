"""Signals from outside the stores: restock posts from the community, and the newest set names.

Community tips. People post live restocks and pre-orders to r/PokemonTCGDeals, often minutes before a store's own
search shows the product. The app reads the subreddit's public list of new posts (no account, no sign-in, one
small request every few minutes, sent with an honest User-Agent that names the app). A post that names a store you
monitor makes the matching products at that store due for a check right away, and a post that links straight to a
product page at one of your stores adds that product to Found for you. Nothing is ever bought, and nothing about
you is sent: the request is a plain read of a public page. Idea from kadarius0719/drip-drop-pokemon.

New set names. Product searches find more when they use the newest set's name ("Phantasmal Flames") and not only
generic words ("pokemon booster bundle"). Once a day the app reads the list of Pokemon sets from TCGCSV, a free
daily mirror of TCGplayer's catalog (one request a day, as its rules ask), and adds the sets released in the last
few months, plus announced ones, to the rotating store searches.

Both are switched on under Products > Finding, and can be switched off there or in config.yaml (community:).
"""
from __future__ import annotations

import os
import re
import threading
import time

import requests

from .tcg import classify
from .util import atomic_write_json, clean_url, normalize_text, read_json

FILE = "community.json"
SUBREDDIT = "PokemonTCGDeals"
FEED_URL = "https://www.reddit.com/r/{sub}/new.json"
POLL_S = 5 * 60                 # how often the feed is read
REST_START_S = 30 * 60          # first pause after Reddit refuses; doubles up to REST_MAX_S
REST_MAX_S = 6 * 3600
MAX_AGE_S = 3 * 3600            # posts older than this are history, not tips
KEEP_TIPS = 40
KEEP_SEEN = 600
SETS_URL = "https://tcgcsv.com/tcgplayer/3/groups"     # category 3 is the Pokemon TCG
SETS_EVERY_S = 24 * 3600
RECENT_DAYS = 240               # sets released within this many days (or announced) are searched for
MAX_SETS = 6

# How people name the stores in post titles, and the store each name means (most specific first).
STORE_WORDS: list[tuple[str, str]] = [
    ("pokemon center", "pokemoncenter"), ("best buy", "bestbuy"), ("bestbuy", "bestbuy"), ("target", "target"),
    ("walmart", "walmart"), ("gamestop", "gamestop"), ("game stop", "gamestop"), ("costco", "costco"),
    ("sam s club", "samsclub"), ("sams club", "samsclub"), ("sams", "samsclub"), ("barnes and noble", "barnesandnoble"),
    ("barnes", "barnesandnoble"), ("books a million", "booksamillion"), ("booksamillion", "booksamillion"),
    ("amazon", "amazon"), ("dick s", "dicks"), ("dicks", "dicks"), ("safeway", "safeway"), ("raley s", "raleys"),
    ("raleys", "raleys"), ("walgreens", "walgreens"), ("cvs", "cvs"), ("macy s", "macys"), ("macys", "macys"),
    ("kohl s", "kohls"), ("kohls", "kohls"), ("kroger", "kroger"), ("fred meyer", "kroger"), ("smith s", "kroger"),
]
# Words that say nothing about which product a post is about.
FILLER = set("""pokemon tcg trading card game cards card the a an and of for in at on to with is are now live back
restock restocked restocking instock in stock online available deal deals price sale msrp new box boxes ea each
just got up get go via""".split())
# Groups in the set list that are not sets you would search a store for.
NOT_A_SET = re.compile(r"promo|prize pack|trainer kit|jumbo|world championship|mcdonald|league|deck exclusive|"
                       r"miscellaneous|trick or trade|professor program|blister exclusives|battle academy|theme deck|"
                       r"\bpop\b|futsal|kids wb", re.I)


def ua(version: str) -> str:
    return f"windows:searchemon:{version} (personal restock monitor; read-only)"


def stores_named(text: str) -> list[str]:
    """Store keys named in a post title, in the order they appear."""
    t = f" {normalize_text(text)} "
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for word, key in STORE_WORDS:
        for m in re.finditer(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", t):
            if any(a <= m.start() < b for a, b in taken):
                continue                          # "sams" inside "sams club" was already counted
            taken.append((m.start(), m.end()))
            found.append((m.start(), key))
    out: list[str] = []
    for _, key in sorted(found):
        if key not in out:
            out.append(key)
    return out


# Short names people use in posts.
ABBREVIATIONS = {"etb": "elite trainer", "etbs": "elite trainer", "bb": "booster bundle", "upc": "ultra premium collection",
                 "spc": "super premium collection", "ppc": "premium collection", "bnb": "build and battle"}


def product_words(text: str) -> set[str]:
    """The words of a title that identify the product (set name, product type), without prices and filler."""
    t = re.sub(r"\$?\d+(\.\d+)?", " ", normalize_text(text))
    words = " ".join(ABBREVIATIONS.get(w, w) for w in t.split()).split()
    return {w for w in words if len(w) > 2 and w not in FILLER and not any(w == s for s, _ in STORE_WORDS)}


# Words that name a kind of product rather than a set ("elite trainer box"), so they do not tell sets apart.
TYPE_WORDS = set("""elite trainer booster bundle display collection premium ultra super tin tins mini blister pack packs
build battle binder poster illustration case sleeved checklane stacking deck decks figure surprise bundles three
two single""".split())


def name_words(text: str) -> set[str]:
    """The product words that name the set or the featured Pokemon (for matching a post to a listing)."""
    return product_words(text) - TYPE_WORDS


def clean_title(title: str) -> str:
    """'[Target] Pokemon TCG Phantasmal Flames ETB - $49.99 (back in stock)' -> the product part."""
    t = re.sub(r"^\s*[\[(][^\])]{1,40}[\])]\s*", "", title or "")
    t = re.sub(r"\s*[-|@]\s*\$?\d[\d,.]*.*$", "", t)
    t = re.sub(r"\s*\$\d[\d,.]*.*$", "", t)
    return re.sub(r"\s+", " ", t).strip()[:160]


def parse_posts(children: list, seen: set, now: float) -> list[dict]:
    """Turn the feed's new posts into tips. Only Pokemon TCG posts that are new to us and recent count."""
    tips = []
    for child in children or []:
        post = child.get("data") if isinstance(child, dict) else None
        if not isinstance(post, dict):
            continue
        pid = str(post.get("id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        created = float(post.get("created_utc") or 0)
        if created and now - created > MAX_AGE_S:
            continue
        title = str(post.get("title") or "").strip()
        link = str(post.get("url_overridden_by_dest") or post.get("url") or "")
        if not title or post.get("removed_by_category") or post.get("stickied"):
            continue
        product = clean_title(title) or title
        if "pokemon" not in normalize_text(product):
            product = "Pokemon TCG " + product          # it is a Pokemon TCG subreddit; titles often skip the word
        if not classify(product).is_tcg:
            continue                                    # plush, sleeves, single cards and the like
        permalink = str(post.get("permalink") or "")
        tips.append({
            "id": pid, "t": created or now, "title": title[:200], "product": product,
            "stores": stores_named(title + " " + link),
            "link": clean_url(link) if link.startswith("http") and "reddit.com" not in link and "redd.it" not in link else "",
            "post": "https://www.reddit.com" + permalink if permalink.startswith("/") else "",
            "woke": 0, "added": [],
        })
    return tips


def parse_sets(data, now: float) -> list[str]:
    """Names of recent and announced sets, newest first, from TCGCSV's group list."""
    rows = data.get("results") if isinstance(data, dict) else data
    out: list[tuple[float, str]] = []
    for g in rows or []:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name") or "").strip()
        if not name or NOT_A_SET.search(name):
            continue
        name = re.sub(r"^[A-Z]{1,4}\d{0,3}[a-z]?\s*:\s*", "", name).strip()     # "ME02: Phantasmal Flames"
        if not name or len(name) > 40:
            continue
        t = _when(g.get("publishedOn"))
        if t is None or now - t > RECENT_DAYS * 86400:
            continue
        out.append((t, name))
    names: list[str] = []
    for _, name in sorted(out, reverse=True):
        if normalize_text(name) not in (normalize_text(n) for n in names):
            names.append(name)
    return names[:MAX_SETS]


def _when(value) -> float | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(0), "%Y-%m-%d"))
    except (ValueError, OverflowError):
        return None


class Community:
    def __init__(self, data_dir: str, log, version: str = "4"):
        self.path = os.path.join(data_dir, FILE)
        self.log = log
        self.version = version
        self.lock = threading.Lock()
        d = read_json(self.path, {}) or {}
        self.seen: list[str] = [str(x) for x in d.get("seen") or []][-KEEP_SEEN:]
        self.tips: list[dict] = [t for t in d.get("tips") or [] if isinstance(t, dict)][-KEEP_TIPS:]
        self.sets: dict = d.get("sets") if isinstance(d.get("sets"), dict) else {}
        self.feed: dict = d.get("feed") if isinstance(d.get("feed"), dict) else {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": ua(version), "Accept": "application/json"})

    # ---- community tips -------------------------------------------------------------
    def feed_due(self, now: float | None = None) -> bool:
        now = now or time.time()
        return now >= float(self.feed.get("next", 0))

    def poll_feed(self, now: float | None = None) -> list[dict]:
        """Read the newest posts if it is time. Returns new tips (never raises)."""
        now = now or time.time()
        if not self.feed_due(now):
            return []
        first = not self.seen
        try:
            r = self.session.get(FEED_URL.format(sub=SUBREDDIT), params={"limit": 25, "raw_json": 1}, timeout=20)
            if r.status_code != 200:
                raise ValueError(f"answered {r.status_code}")
            children = r.json()["data"]["children"]
        except Exception as exc:
            rest = min(REST_MAX_S, max(REST_START_S, float(self.feed.get("rest", 0)) * 2))
            self.feed.update({"next": now + rest, "rest": rest, "problem": str(exc)[:120], "problem_at": now})
            self.log.info("Community tips: Reddit did not answer (%s); trying again in %d min", str(exc)[:60], rest // 60)
            self.save()
            return []
        seen = set(self.seen)
        tips = parse_posts(children, seen, now)
        with self.lock:
            self.seen = (self.seen + [p for p in seen if p not in self.seen])[-KEEP_SEEN:]
            self.feed.update({"next": now + POLL_S, "rest": 0, "ok_at": now, "problem": ""})
            if first:
                tips = []                  # the first read only learns what is already there: old posts are not tips
            self.tips = (self.tips + tips)[-KEEP_TIPS:]
        self.save()
        return tips

    def note_used(self, tip: dict, woke: int, added: list[str]) -> None:
        with self.lock:
            for t in self.tips:
                if t.get("id") == tip.get("id"):
                    t["woke"], t["added"] = woke, added
        self.save()

    # ---- set names ---------------------------------------------------------------------
    def set_names(self) -> list[str]:
        return list(self.sets.get("names") or [])

    def refresh_sets(self, now: float | None = None) -> bool:
        """Once a day: read the set list. Returns True when it changed. Never raises."""
        now = now or time.time()
        if now - float(self.sets.get("t", 0)) < SETS_EVERY_S:
            return False
        try:
            r = self.session.get(SETS_URL, timeout=30, headers={"User-Agent": f"Searchemon/{self.version}"})
            if r.status_code != 200:
                raise ValueError(f"answered {r.status_code}")
            names = parse_sets(r.json(), now)
        except Exception as exc:
            self.sets["t"] = now - SETS_EVERY_S + 3 * 3600      # try again in 3 hours
            self.log.info("New set names: the set list could not be read (%s)", str(exc)[:80])
            self.save()
            return False
        changed = names != self.set_names()
        self.sets = {"t": now, "names": names or self.set_names()}
        if changed and names:
            self.log.info("New set names for store searches: %s", ", ".join(names))
        self.save()
        return changed

    # ---- view and storage ------------------------------------------------------------
    def view(self) -> dict:
        with self.lock:
            return {"tips": list(reversed(self.tips[-20:])), "sets": self.set_names(),
                    "feed_ok_at": self.feed.get("ok_at"), "feed_problem": self.feed.get("problem", ""),
                    "sets_at": self.sets.get("t")}

    def save(self) -> None:
        with self.lock:
            data = {"seen": self.seen, "tips": self.tips, "sets": self.sets, "feed": self.feed}
        try:
            atomic_write_json(self.path, data)
        except OSError:
            pass
