# Project notes (rolling memory)

Read this first when picking the project back up. Newest entries at the top of each section.

## State (v0.1 test build)
- Repo: github.com/xgrindley/Searchemon (public). main = stable (empty until the user declares one), test = current work. See RELEASING.md.
- Version scheme: stable v1.0, v2.0...; tests v1.1, v1.2... (v0.x before the first stable).
- Windows app, Python 3.13 venv, tkinter window + local control panel at 127.0.0.1:8765.
- Retailers: Target, Best Buy, Walmart, Kroger family, Pokemon Center, GameStop, Costco, Sam's,
  B&N, BAM, Amazon, Dick's, Safeway, Raley's, Walgreens, CVS.
- Alerts go to Discord: default, online, in_store, per-store keys, and per-area webhooks.
- Project folder on the PC: Documents\poke-restock. Back up with `.\versions.ps1 save`.

## Decisions
- No stealth, fingerprint spoofing, CAPTCHA solving or proxy rotation (see RESOURCES.md).
- Per-store MSRP allowance (`msrp_tolerance_pct` per retailer) instead of changing the MSRP.
- Blocks are per browser session, not per IP, so rotate profiles and rest the blocked one.
- Browser profile 1 keeps the old `data\browser-profile` folder; others live in `data\browser-profiles\<name>`.

## Known issues / next
- Target `plp_search_v2` returned zero products; now retried with simpler settings. Needs a live
  check on the PC: look for "Target search worked with simpler settings" in the log.
- Walmart shelf stock and CVS/Walgreens per-store stock are not available without a signed-in store page.
- Changing `browser.profiles` needs an app restart.
- Pick list: waiting on the user's chosen products to add to the watchlist.

## Log
- 2026-10-25: v0.1 (was 3.4.0) session rotation, tracker, A/B test, webhooks routing, versions script.
