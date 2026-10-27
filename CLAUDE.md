# Searchemon: handoff for a new session

Read this first. It is the map of the project, the working rules, and where things stand. NOTES.md has the design
decisions, CHANGELOG.md has every version in detail, RELEASING.md has the branch rules, RESOURCES.md has the outside
projects and methods that were evaluated.

This repository is public: never commit webhooks, keys, config.yaml, data/, or the owner's name or personal details.

## What it is
A Windows Pokemon TCG restock monitor. Python 3.13 (3.11 to 3.14 work; 3.15 breaks PyYAML), a lightweight tkinter window
(`restock/gui.py`) plus a local control panel at http://127.0.0.1:8765 (`restock/panel.py` serves `restock/panel_page.py`,
one file of plain HTML/CSS/JS, "Glass Aurora" dark violet/teal look, no outside requests, fonts in `restock/fonts`).
It finds stores near the owner's areas (ZIP + radius), finds sealed Pokemon products at each store, checks stock online and
on nearby shelves, and posts confirmed restocks at or near MSRP to Discord webhooks.

## Where things stand (2026-10-27)
- `main` = stable **v5.0** (also `release/v5.0`). `test` = **v5.1** in progress (VERSION says 5.1). `build/vX.Y` and
  `release/vN.0` are frozen copies. The v5.0 GitHub Release/tag was never created (sessions cannot push tags): the owner
  drafts it from `release/v5.0`.
