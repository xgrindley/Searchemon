"""Recognizes sealed Pokemon TCG products from a listing title.

Decides three things for a title like "Pokemon TCG: Mega Evolution Elite
Trainer Box": is it a sealed Pokemon card product (not sleeves, a plush, a
video game, a reseller lot), which product type it is, and that type's MSRP.

MSRPs are US retail prices from two collector price guides checked in
October 2026 (see the user guide's Sources). When the two disagree or a type
spans several prices, the cap is the highest normal retail price for that
type, so a real retail listing is never filtered out; third-party sellers are
excluded separately. Every value can be changed in the control panel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .util import normalize_text


@dataclass(frozen=True)
class ProductType:
    key: str
    label: str
    patterns: tuple[str, ...]      # regexes on normalized text, first type that matches wins
    msrp: float | None
    priority: int                  # lower = checked first when there are many products
    strong: bool = True            # a clear sealed-product name; weak = a generic word like "box"


# Order matters: specific before general ("pokemon center elite trainer box" before "elite trainer box").
TYPES: tuple[ProductType, ...] = (
    ProductType("pc_etb", "Pokemon Center Elite Trainer Box", (r"pokemon center.*elite trainer box", r"elite trainer box.*pokemon center"), 59.99, 1),
    ProductType("etb", "Elite Trainer Box", (r"elite trainer box", r"\betb\b"), 49.99, 1),
    ProductType("pc_booster_box", "Pokemon Center Booster Box", (r"pokemon center.*booster (box|display)",), 179.64, 2),
    ProductType("booster_box", "Booster Box (36 packs)", (r"booster (box|display)(?! bundle)", r"\b36 (booster )?packs?\b"), 161.64, 2),
    ProductType("booster_bundle", "Booster Bundle", (r"booster bundle",), 26.99, 1),
    ProductType("upc", "Ultra Premium Collection", (r"ultra[ -]?premium collection",), 179.99, 2),
    ProductType("spc", "Super Premium Collection", (r"super[ -]?premium collection",), 89.99, 2),
    ProductType("premium_figure", "Premium Figure Collection", (r"premium figure collection",), 69.99, 3),
    ProductType("premium_poster", "Premium Poster Collection", (r"premium poster collection",), 39.99, 3),
    ProductType("premium_collection", "Premium Collection", (r"premium collection",), 49.99, 3),
    ProductType("build_battle_stadium", "Build & Battle Stadium", (r"build and battle stadium",), None, 3),
    ProductType("build_battle", "Build & Battle Box", (r"build and battle",), 29.99, 3),
    ProductType("binder_collection", "Binder Collection", (r"binder collection",), 31.99, 4),
    ProductType("poster_collection", "Poster Collection", (r"poster collection",), 14.99, 4),
    ProductType("tech_sticker", "Tech Sticker Collection", (r"tech sticker",), 14.99, 4),
    ProductType("mini_tin", "Mini Tin", (r"mini tin",), 9.99, 3),
    ProductType("tin", "Tin", (r"\btins?\b",), 27.99, 3),
    ProductType("three_pack", "3-Pack Blister", (r"\b3 ?(pack|pk)\b.*blister", r"blister.*\b3 ?(pack|pk)\b", r"three booster", r"\b3 booster packs?\b"), 14.99, 3),
    ProductType("checklane", "Checklane Blister", (r"checklane", r"check lane", r"\b1 ?pack blister", r"single pack blister"), 5.99, 4),
    ProductType("two_pack", "2-Pack Blister", (r"\b2 ?(pack|pk)\b.*blister", r"two booster"), 9.99, 4),
    ProductType("ex_box", "ex Box", (r"\bex box\b", r"\bex collection box\b"), 24.99, 3),
    ProductType("league_battle_deck", "League Battle Deck", (r"league battle deck",), 35.00, 5),
    ProductType("deluxe_battle_deck", "Deluxe Battle Deck", (r"deluxe battle deck",), 30.00, 5),
    ProductType("battle_deck", "Battle Deck", (r"battle deck", r"theme deck", r"starter deck"), 15.00, 5),
    ProductType("collector_chest", "Collector Chest", (r"collector s? chest", r"\bchest\b"), None, 4),
    ProductType("trainer_toolkit", "Trainer's Toolkit", (r"trainer s? toolkit",), None, 5),
    ProductType("battle_academy", "Battle Academy", (r"battle academy",), None, 5),
    ProductType("holiday_calendar", "Holiday Calendar", (r"(holiday|advent) calendar",), None, 5),
    ProductType("sleeved_booster", "Sleeved Booster Pack", (r"sleeved booster",), 5.99, 4),
    ProductType("booster_pack", "Booster Pack", (r"booster pack", r"\bbooster\b(?! (bundle|box|display))"), 5.99, 4),
    ProductType("collection", "Collection Box", (r"collection( box)?\b", r"\bbox\b"), None, 4, False),
)
TYPE_BY_KEY = {t.key: t for t in TYPES}

POKEMON = re.compile(r"\bpokemon\b")
TCG_SIGNALS = re.compile(r"trading card|\btcg\b|\bcard game\b|booster|elite trainer|collection|blister|\btin\b|battle deck|cards?\b")

# Never new retail sealed product, whatever else the title says.
HARD_EXCLUDE = (
    (re.compile(r"\blots?\b|\brepack(ed|s)?\b|\bmystery\b|\bgrab bag\b"), "lot, repack or mystery item"),
    (re.compile(r"\bgraded\b|\bpsa\b|\bbgs\b|\bcgc\b|\bslab\b|\bsingle card\b"), "graded or single card"),
    (re.compile(r"\bproxy\b|\bcustom\b|\bfan made\b|\borica\b|\breplica\b|\bunofficial\b"), "unofficial product"),
    (re.compile(r"\bcase of\b|\bbundle of \d|\bset of \d|\b\d+ ?x\b|\bx ?\d+\b|\bpack of \d|\blot of\b"), "multi-unit reseller bundle"),
    (re.compile(r"\bmagic the gathering\b|\byu gi oh\b|\bone piece card\b|\blorcana\b|\bdragon ball\b|\bdigimon\b|\bflesh and blood\b|\bsports cards?\b"), "another card game"),
)
# Pokemon-branded things that are not card product. Only applied when the title
# does not clearly name a sealed product, because real listings often mention
# contents ("Elite Trainer Box with sleeves and dice").
SOFT_EXCLUDE = (
    (re.compile(r"\b(card )?sleeves?\b(?! booster)"), "card sleeves"),
    (re.compile(r"\bdeck box\b|\bdeck case\b"), "deck box"),
    (re.compile(r"\bbinder\b(?! collection)|\bportfolio\b|\balbum\b"), "binder or portfolio"),
    (re.compile(r"\bplaymat\b|\bplay mat\b|\bdice\b|\bcoin\b(?!s? and)|\bdamage counters?\b"), "play accessory"),
    (re.compile(r"\btoploaders?\b|\bcard savers?\b|\bpage protectors?\b|\bstorage\b"), "card storage"),
    (re.compile(r"\bplush\b|\bplushie\b|\bfigure\b(?! collection)|\bfigurine\b|\baction figure\b|\btoy\b(?!s? and)"), "toy or figure"),
    (re.compile(r"\bnintendo\b|\bswitch\b|\bvideo game\b|\bscarlet and violet game\b|\blegends\b(?!.*(trading|tcg))"), "video game"),
    (re.compile(r"\bcode cards?\b|\bonline codes?\b|\bdigital\b|\bdownload\b"), "code card or digital"),
    (re.compile(r"\bt ?shirt\b|\bhoodie\b|\bbackpack\b|\blunch\b|\bcostume\b|\bpuzzle\b|\bbook\b|\bguide\b|\bcalendar\b|\bsticker book\b"), "merchandise"),
    (re.compile(r"\bholo rare\b|\bpromo card\b"), "single card"),
)
NON_ENGLISH = re.compile(r"\bjapanese\b|\bjapan\b|\bkorean\b|\bchinese\b|\bsimplified\b|\btraditional chinese\b|\bthai\b|\bindonesian\b")
PREORDER = re.compile(r"\bpre ?order\b|\bpresale\b|\bcoming soon\b")


@dataclass
class Classified:
    is_tcg: bool
    type_key: str | None
    type_label: str
    msrp: float | None
    reason: str = ""
    language: str = "en"
    priority: int = 9


def classify(title: str, *, allow_non_english: bool = False, msrp_overrides: dict | None = None) -> Classified:
    t = normalize_text(title)
    if not POKEMON.search(t):
        return Classified(False, None, "", None, "not a Pokemon product")
    for rx, why in HARD_EXCLUDE:
        if rx.search(t):
            return Classified(False, None, "", None, why)
    lang = "en"
    if NON_ENGLISH.search(t):
        lang = "other"
        if not allow_non_english:
            return Classified(False, None, "", None, "non-English product", lang)
    match = next((pt for pt in TYPES if any(re.search(p, t) for p in pt.patterns)), None)
    if match is None or not match.strong:
        for rx, why in SOFT_EXCLUDE:
            if rx.search(t):
                return Classified(False, None, "", None, why, lang)
    if match is not None:
        msrp = match.msrp
        if msrp_overrides and match.key in msrp_overrides:
            o = msrp_overrides[match.key]
            msrp = float(o) if o not in (None, "") else None
        return Classified(True, match.key, match.label, msrp, "", lang, match.priority)
    if TCG_SIGNALS.search(t):
        return Classified(True, "other", "Other card product", None, "", lang, 6)
    return Classified(False, None, "", None, "no trading card signal in title", lang)


def type_settings(raw_cfg: dict) -> dict[str, dict]:
    """Per-type settings from config merged over built-in defaults: {key: {msrp, alert, label}}."""
    user = (raw_cfg.get("product_types") or {})
    out = {}
    for pt in TYPES:
        u = user.get(pt.key) or {}
        out[pt.key] = {
            "label": pt.label,
            "msrp": u["msrp"] if "msrp" in u else pt.msrp,
            "alert": bool(u.get("alert", True)),
            "priority": pt.priority,
        }
    u = user.get("other") or {}
    out["other"] = {"label": "Other card product", "msrp": u.get("msrp"), "alert": bool(u.get("alert", True)), "priority": 6}
    return out
