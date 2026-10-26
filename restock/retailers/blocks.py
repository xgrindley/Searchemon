"""Recognizes bot-check and block pages, and names the protection vendor when it can.

Knowing *which* system answered matters: a rate limit wants a long pause, a
JavaScript check often clears in a real browser on its own, and a CAPTCHA
needs a person.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A virtual waiting room (Pokemon Center uses one) is not a block: it means a
# drop is starting, and the page should simply be watched.
_QUEUE = ("you are now in line", "you're now in line", "you are in line", "waiting room", "estimated wait time",
          "queue-it", "queue.pokemoncenter", "virtual queue", "you are in the queue", "in line to access",
          "high demand, you have been placed")

# Strong markers only show up on challenge/block pages.
_STRONG = (
    ("PerimeterX", ("px-captcha", "perimeterx", "press &amp; hold", "press & hold", "_pxhd")),
    ("Imperva", ("_incapsula_resource", "incapsula incident", "blocked by our security service",
                 "powered by imperva", "imperva.com/")),
    # Cloudflare also adds a harmless "/cdn-cgi/challenge-platform/.../jsd/main.js" script to
    # ordinary pages it protects (GameStop's among them), so only the markers that appear on a
    # real challenge page count here.
    ("Cloudflare", ("cf_chl_opt", "orchestrate/chl_page", "cf-browser-verification", "challenge-error-text",
                    "checking your browser before accessing", "<title>just a moment...")),
    ("DataDome", ("captcha-delivery.com", "geo.captcha-delivery")),
    ("Amazon", ("/errors/validatecaptcha", "api-services-support@amazon.com", "enter the characters you see below")),
    # Akamai's "Challenge Validation" page (a short proof-of-work a real browser passes by itself; Walgreens uses it).
    ("Akamai", ("errors.edgesuite.net", "sec-if-cpt-container", "akamai bot manager", "sec-cpt-if", "cp_clge_done",
                "<title>challenge validation")),
    ("Generic", ("robot or human", "are you a human", "verify you are human", "verify you are a human",
                 "unusual traffic from your", "please enable js and disable any ad blocker")),
)
# Weak markers also appear on normal pages, so they only count on small pages.
_WEAK = (
    ("Akamai", ("access denied", "reference&#32;&#35;", "reference #")),
    ("Generic", ("request unsuccessful", "blocked", "forbidden")),
)
_PRODUCT_HINTS = ('"@type":"product"', '"@type": "product"', "__next_data__", "add to cart", "itemprop=\"price\"")


@dataclass
class BlockInfo:
    vendor: str
    kind: str            # "rate_limit", "challenge", "denied", "queue"
    needs_human: bool    # a CAPTCHA or press-and-hold that only a person should solve
    retry_after: float = 0   # seconds the site itself asked us to wait, when it says so
    hint: str = ""           # a plain-words next step shown with the message

    @property
    def hard(self) -> bool:
        """A flat refusal from Imperva (its "Error 15" page) is a ban on this
        browser and connection, not a check anyone can pass. Retrying soon only
        keeps it in place, so these get a long pause."""
        return self.kind == "denied" and self.vendor == "Imperva"

    def message(self, display: str) -> str:
        what = {"rate_limit": "is rate limiting", "challenge": "asked for a bot check",
                "denied": "refused the request", "queue": "has its waiting-room queue up"}[self.kind]
        vendor = "" if self.vendor == "Generic" else f" ({self.vendor})"
        msg = f"{display} {what}{vendor}"
        if self.retry_after >= 1800:
            msg += f". It asked for a wait of about {self.retry_after / 3600:.0f} hours"
        if self.hard:
            msg += ". This kind of block usually lifts within a few hours to a day"
        if self.hint:
            msg += f". {self.hint}"
        return msg


def wants_person(info: BlockInfo | None) -> bool:
    """True when opening the browser window for the user could help. A flat refusal such as
    Akamai's "Access Denied" page has nothing to click or solve, so asking someone to verify
    there only leaves the store stuck waiting."""
    return bool(info) and info.kind == "challenge"


_WAIT_RX = re.compile(r"try again (?:in|after)\s+(\d+)\s*(hour|minute|min)", re.I)


def _asked_wait(low: str) -> float:
    """A page that says 'try again after 12 hours' (Dick's does) is a timed block on this
    browser session. Returns the wait in seconds, or 0."""
    if len(low) > 20000:
        return 0
    m = _WAIT_RX.search(low)
    if not m:
        return 0
    n = int(m.group(1))
    return n * (3600 if m.group(2).lower().startswith("hour") else 60)


def classify(status: int, text: str, headers: dict | None = None) -> BlockInfo | None:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    low = (text or "")[:60000].lower()

    wait = _asked_wait(low)
    if wait:
        return BlockInfo("Generic", "rate_limit", False, retry_after=wait)

    if status in (200, 202, 503) and any(q in low for q in _QUEUE) and not any(h in low for h in _PRODUCT_HINTS[:2]):
        return BlockInfo("Queue", "queue", False)

    vendor = None
    for name, marks in _STRONG:
        if any(m in low for m in marks):
            vendor = name
            break
    on_page = vendor is not None
    if vendor is None and len(low) < 20000 and not any(h in low for h in _PRODUCT_HINTS):
        for name, marks in _WEAK:
            if any(m in low for m in marks) and status >= 400:
                vendor = name
                break
    if vendor is None and status >= 400:
        # The Server header alone only says who hosts the site. On a normal 200 page it proves nothing.
        server = headers.get("server", "").lower()
        if "akamai" in server or "akamaighost" in server:
            vendor = "Akamai"
        elif "cloudflare" in server:
            vendor = "Cloudflare"

    if status == 429:
        return BlockInfo(vendor or "Generic", "rate_limit", False)
    if vendor and status in (200, 202, 403, 405, 503):
        human = any(m in low for m in ("captcha", "press & hold", "press &amp; hold", "robot or human",
                                        "verify you are"))
        if vendor == "Imperva" and not human and ("error 15" in low or "blocked by our security service" in low):
            return BlockInfo(vendor, "denied", False)
        return BlockInfo(vendor, "challenge" if (human or status != 403 or (vendor == "Cloudflare" and on_page)) else "denied", human)
    if status in (401, 403):
        return BlockInfo(vendor or "Generic", "denied", False)
    return None
