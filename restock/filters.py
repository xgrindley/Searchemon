"""Decides whether an in-stock result is worth alerting on.

Checks, in order: seller (skip marketplace sellers), product type (a type you
turned off never alerts), price against MSRP, and keywords.

Which MSRP applies, most specific first: the product's own MSRP, the search's
max price, your "title contains" price rules, then the product type's MSRP.
"""
from __future__ import annotations

from .config import Config, KeywordFilter
from .models import StockResult
from .tcg import classify, type_settings


def annotate(result: StockResult, cfg: Config) -> None:
    """Fill in the product type from the title when the checker did not."""
    if result.type_key is None:
        c = classify(result.title, allow_non_english=True)
        if c.is_tcg:
            result.type_key, result.type_label = c.type_key, c.type_label


def tolerance_pct(cfg: Config, retailer: str) -> float:
    """How far over MSRP a store may be and still alert, in percent. Each store can
    have its own allowance (retailers.<store>.msrp_tolerance_pct); otherwise the
    general setting applies."""
    own = (cfg.raw.get("retailers") or {}).get(retailer, {}).get("msrp_tolerance_pct")
    if own not in (None, ""):
        return max(0.0, float(own))
    return max(0.0, float(cfg.settings.get("msrp_tolerance_pct") or 0))


def price_limit(result: StockResult, cfg: Config, search_max: float | None = None) -> float | None:
    if result.msrp:
        return result.msrp
    if search_max:
        return search_max
    rule = cfg.price_limit_for(result.title)
    if rule:
        return rule
    annotate(result, cfg)
    if result.type_key:
        msrp = type_settings(cfg.raw).get(result.type_key, {}).get("msrp")
        return float(msrp) if msrp not in (None, "") else None
    return None


def display_msrp(result: StockResult, cfg: Config) -> float | None:
    """The MSRP to show in an alert: the product's own, else its product type's
    (your Product types setting wins over the built-in list), else a title price rule."""
    if result.msrp:
        return float(result.msrp)
    annotate(result, cfg)
    if result.type_key:
        msrp = type_settings(cfg.raw).get(result.type_key, {}).get("msrp")
        if msrp not in (None, ""):
            return float(msrp)
    rule = cfg.price_limit_for(result.title)
    return float(rule) if rule else None


def passes(result: StockResult, cfg: Config, keywords: KeywordFilter | None = None,
           search_max: float | None = None, check_type: bool = True) -> tuple[bool, str]:
    settings = cfg.settings
    if settings.get("retailer_sold_only", True) and result.third_party:
        return False, "third-party seller"

    if check_type:
        annotate(result, cfg)
        if result.type_key and not type_settings(cfg.raw).get(result.type_key, {}).get("alert", True):
            return False, f"{result.type_label or result.type_key} alerts are off"

    limit = price_limit(result, cfg, search_max)
    if limit and result.price:
        pct = tolerance_pct(cfg, result.retailer)
        if result.price > limit * (1 + pct / 100) + 0.01:
            return False, (f"price ${result.price:.2f} is more than {pct:g}% over MSRP ${limit:.2f} "
                           f"(limit ${limit * (1 + pct / 100):.2f} at {result.retailer_name})")

    if keywords is not None and not keywords.empty:
        ok, why = keywords.matches(result.title)
        if not ok:
            return False, why
    return True, ""
