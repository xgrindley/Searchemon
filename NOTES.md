# Project notes (rolling memory)

Read this first when picking the project back up. Newest entries at the top of each section.

## State (v1.0 stable; working on test build v1.2)
- Repo: github.com/xgrindley/Searchemon (public). main = the latest stable release only (v1.0, declared 2026-10-25), test = current work (next test build is v1.2). See RELEASING.md.
- Version scheme: stable v1.0, v2.0...; tests v1.1, v1.2... Before v1.0 the tests were v0.1 to v0.6.
- Windows app, Python 3.13 venv, tkinter window + local control panel at 127.0.0.1:8765.
- Retailers: Target, Best Buy, Walmart, Kroger family, Pokemon Center, GameStop, Costco, Sam's,
  B&N, BAM, Amazon, Dick's, Safeway, Raley's, Walgreens, CVS.
- Alerts go to Discord: default, online, in_store, per-store keys, and per-area webhooks.
- Project folder on the PC: Documents\poke-restock. Back up with `.\versions.ps1 save`.

## Decisions
- GitHub pushes only after the user tests and approves a build (2026-10-25). Until then work stays local and is synced to the PC folder only. Stable (main) is a separate, later word from the user.
- UI direction chosen: B, Glass Aurora (2026-10-25). Control panel (panel_page.py) carries the rich visuals; the tkinter window stays lightweight and only gets what is needed. No external fonts (privacy).
- No stealth, fingerprint spoofing, CAPTCHA solving or proxy rotation (see RESOURCES.md).
- Per-store MSRP allowance (`msrp_tolerance_pct` per retailer) instead of changing the MSRP.
- Blocks are per browser session, not per IP, so rotate profiles and rest the blocked one.
- Browser profile 1 keeps the old `data\browser-profile` folder; others live in `data\browser-profiles\<name>`.

## Known issues / next
- CVS refuses the automated browsers (Akamai "Access Denied"). v0.5 routes CVS and Dick's through the
  user's own Chrome (start-my-chrome.ps1). Needs a live check on the PC. Foreground-window fix is untested on Windows.
- Target `plp_search_v2` returned zero products; now retried with simpler settings. Needs a live
  check on the PC: look for "Target search worked with simpler settings" in the log.
- Walmart shelf stock and CVS/Walgreens per-store stock are not available without a signed-in store page.
- Changing `browser.profiles` needs an app restart.
- Pick list: waiting on the user's chosen products to add to the watchlist.

## Log
- 2026-10-25: v0.1 (was 3.4.0) session rotation, tracker, A/B test, webhooks routing, versions script.
