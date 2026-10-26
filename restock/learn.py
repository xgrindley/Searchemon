"""Learn a store's own data requests from your own browsing (inspired by Klura's "learn from traffic").

You browse a product page in your own Chrome or Edge (the one started by start-my-chrome.ps1) and use the
store's own "check nearby stores" box. This tool listens, through the DevTools port on this PC, to the
data requests that page makes (JSON answers only), keeps the ones that look like stock or store answers,
and turns the best into URL templates with {zip}, {pid} and {radius} slots. Saved templates are tried by
the monitor first, so it uses the same request the store's own page uses instead of a guess.

Privacy: no cookies and no request headers are recorded. Only the URL, method, status, a small slice of the
request body and the JSON answer are kept, and values of keys that look like tokens or passwords are
replaced with "REDACTED". Everything stays in data\\learned on this PC. Nothing is sent anywhere.
It records only what your own page already did while you browsed normally; it does not change or send requests.

    python -m restock.learn --site gamestop --zip 12345 --pid 123456 --seconds 180 --save
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .util import atomic_write_json, read_json

TRACKER_HOSTS = ("google-analytics", "googletagmanager", "doubleclick", "facebook", "fbcdn", "hotjar", "segment.",
                 "newrelic", "nr-data", "sentry", "datadog", "clarity.ms", "tiktok", "pinterest", "criteo",
                 "adsrvr", "bing.com", "snapchat", "optimizely", "quantummetric", "medallia", "tealium",
                 "akamai", "px-cdn", "perimeterx", "datadome", "demdex", "branch.io", "braze", "onetrust")
SECRET_KEY = re.compile(r"(token|auth|passw|secret|session|csrf|cookie|bearer|signature|sid|jwt|apikey|api_key|key)", re.I)
STOCK_WORDS = ("instock", "in_stock", "outofstock", "out_of_stock", "availability", "available", "quantity", "inventory",
               "pickup", "storeid", "store_id", "stocklevel", "ats", "onhand", "stores", "storenumber", "orderable")
MAX_BODY = 60_000
MAX_KEEP = 150


def redact_url(url: str) -> str:
    """Remove the values of token-like query parameters, keep everything else."""
    p = urlsplit(url)
    q = [(k, "REDACTED" if SECRET_KEY.search(k) else v) for k, v in parse_qsl(p.query, keep_blank_values=True)]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q, safe="{}"), ""))


def redact_json(node):
    if isinstance(node, dict):
        return {k: ("REDACTED" if SECRET_KEY.search(str(k)) and not isinstance(v, (dict, list)) else redact_json(v))
                for k, v in node.items()}
    if isinstance(node, list):
        return [redact_json(x) for x in node[:200]]
    return node


def redact_text(text: str) -> str:
    """Request bodies: redact JSON or form values whose key looks secret."""
    try:
        return json.dumps(redact_json(json.loads(text)))[:2000]
    except ValueError:
        pass
    pairs = parse_qsl(text, keep_blank_values=True)
    if pairs:
        return urlencode([(k, "REDACTED" if SECRET_KEY.search(k) else v) for k, v in pairs], safe="{}")[:2000]
    return ""


def interesting(url: str, ctype: str, resource_type: str) -> bool:
    if resource_type not in ("xhr", "fetch"):
        return False
    if "json" not in (ctype or "").lower():
        return False
    host = urlsplit(url).netloc.lower()
    return not any(t in host for t in TRACKER_HOSTS)


def stock_score(body: str) -> int:
    low = body.lower()
    return sum(min(low.count(w), 5) for w in STOCK_WORDS)


def templatize(url: str, hints: dict[str, str]) -> str:
    """Swap the values you told us (zip, product id, radius) for {zip} {pid} {radius} slots."""
    p = urlsplit(url)
    path = p.path
    for slot, value in hints.items():
        if value and len(value) >= 3:
            path = path.replace(value, "{" + slot + "}")
    q = []
    for k, v in parse_qsl(p.query, keep_blank_values=True):
        for slot, value in hints.items():
            if value and v and value in v:
                v = v.replace(value, "{" + slot + "}")
        q.append((k, v))
    return urlunsplit((p.scheme, p.netloc, path, "&".join(f"{k}={v}" for k, v in q), ""))


def analyze(entries: list[dict], hints: dict[str, str] | None = None, top: int = 8) -> list[dict]:
    """Rank recorded answers: the ones that mention stock or stores and echo your ZIP or product id first."""
    hints = {k: str(v) for k, v in (hints or {}).items() if v}
    ranked = []
    for e in entries:
        if e.get("status") != 200:
            continue
        body = e.get("body") or ""
        score = stock_score(body)
        if not score:
            continue
        haystack = (e["url"] + " " + (e.get("post") or "") + " " + body).lower()
        echoed = [slot for slot, value in hints.items() if value.lower() in haystack]
        score += 6 * len(echoed)
        if e["method"] == "GET":
            score += 2                                      # GET answers can be replayed by the monitor
        ranked.append({"score": score, "method": e["method"], "url": e["url"],
                       "template": templatize(e["url"], hints) if e["method"] == "GET" else "",
                       "echoes": echoed, "bytes": len(body), "post": e.get("post") or ""})
    ranked.sort(key=lambda r: -r["score"])
    seen, out = set(), []
    for r in ranked:
        key = (r["method"], r["template"] or r["url"].split("?")[0])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out[:top]


def save_templates(data_dir: str, site: str, candidates: list[dict]) -> list[str]:
    """Keep the replayable (GET) templates that carry at least a {zip} or {pid} slot."""
    path = os.path.join(data_dir, "learned", "endpoints.json")
    data = read_json(path, {})
    good = [c["template"] for c in candidates if c["template"] and ("{zip}" in c["template"] or "{pid}" in c["template"])]
    if good:
        data[site] = list(dict.fromkeys(good + [t for t in data.get(site, []) if t not in good]))[:6]
        atomic_write_json(path, data)
    return good


def learned_templates(data_dir: str, site: str) -> list[str]:
    return [t for t in (read_json(os.path.join(data_dir, "learned", "endpoints.json"), {}).get(site) or [])
            if isinstance(t, str) and t.startswith("https://")]


def record(port: int, seconds: int, say=print) -> list[dict]:
    """Listen on a browser you started with DevTools open and collect JSON data requests."""
    from playwright.sync_api import sync_playwright
    entries: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0]

        def on_response(resp):
            if len(entries) >= MAX_KEEP:
                return
            try:
                req = resp.request
                ctype = resp.headers.get("content-type", "")
                if not interesting(resp.url, ctype, req.resource_type):
                    return
                text = resp.text()
                if len(text) > MAX_BODY:
                    text = text[:MAX_BODY]
                try:
                    body = json.dumps(redact_json(json.loads(text)))
                except ValueError:
                    return
                entries.append({"method": req.method, "url": redact_url(resp.url), "status": resp.status,
                                "post": redact_text(req.post_data or ""), "body": body[:MAX_BODY]})
            except Exception:
                return

        def watch(page):
            page.on("response", on_response)

        for pg in ctx.pages:
            watch(pg)
        ctx.on("page", watch)
        say(f"Listening for {seconds} seconds. In your own browser, open the product page and use the store's "
            "'check nearby stores' box with your ZIP. Nothing is changed or sent.")
        end = time.time() + seconds
        anchor = ctx.pages[0] if ctx.pages else ctx.new_page()
        while time.time() < end:
            anchor.wait_for_timeout(250)
        browser.close()                       # only disconnects; your browser stays open
    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Learn a store's data requests from your own browsing")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--site", default="gamestop")
    ap.add_argument("--zip", default="")
    ap.add_argument("--pid", default="")
    ap.add_argument("--radius", default="")
    ap.add_argument("--data", default="data")
    ap.add_argument("--save", action="store_true", help="keep the best replayable requests for the monitor to try first")
    a = ap.parse_args(argv)
    try:
        entries = record(a.port, a.seconds)
    except Exception as exc:
        print(f"Could not listen on port {a.port}: {str(exc).splitlines()[0][:120]}\n"
              "Start your own Chrome first (start-my-chrome.ps1) and leave it open.")
        return 1
    hints = {"zip": a.zip, "pid": a.pid, "radius": a.radius}
    cands = analyze(entries, hints)
    folder = os.path.join(a.data, "learned")
    os.makedirs(folder, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    atomic_write_json(os.path.join(folder, f"{a.site}-{stamp}.json"),
                      {"site": a.site, "recorded": len(entries), "candidates": cands, "entries": entries})
    print(f"Recorded {len(entries)} data answers; {len(cands)} look like stock or store answers.")
    for c in cands:
        print(f"  [{c['score']:>3}] {c['method']} {c['template'] or c['url']}")
    if a.save:
        kept = save_templates(a.data, a.site, cands)
        print(f"Saved {len(kept)} request(s) for the monitor to try first." if kept else
              "Nothing replayable was found to save (use --zip and --pid so the slots can be filled in).")
    print(f"Full recording: {os.path.join(folder, a.site + '-' + stamp + '.json')} (no cookies or headers inside; "
          "it can contain your ZIP and nearby store names, so look before sharing it).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
