"""Small helpers shared across the app."""
from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query keys that only exist to track who clicked what. Removed from every link
# before it is shown or sent to Discord.
_TRACKING_KEYS = {
    "si", "is", "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "igshid",
    "mc_cid", "mc_eid", "ref", "ref_", "ref_src", "afid", "affid", "adid", "clkid",
    "irgwc", "irclickid", "clickid", "sharedid", "ranmid", "raneaid", "ransiteid",
    "wmlspartner", "sourceid", "veh", "cmp", "cmpid", "intcmp", "lnm", "cpng",
    "loc", "acid", "s_kwcid", "ef_id", "twclid", "ttclid", "yclid", "_ga", "_gl",
}
_TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_")


def clean_url(url: str | None) -> str:
    """Strip tracking parameters and fragments from a URL."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_KEYS and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def normalize_text(text: str | None) -> str:
    """Lowercase, strip accents (Pokémon -> pokemon) and collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9$.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_upc(upc: Any) -> str:
    """Digits only, leading zeros removed, so UPC-A / EAN-13 / GTIN-14 compare equal."""
    digits = re.sub(r"\D", "", str(upc or ""))
    return digits.lstrip("0")


def upc_variants(upc: Any) -> list[str]:
    """Common padded forms of a UPC to try against retailer lookups."""
    core = normalize_upc(upc)
    if not core:
        return []
    out = []
    for width in (12, 13, 14):
        if len(core) <= width:
            out.append(core.zfill(width))
    return list(dict.fromkeys(out))


def parse_price(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)", str(value))
    return float(m.group(1).replace(",", "")) if m else None


def dig(data: Any, *path: Any, default: Any = None) -> Any:
    """Safely walk nested dicts/lists: dig(d, 'a', 0, 'b')."""
    cur = data
    for key in path:
        try:
            if isinstance(cur, dict):
                cur = cur[key]
            elif isinstance(cur, list) and isinstance(key, int):
                cur = cur[key]
            else:
                return default
        except (KeyError, IndexError, TypeError):
            return default
        if cur is None:
            return default
    return cur


def atomic_write_json(path: str, data: Any) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def read_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default
