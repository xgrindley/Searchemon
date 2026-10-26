"""Request signing for the Walmart.io affiliate API.

Walmart.io asks every call to carry four headers: your Consumer ID, a timestamp, the key version, and a
signature. The signature is your RSA private key signing "<consumer id>\\n<timestamp>\\n<key version>\\n"
with SHA-256 (PKCS#1 v1.5), base64 encoded. This is done here with plain Python so nothing extra needs
installing. The private key file stays on this PC and is only read to sign; it is never sent anywhere or logged.
"""
from __future__ import annotations

import base64
import hashlib
import re
import time

_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class KeyError_(ValueError):
    """The key file could not be used (message is safe to show)."""


def _read(der: bytes, i: int):
    tag = der[i]
    ln = der[i + 1]
    i += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(der[i:i + n], "big")
        i += n
    return tag, der[i:i + ln], i + ln


def _seq(der: bytes) -> list[tuple[int, bytes]]:
    items, i = [], 0
    while i < len(der):
        tag, body, i = _read(der, i)
        items.append((tag, body))
    return items


def parse_private_key(pem: str) -> tuple[int, int]:
    """(modulus, private exponent) from an unencrypted RSA key in PKCS#1 or PKCS#8 PEM form."""
    m = re.search(r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----(.*?)-----END \1-----", pem, re.S)
    if not m:
        raise KeyError_("That file is not a PEM private key (it should start with -----BEGIN RSA PRIVATE KEY-----).")
    kind = m.group(1)
    if "ENCRYPTED" in kind:
        raise KeyError_("The private key is password protected. Make an unprotected key for Walmart.io.")
    try:
        der = base64.b64decode("".join(m.group(2).split()))
        tag, body, _ = _read(der, 0)
        fields = _seq(body)
        if kind == "PRIVATE KEY":                      # PKCS#8 wraps the PKCS#1 key in an octet string
            inner = next(b for t, b in fields if t == 0x04)
            _, body, _ = _read(inner, 0)
            fields = _seq(body)
        nums = [int.from_bytes(b, "big") for t, b in fields if t == 0x02]
        n, d = nums[1], nums[3]
    except (StopIteration, IndexError, ValueError) as exc:
        raise KeyError_("The private key file could not be read (is it an RSA key?).") from exc
    if n.bit_length() < 1024:
        raise KeyError_("The private key looks too short to be a Walmart.io RSA key.")
    return n, d


def sign(message: bytes, key: tuple[int, int]) -> bytes:
    n, d = key
    size = (n.bit_length() + 7) // 8
    digest_info = _SHA256_PREFIX + hashlib.sha256(message).digest()
    padded = b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) + b"\x00" + digest_info
    return pow(int.from_bytes(padded, "big"), d, n).to_bytes(size, "big")


def headers(consumer_id: str, key_version: str, key: tuple[int, int], now_ms: int | None = None) -> dict[str, str]:
    ts = str(now_ms if now_ms is not None else int(time.time() * 1000))
    sig = sign(f"{consumer_id}\n{ts}\n{key_version}\n".encode(), key)
    return {"WM_SEC.AUTH_SIGNATURE": base64.b64encode(sig).decode(), "WM_CONSUMER.INTIMESTAMP": ts,
            "WM_CONSUMER.ID": consumer_id, "WM_SEC.KEY_VERSION": key_version}
