"""Per-store trust report: is each store reliable, flaky or blocked, and what to do about it.

It only reads numbers the app already collects: the outcome of recent real checks (what you actually
get), the block tracker (per method), and the side-by-side test (all methods on the same page at the
same time). Nothing here changes how stores are checked.
"""
from __future__ import annotations

MIN_CHECKS = 10        # real checks needed before a rating is given
MIN_RUNS = 5           # side-by-side runs needed to name a best method
RELIABLE = 90
FLAKY = 60

# Stores that publish an official feed, and the settings that switch it on.
OFFICIAL = {
    "bestbuy": {"label": "Best Buy developer API", "keys": ("api_key",), "where": "developer.bestbuy.com, free key"},
    "kroger": {"label": "Kroger developer API", "keys": ("client_id", "client_secret"), "where": "developer.kroger.com, free app"},
}


def _pct(x: float) -> int:
    return int(round(100 * x))


def _site_match(site: str, domains: tuple[str, ...]) -> bool:
    site = site.lower().removeprefix("www.")
    return any(site == d or site.endswith("." + d) or d.endswith("." + site) for d in domains)


def store_row(name: str, display: str, health: dict, compare_rows: list[dict], tracker_rows: list[dict],
              domains: tuple[str, ...], feed: dict | None = None) -> dict:
    """Rate one store. `health` is the panel's per-store health dict (success %, checks)."""
    best_cmp = None
    for r in compare_rows:
        if r["store"] == name and r["runs"] >= MIN_RUNS:
            rate = r["ok"] / r["runs"]
            if best_cmp is None or rate > best_cmp[1]:
                best_cmp = (r["method"], rate, r["runs"])
    best_trk = None
    for r in tracker_rows:
        if r["checks"] >= 20 and _site_match(r["site"], domains):
            rate = 1 - r["blocks"] / r["checks"]
            if best_trk is None or rate > best_trk[1]:
                best_trk = (r["method"], rate, r["checks"])

    checks = int(health.get("checks") or 0)
    success = health.get("success")
    if feed and feed.get("state") == "needs_key":
        verdict, score, basis = "Needs setup", None, "official feed not switched on"
    elif checks >= MIN_CHECKS and success is not None:
        score, basis = float(success), f"{checks} recent checks"
    elif int(health.get("week_checks") or 0) >= MIN_CHECKS and health.get("week_success") is not None:
        score, basis = float(health["week_success"]), f"{health['week_checks']} checks in the last 7 days"
    elif best_trk:
        score, basis = 100 * best_trk[1], f"{best_trk[2]} checks with {best_trk[0]}"
    elif best_cmp:
        score, basis = 100 * best_cmp[1], f"{best_cmp[2]} side-by-side runs"
    else:
        score, basis = None, ""
    if score is not None:
        verdict = "Reliable" if score >= RELIABLE else ("Flaky" if score >= FLAKY else "Blocked")
    elif not (feed and feed.get("state") == "needs_key"):
        verdict = "Not enough data"

    advice = []
    if feed and feed.get("state") == "needs_key":
        advice.append(f"Switch on the {feed['label']} ({feed['where']}); official feeds do not use bot checks.")
    if verdict in ("Flaky", "Blocked"):
        if best_cmp and best_cmp[1] >= 0.9 and best_cmp[0] != "direct":
            advice.append(f"Side-by-side shows {best_cmp[0]} loading it {_pct(best_cmp[1])}% of the time; checks will favour it.")
        elif best_cmp and best_cmp[0] == "direct" and best_cmp[1] >= 0.9:
            advice.append("Plain requests work here; slow the interval if blocks continue.")
        else:
            advice.append("No method loads it reliably yet. Keep your own Chrome running and signed in, "
                          "and pass any human check it shows you.")
        if health.get("last_block"):
            advice.append(f"Last problem: {health['last_block']}.")
    if verdict == "Reliable" and feed and feed.get("state") == "on":
        advice.append(f"Uses the {feed['label']}.")
    if verdict == "Not enough data":
        advice.append("Let the monitor run for a while; ratings need about 10 checks.")
    if basis and int(health.get("week_checks") or 0) > checks:
        basis += f" | last 24 h: {health.get('day_checks') or 0} checks, {health.get('day_success')}% loaded" \
            if health.get("day_checks") else f" | last 7 days: {health['week_checks']} checks, {health['week_success']}% loaded"
    return {"store": name, "display": display, "verdict": verdict,
            "score": None if score is None else round(score),
            "basis": basis, "best_method": best_cmp[0] if best_cmp else (best_trk[0] if best_trk else ""),
            "best_rate": None if not best_cmp else _pct(best_cmp[1]),
            "official": (feed or {}).get("label", ""), "advice": " ".join(advice)}


def feed_state(name: str, rcfg: dict) -> dict | None:
    f = OFFICIAL.get(name)
    if not f:
        return None
    have = all(str(rcfg.get(k) or "").strip() for k in f["keys"])
    return {**f, "state": "on" if have else "needs_key"}


def build(retailers: list[dict], compare_rows: list[dict], tracker_rows: list[dict],
          domains_of, rcfg_of) -> list[dict]:
    order = {"Blocked": 0, "Flaky": 1, "Needs setup": 2, "Not enough data": 3, "Reliable": 4}
    rows = [store_row(r["name"], r["display"], r, compare_rows, tracker_rows, domains_of(r["name"]),
                      feed_state(r["name"], rcfg_of(r["name"]))) for r in retailers]
    rows.sort(key=lambda x: (order.get(x["verdict"], 5), x["display"]))
    return rows


def missing_feeds(rcfg_of, enabled: set[str]) -> list[dict]:
    """Official feeds that exist but are not switched on (store off, or key missing)."""
    out = []
    for name in OFFICIAL:
        st = feed_state(name, rcfg_of(name))
        if st["state"] == "needs_key" and name not in enabled:
            out.append({"store": name, "label": st["label"], "where": st["where"]})
    return out
