# Project notes (rolling memory)

Read this first when picking the project back up. Newest entries at the top of each section.

## State (v3.0 stable; test builds continue from v3.1)
- Repo: github.com/xgrindley/Searchemon (public). main = the latest stable release only (v2.0, declared 2026-10-25), test = current work (next test build is v2.9). See RELEASING.md.
- Version scheme: stable v1.0, v2.0, v3.0...; tests count up from the release (v2.1, v2.2, v2.3, v2.4, v2.5...). v1.0 was v0.6 promoted, v2.0 is v1.2 promoted.
- Windows app, Python 3.13 venv, tkinter window + local control panel at 127.0.0.1:8765.
- Retailers: Target, Best Buy, Walmart, Kroger family, Pokemon Center, GameStop, Costco, Sam's,
  B&N, BAM, Amazon, Dick's, Safeway, Raley's, Walgreens, CVS.
- Alerts go to Discord: default, online, in_store, per-store keys, and per-area webhooks.
- Project folder on the PC: Documents\poke-restock. Back up with `.\versions.ps1 save`.

## Decisions
- GitHub pushes only after the user tests and approves a build (2026-10-25). Until then work stays local and is synced to the PC folder only. Stable (main) is a separate, later word from the user.
- UI direction chosen: B, Glass Aurora (2026-10-25). Control panel (panel_page.py) carries the rich visuals; the tkinter window stays lightweight and only gets what is needed. No external fonts (privacy).
- Stealth trials (direct-impersonate, browser-stealth) added in v2.6 on request, off by default. No CAPTCHA solving or proxy rotation built.
- Per-store MSRP allowance (`msrp_tolerance_pct` per retailer) instead of changing the MSRP.
- Blocks are per browser session, not per IP, so rotate profiles and rest the blocked one.
- Browser profile 1 keeps the old `data\browser-profile` folder; others live in `data\browser-profiles\<name>`.

## Trials (v2.6)
- restock/trials.py: TrialPlan picks one arm per store at a time (slices of 20 checks, control included, blocked arm
  rests 90 min). Arms: direct-h2, direct-warm, direct-impersonate, browser-solo, browser-own, browser-stealth, browser-slow. Default on: direct-h2,
  browser-solo, browser-own. Hooks: Retailer.fetch_html (base.py), BrowserPool.fetch(pick, label), Monitor._next_delay.
- Trial results are recorded in the block tracker under the arm key; the control is recorded where it always was
  (direct, or the profile name). Trace: data\trial-log.jsonl. Panel: Methods lab, "Trial methods".
- Not covered: API stores (Target, Best Buy, Kroger) go through Retailer.get, not fetch_html.
- Needs a live check on the PC: httpx[http2] install (setup.ps1), browser-own with start-my-chrome.ps1 running.

## Rolling history (v2.10)
- history_store.py: data/store-history.json, per store recent (40 chars of 0/1), hourly [ok, fail] for 7 days, last problem. Engine preloads health["recent"] from it; trust.py falls back to the 7 day totals.

## Auto-balance (v3.3)
- trials.py: saved["balance"][store][arm] = decayed [ok, fail] (x0.97 per check). Turn length = slice_checks * (min_share + (2 - min_share) * (score/best)^3); methods under 6 recent checks get 1.0.

## Method control (v2.9)
- trials.py keeps data/trial-state.json: active list, per-method attempt counters (since switched on), stopped records, last 30 events.
- Auto-stop: attempts > stop_after (25) and fails/attempts >= stop_fail_pct (50). Only trial arms; controls are never counted.
- After the first button press the saved active list overrides config.yaml (TrialPlan.attach).
- CVS: "in store purchase only" text overrides the page's InStock data (online=False, status "In store only").

## ZIP scan (v2.8, v2.10)
- v2.10: "everything" mode = all enabled SCAN_STORES + live r.search() with the discovery queries (in memory, catalog untouched), cap 150, honours product type alert flags.
- restock/scan.py ZipScan: manual only (panel tab "Find stock near a ZIP", /api/scan, actions scan_start and scan_cancel).
  Builds fresh retailer objects with a temporary Area for the ZIP and radius, asks Target, Best Buy, Kroger, GameStop, CVS.
  Results are held in memory only.

## Known issues / next
- CVS refuses the automated browsers (Akamai "Access Denied"). v0.5 routes CVS and Dick's through the
  user's own Chrome (start-my-chrome.ps1). Needs a live check on the PC. Foreground-window fix is untested on Windows.
- Target `plp_search_v2` returned zero products; now retried with simpler settings. Needs a live
  check on the PC: look for "Target search worked with simpler settings" in the log.
- Walmart shelf stock and CVS/Walgreens per-store stock are not available without a signed-in store page.
- Changing `browser.profiles` needs an app restart.
- Pick list: waiting on the user's chosen products to add to the watchlist.

## Log
- 2026-10-26: v2.6 test build: trial methods (on top of the PC v2.5) (see Trials). Local and PC folder only until approved.
- 2026-10-25: v0.1 (was 3.4.0) session rotation, tracker, A/B test, webhooks routing, versions script.

- Standing rule: every report of a new version ends with the PowerShell text to run it (cd, Get-Content .\VERSION, start-my-chrome, run.ps1), and the CHANGELOG entry carries the same "To test" block.