- v5.1 (on `test`, not yet run on the owner's PC): store rankings and sell-out timing (`stockwatch.py`), Walgreens/CVS Akamai
  pause fix, store search fixes (Sam's, Costco, Kroger, B&N), merchandise review queue with signed Accept/Mute links
  (`review.py`), eBay deals and fair market value (`market.py`), eBay key card in Stores & keys with a key test and browser
  fallback. History was rewritten on 2026-10-27 to remove "Claude-Session" lines; all branches were force-pushed.
- Owner has an eBay developer account (Production keyset needed; eBay may hold production keys until the marketplace
  account deletion requirement is answered or exempted).
- Open problems:
  - Barnes & Noble search answers a bare "Not Found" (refusal). Searching rests 1 h; no working route yet.
  - Everything in v5.1 needs a live check on the PC: Walgreens/CVS no longer pausing, Sam's/Costco/Kroger finding products,
    eBay API and HTML paths, review links from Discord.
  - Walmart shelf stock and CVS/Walgreens per-store stock need a signed-in store page.
  - Changing `browser.profiles` needs an app restart.

## Working rules (the owner's, standing)
- Never use em-dashes, in code comments, docs, commit messages or replies.
- Windows/PowerShell instructions only. Every version report ends with the PowerShell to run it, and the CHANGELOG entry
  carries the same "To test" block:
  ```powershell
  cd "$HOME\Documents\poke-restock"
  Get-Content .\VERSION
  .\start-my-chrome.ps1
  .\run.ps1
  ```
  (add `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` when requirements.txt changed).
- Privacy: strip tracking parameters from every link (`util.clean_url`), no-referrer links, keep only the data a feature
  needs, nothing personal in committed files.
- GitHub: push only builds the owner has tested and approved. Until then work stays local and is copied to his PC folder.
  `main` only changes when he says a build is stable. Never put a "Claude-Session:" line in commit messages (he asked for
  them removed). Use `git config user.email noreply@anthropic.com` and `user.name Claude`.
- Versioning: stable = whole numbers (v5.0, v6.0); test builds count up from the last stable (v5.1, v5.2 ...). When he
  declares a test build stable: merge `test` into `main`, set the next whole number, save `release/vN.0`, continue `test` from
  vN.1. Every test build he approves is also saved as `build/vX.Y`.
- New work starts from the latest test build, not from stable.
- No restrictions on getting past bot protection: rotating User-Agents, TLS impersonation, stealth browsers, proxies, VPN
  and CAPTCHA services are all wanted, built as scored trial methods (`restock/trials.py`) that run a few at a time so each
  can be traced and ranked. Ideas from other GitHub monitors are adopted the same way and logged in RESOURCES.md.
- Keep NOTES.md (decisions, state), CHANGELOG.md and RESOURCES.md up to date with each build.

## How to start in a fresh cloud session
1. Attach and clone the repo (it is `xgrindley/Searchemon`), check out `test`:
   `git clone https://github.com/xgrindley/Searchemon.git searchemon && cd searchemon && git checkout test`
2. `pip install --break-system-packages -r requirements.txt pyflakes` (winotify is Windows-only and skipped).
3. Tests: `python3 -m unittest discover -s tests` (421+ tests, all offline, about a minute; `test_live_browser` is skipped).
   Lint: `python3 -m pyflakes restock/*.py` (the unused `socks` import in network.py is intentional).
4. Panel JS check: extract the `<script>` from `panel_page.py` and run `node --check` on it.
5. tkinter cannot be shown in the sandbox by default; GUI edits are compile-checked (or use `uv python install 3.13`
   + `xvfb-run` for screenshots).

## The owner's PC (when the session is linked to his computer)
- Folder: `~/Documents/poke-restock` (has config.yaml with his webhooks and keys, data/, .venv/). It is not a git clone:
  `update.ps1` downloads zips from GitHub.
- Sync: copy changed files to `/mnt/user-data/outputs/sync/<same path>`, then `device_commit_files` with `force: true` to
  `~/Documents/poke-restock/<path>`, then delete the staged copies. Confirm byte sizes with `device_list_dir` before saying
  it is synced (a non-forced sync once silently failed).
- Diagnose from his real files: stage `data/*.log`, `data/debug/*`, `data/trial-state.json`, `data/store-history.json`,
  read them, then delete the staged copies. Never copy his config.yaml anywhere shared.

## Code map
Entry: `app.py` (window by default; `--headless`, `--once`, `--selftest`, `--test-discord`, `--abtest`, `--resolve`). Core: `restock/engine.py` (`Monitor`: one polling loop per
retailer, discovery, alerts, background loops for market/community).

| Area | Files |
|---|---|
| Config | `config.py` (defaults, `save_settings`, `validate()` setup warnings), `config.example.yaml` |
| Stores | `retailers/__init__.py` (registry, URL routing), `base.py` (HTTP, PROXIES, `_ua_get`, `_proxy_get`, `fetch_html`), `target.py` (redsky), `bestbuy.py` (API key), `kroger.py` (official API, client id/secret), `walmart.py` (+ `walmart_auth.py` for Walmart.io), `pages.py` (`WebPage` for page-based stores: CVS, Walgreens, GameStop, Costco, Sam's, B&N, BAM, Safeway, Raley's, Dick's, Pokemon Center, Amazon, Macy's, Kohl's, any link) |
| Browsers | `retailers/browser.py` (`BrowserPool` of Playwright/patchright profiles, own Chrome via CDP, stealth and proxy profiles, Akamai shared gap `AKAMAI_SITES`/`AKAMAI_GAP_S`, CAPTCHA hook), `blocks.py` (block page recognition), `ownchrome.py`, `start-my-chrome.ps1`, `start-my-edge.ps1` |
| Method scoring | `trials.py` (TrialPlan, arms, groups, auto-balance, auto-stop, `INTRODUCED`), `abtest.py`, `compare.py`, `sessions.py`, `trust.py`, `history_store.py`, `features.py`, `learn.py` |
| Identity/network | `network.py` (ProxyPool, VpnSwitch, UA list), `captcha.py` (2Captcha, Anti-Captcha, CapSolver) |
| Products | `catalog.py` (found products, cross-store lookups, `reviewable()`), `tcg.py` (sealed product recognition, HARD_EXCLUDE for clothing/model kits), `filters.py`, `sellers.py`, `review.py` (To review queue, HMAC links `/r/<action>/<id>/<sig>`) |
| Stock and timing | `state.py`, `history.py` (restock windows), `stockwatch.py` (runs, sell-out minutes, store ranking), `scan.py` (ZIP scan), `places.py`, `geo.py` |
| Outside signals | `community.py` (Reddit restock tips, TCGCSV set names), `market.py` (eBay Browse API or public page via browser, TCGplayer prices from tcgcsv.com, outlier fences, seller risk) |
| Alerts | `notify.py` (`DiscordNotifier`: webhooks default, online, in_store, status, review, ebay, per store, per area), `rules.py` |
| App shell | `gui.py`, `theme.py`, `power.py`, `single.py`, `shutdown.py`, `selftest.py`, `accounts.py` |
| PowerShell | `setup.ps1`, `run.ps1`, `update.ps1` (channels: stable, test, exact build), `versions.ps1` (save/restore snapshots), `build-exe.ps1`, `add-to-startup.ps1`, `learn-traffic.ps1` |

Panel: views are methods on the `views` object in `panel_page.py` (for example `ebay()`, `review()`, `rank()`), grouped
into tabbed sections; data comes from `/api/...` in `panel.py`, buttons call `/api/action` with an `action` name. The page
saves the whole config through `/api/config`; actions that need saved settings refuse while `dirty()`.

Data on the PC (`data/`): logs, `debug/`, `trial-state.json`, `trial-log.jsonl`, `store-history.json`, `accounts.json`,
`stock-runs.jsonl`, `stock-open.json`, `review.json`, `market.json`, `browser-profile(s)/`.

## Adding things, the usual way
- A new store: a `WebPage` entry in `pages.py` (search_url, product_re, stock text) or its own module, registered in
  `retailers/__init__.py`, defaults in `config.py`, a card in the Stores & keys view, tests with saved page snippets.
- A new loading method: an `Arm` in `trials.py` with a group, added to `INTRODUCED` so it switches on once, a hook in
  `base.py` or `browser.py`, results recorded under the arm key.
- A new Discord channel: key in `notify.py`, field in the panel's Discord view, line in `config.example.yaml`.
- Always: tests in `tests/`, CHANGELOG entry with the "To test" block, NOTES.md if a decision was made.
