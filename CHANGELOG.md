# Changelog

## v3.6 (2026-10-26, test build, includes v3.5)
- **Dark and light themes for the desktop window.** The window now opens in a dark violet theme that matches the control panel
  (same ground, raised surfaces, violet accent and cyan for in stock), with a thin violet to cyan gradient line under the top bar.
  Fields, tables, tabs, scrollbars, dropdowns, checkboxes, menus, the activity log and the block tracker all use the same tonal steps,
  so nothing is a stark white box any more. **More > Appearance** switches between Dark, Light and Match Windows, and the choice is
  remembered in data\gui-theme.txt. Text contrast is checked in tests for both themes.
- **Status channel.** A second Discord webhook (`discord.webhooks.status`) gets everything that is not stock: sign-in lost, human
  checks, blocked stores and recoveries, methods stopped automatically. Each kind has a switch in Notifications, with a cooldown.
- **Areas map.** The Areas & radius page draws your areas, radius circles and nearby stores on a map that makes no outside requests.
- **Control panel fits any window.** Wide tables scroll inside their box instead of being cut off, the side menu narrows for medium
  windows and becomes a tab bar for small ones, rows and settings wrap, and the top strip no longer overflows or shows text through it.
  Methods lab and Accounts no longer rebuild every 5 seconds: they refresh only when their numbers change, and never while you are
  selecting text or typing, so the page stays still and responds faster.
- **Stores near you now shows stock, not just stores.** The page opens on the stores that have something in stock right now, nearest
  first, with a map that draws only those stores (the number on each dot is how many products it has) at the radius you choose.
  Filters: **Area** (one area or all), a **radius** slider that can go past the area's own radius, store/chain, a product or store
  search, Pickup available, online listings, and a switch to also list every store with nothing in stock. Click a dot on the map or a
  store in the list to open it and see each product with its price, count and a link (over-MSRP prices are flagged). It updates by
  itself as checks finish, without losing your place.
- **Find stock near a ZIP: pick your stores.** The store ticks are always shown on the scan page now (All and None buttons, stores that
  are off in Stores & keys are labelled), and the scan asks exactly the stores you tick, with or without "Search every product".
  **Walgreens** was added. It publishes no shelf stock, so for Walgreens the scan reports the online listing only, and says so.
- **CVS stops sitting on "Blocked".** CVS, Sam's Club, GameStop and Dick's refuse the app's automated browsers but accept a normal
  Chrome. The app now starts your own Chrome (minimized, own profile in data\my-chrome, DevTools on this PC only) by itself the first
  time one of those stores needs it, at most once every 10 minutes (`browser.auto_start_own_chrome: false` turns it off). A scan that
  still has to wait for it says "Needs your own Chrome" instead of "Blocked".
- **Sam's Club tries your own Chrome first**, like CVS, Dick's and GameStop (built in). In the app's automated browser the Sam's human check
  can sit on loading dots forever; your own Chrome (start-my-chrome.ps1) is a normal browser, so the Press and Hold button shows up.
  The app does not solve human checks. It shows you the page and carries on after you finish it.
- **Control panel first.** In the desktop window, "Open control panel" is now the highlighted button at the front of the top bar, with a
  "Click here for the better, more advanced GUI" note beside it that opens the panel too.
- **Clear message when the app is gone.** "Failed to fetch" is replaced by "Lost contact with the app" plus a red bar, and the page reconnects by itself once the app runs again.
- **Faster, safe close.** Closing the app hides the window at once, tells every browser to close together instead of one after
  another, and the store loops share one short wait (before: up to 5 seconds each). Saves still run, and a browser mid-page finishes
  and closes cleanly.
- **Runs quietly while you use the PC.** Browsers already sit off screen and never take focus (only sign-in does, when you ask).
  The app now also runs at below-normal priority so games and calls get the CPU first (`power: low_priority`). Optional
  `power: keep_awake: true` stops Windows sleeping while it runs.
- Tests: tests\test_theme.py (contrast, saved choice, and painting a real window when a display is available).
- Tests: tests\test_shutdown_speed.py (close speed, power settings), test_status.py.

To test v3.6 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 3.6. Close the running app first. The window should open dark. Try **More > Appearance > Light** and back.

## v3.5 (2026-10-26, test build, includes v3.4)
- **No links needed for page stores.** CVS, GameStop, Costco, Sam's Club, Walgreens, Barnes & Noble, Books-A-Million and
  Safeway now search their own site for Pokemon products (the same automatic product list Target, Best Buy and the others
  already had), and they also look up the products found at other stores by UPC and by name, a few per refresh, so the product
  list is shared across stores. Everything found goes through your **Product filters** (alerts on/off per type, MSRP caps),
  the third-party seller rule and the sold-out checks like any other product. Switch off with `discovery: cross_store: false`.
  Pokemon Center, Amazon and Raley's still need links (their search pages are not readable yet). Search pages that name no product
  in the link are named by opening the page (up to 6 per search). If a store's search page shows nothing, a copy is saved in
  data\debug so the reader can be adjusted. These readers were tested against mock pages only; they have not been run against the live sites yet.
- **Restock boost:** when a product restocks at one store, the same product at the other stores is checked every cycle for 2 hours.
- **Browser profiles (Accounts tab and the desktop window, Stores & speed tab):** if Akamai or PerimeterX blocks a browser because its
  cookies earned a bad reputation, **Clear bot-check cookies** removes only those cookies (Akamai, PerimeterX, Cloudflare, Imperva,
  DataDome) and keeps your sign-ins, and **Reset profile** deletes that browser's whole saved profile so it starts fresh. Both lift
  the 90-minute rest for that browser right away. Your own Chrome or Edge is only cleared of cookies and stays open. The panel shows
  each browser, its size on disk and which stores are resting it.
- **Fonts and styling:** the control panel now uses Sora, Inter and JetBrains Mono, served by the app itself (no outside requests),
  with refined buttons, panels, tables and spacing. The desktop window picks Segoe UI Variable, taller rows, clearer tabs and Cascadia Mono.
- **Exe build:** build-exe.ps1 now stamps the version, bundles VERSION, config.example.yaml and the fonts, collects curl_cffi, patchright,
  zipcodes and certifi data, runs `PokeRestock.exe --selftest` on the fresh build, and only then zips it with a SHA256 checksum.
  `--selftest` also works from source. A crash in the windowed exe is written to data\crash.log.
- Tests: tests\test_storesearch.py, test_pagestores_e2e.py (mock stores: products found with no links, type filters, MSRP caps),
  test_profiles.py. 246 pass.

To test v3.5 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
.\.venv\Scripts\python.exe app.py --selftest
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 3.5. Close the running app first. Open **Found products** after a few minutes: CVS, GameStop and the others
should list products without any links added. Open **Accounts** and look at **Browser profiles**.

## v3.4 (2026-10-26, test build, includes v3.3)
- **Accounts tab:** shows, for each store you can sign in to, whether a sign-in is saved and whether it is working fine.
  Press **Sign in** (opens the store in the checking browser), log in, and the app notices by itself within a minute and marks
  it **Signed in and saved**, with which browser holds it, since when, and about how many days the sign-in cookie lasts.
  Under that it says **Working** (the store loaded 80% or more of recent checks, with the last good one in the past hour)
  or **Not working well**, so a signed-in account that is still being blocked shows up. If a saved sign-in disappears (expired
  or signed out) it says so and when.
- **I signed in** button for stores whose login cookies the app cannot recognise by name: it records your word, keeps showing
  it as signed in while the cookies last, and drops it when they are wiped. A count of signed-in stores shows next to the tab.
- It saves in data\accounts.json, so it is still there after a restart. Only counts, dates and the expiry are saved. Cookie
  values are never read or stored, and the check only looks at browsers that are already running.
- Tests: tests\test_accounts.py.

To test v3.4 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 3.4. Close the running app first. Open the **Accounts** tab, press Sign in next to a store, log in, wait about a minute. Close the app, start it again, and it should still show as signed in.

## v3.3 (2026-10-26, test build, includes v3.2)
- **Auto-balance:** the app now shifts checks toward what is working, store by store. Every method (the normal ones and the
  trial ones) keeps a running score at each store, weighted toward its most recent ~30 checks. A method that has been loading
  pages gets longer turns, one that has been failing gets shorter turns, down to a quarter of a normal turn so it can still
  recover and be judged again. Nothing is judged until a method has about 6 recent checks at that store, and until then everyone
  gets a normal turn. A blocked trial method still rests for 90 minutes and falls back to the normal method, and a method that
  fails more than 25 attempts at 50% is still switched off (v2.9), so a poor method cannot drag down the tool's overall results.
- **Method control** shows "How checks are shared out right now": for each store, each method's share of the checks and how
  often it loaded recently. The balance is saved in data\trial-state.json and survives a restart.
- Settings (Methods lab, About the trial methods): **Auto-balance checks** on/off and, in config.yaml, `trials: min_share`
  (default 0.25). Off gives every method equal turns, as before.
- Tests: tests\test_methodcontrol.py (turn lengths, per-store, recovery, off switch, rotation, restart).

To test v3.3 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 3.3. Close the running app first. Open **Methods lab**, **Method control**: "How checks are shared out right now" fills in after a few minutes of checking.

## v3.2 (2026-10-26, test build, includes v3.1)
- **The whole picture** (Methods lab, under the trust table): every store, every day, kept for 180 days in
  data\store-history.json (compact, under 200 KB). Per store: checks, % loaded, average check time, products found, alerts
  sent, and a 30 day bar strip (taller = more checks, amber and red = failures). A second table does the same for each
  checking method over 14 days. The 40 recent checks and hourly numbers from v2.10 are still there. Nothing is lost when you
  close the app, and files from v2.10 load fine.
- **Clearer "no products" messages:** a store with no automatic search yet (Costco, Sam's Club, Barnes & Noble, Books-A-Million,
  Amazon, Raley's, Walgreens, GameStop, CVS) now says so and points to My products, instead of "nothing to check". A store
  that is searched but came back empty says it searched, and the Whole picture table shows "none found yet" or the catalog size.
- **A store that found nothing is searched again after every restart** (it used to wait up to 30 minutes), so a fix such as
  the Target block detection shows up right away.
- Tests: more in tests\test_history.py.

To test v3.2 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 3.2. Close the running app first. Open **Methods lab**: the new "The whole picture" tables are under "Can I trust each store?".

## v3.1 (2026-10-26, test build, follows stable v3.0)
Due diligence pass.
- **Quiet interruptions:** when you save settings or close the app while a browser check is running, the check is dropped
  quietly. Before, it logged a long error (browser has been closed) and counted as a failed check against that store, which
  also dragged down its trust rating. Your log showed 57 of these (Walmart, Pokemon Center, CVS).
- **Privacy clean-up of the repository:** your Windows user name, home ZIP, area names and a real local store address were in
  example text and tests in the public repo. They are replaced with neutral examples (12345, Anytown). The older commits
  on GitHub still contain them; removing them from history needs a history rewrite, which is your call.
- Removed two unused imports.
- Checked and found fine: no webhook URLs, API keys or private keys are committed (the PEM blocks in tests are throwaway
  fixtures); the control panel checks the Host header, needs a session token or PIN and only listens on this PC unless you
  switch on allow_lan with a PIN.
- Seen in your log, not changed: Kroger is switched on without a client ID and secret (it pauses every cycle; switch it off in
  Stores & keys or add the free keys), and Target is blocked by PerimeterX (see v2.10).

To test v3.1 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 3.1. Close the running app first.

## v3.0 (2026-10-26, stable release)
- Declared stable by the owner. It is exactly test build v2.10 (saved as build/v2.10), with the version number
  changed to 3.0. Everything listed under v2.10 to v2.1 below is in it: the trial methods, Method control with
  auto-stop, the ZIP stock scan with "search every product", the rolling store history, the CVS in-store-only fix
  and Target block detection.
- Install it with `.\update.ps1` (no channel name). Test builds continue from v3.1.

## v2.10 (2026-10-26, test build, includes v2.9)
- **Search every product** switch in Find stock near a ZIP (on by default). With it on, the scan asks every store that is
  switched on (the hand-picked list is ignored), and searches each store's own catalog for Pokemon products at that moment, so
  you do not have to add links or products first. Up to 150 products per store (30 with the switch off). Product types you
  turned alerts off for are skipped, and non-card items and third-party sellers are filtered out the same way discovery does.
- A store with no catalog search (GameStop, CVS) uses your products plus what discovery already found, and its row says so.
- Still manual only, still no Discord alerts, and the search results are held in memory only: your saved catalog and settings
  are not changed.
- Tests: four new ones in tests\test_scan.py.
- **Rolling history:** the trust table no longer starts from nothing after a restart. Each store's last 40 check outcomes, hourly
  totals for the last 7 days and its last problem are saved in data\store-history.json (a few KB, counts only, no pages or
  URLs) after every check and when the app closes. "Based on" now also shows the last 24 hours or 7 days. The method counts in
  block-stats.json and the trial state were already saved.
- Tests: tests\test_history.py.
- **Target block now shows up as a block.** Target answered the search with a PerimeterX bot-check page that looked like normal
  JSON, so the app logged "search came back empty" and tracked nothing, and the trust table said "not enough data". It is now
  recognised as a block: the log and trust table say Blocked, and the app tries the same call from inside Target's page in your
  browser (page fetch). Tests: tests\test_jsonblock.py.

To test v2.10 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 2.10. Close the running app first. Open **Find stock near a ZIP**, type a ZIP, leave **Search every product at every store that is on** ticked and press Scan now. Untick it to go back to your own products only.

## v2.9 (2026-10-26, test build, includes v2.8)
- **Method control** in the Methods lab, right under "Can I trust each store?": one row per trial method with a Turn on / Turn off
  button and quick numbers (checks in all, % blocked in all, attempts since it was switched on with a failure bar, and a
  "Best so far" badge). **Keep only the best 3** and **Turn off all trials** are one-press buttons. Changes apply at once.
- **Auto-stop:** a trial method that is on is switched off by itself once it has had MORE than 25 attempts and 50% or more of
  them failed or were blocked. Errors (a page that would not load) count as failed. The numbers are settings
  (trials: stop_after, stop_fail_pct, auto_stop) and are editable in the Methods lab. The normal methods are never stopped.
- **Summary:** a banner lists anything that was stopped automatically, each row says when and how many failed, and a short
  "What happened" list shows the last switches. Turning a stopped method back on gives it a fresh count.
- **Remembered:** the on/off choices, the attempt counts and the stopped list are saved in data\trial-state.json, so after a
  restart everything is as you left it. Once you use a button, that saved list wins over config.yaml.
- Turning on the stealth browser now starts its profile straight away, no restart needed.
- A trial method that is blocked no longer sends the normal retry instantly: it waits a few seconds first, so one block does
  not turn into two quick requests at the same store.
- The trial method descriptions were running together; each line now sits on its own row.
- **CVS fix:** items CVS marks "Item for in store purchase only" were being read as in stock online (the page data reports
  the store it picked from your location). They now count as in store only: no "online restock" alert, and the alert lists
  the stores that really have them with the quantity at each and the address. Stores showing 0 are left out.
- Tests: tests\test_methodcontrol.py (the 25 attempt / 50% rule, buttons, best 3, restart), tests\test_cvs.py.

To test v2.9 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 2.9. Close the running app first. Open the control panel, **Methods lab**, and look under "Can I trust each store?" for **Method control**. Turn a method off, close the app, start it again, and it should still be off.

## v2.8 (2026-10-26, test build, includes v2.7)
- New tab in the control panel: **Find stock near a ZIP**. Type a ZIP, drag the radius (1 to 100 miles), pick which stores to
  ask, and press **Scan now**. The app asks Target, Best Buy, Kroger, GameStop and CVS which of their stores in that circle
  have your products (My products plus what discovery found, up to 30 per store) and lists them nearest first with
  quantity, pickup, price, an "over MSRP" mark and a link. A switch adds online stock to the list.
- Manual only: it never runs on a timer, sends no Discord alerts, and does not touch your areas or settings. A store that is
  blocked, off or needs a key shows its reason and the others carry on. Stop cancels a scan in progress.
- Nothing is saved to disk. Only the ZIP, radius and chosen stores are remembered in your browser for next time.
- Walmart and the other sites do not publish shelf stock, so they are not part of this scan.
- Tests: tests\test_scan.py (radius filtering, nearest-first order, blocked and off stores, cancel, nothing written to disk).

To test v2.8 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 2.8. Close the running app first. Press **Control panel**, open **Find stock near a ZIP**, type a ZIP and press Scan now.

## v2.7 (2026-10-26, test build, includes v2.6)
- Stores & speed: the labels in "Free keys for more shelf checks" are wider, so "Walmart.io private key file" is no
  longer cut off, and the key file box is about twice as wide so a full path such as
  %USERPROFILE%\Documents\poke-restock\walmart-private.pem shows without scrolling. The saved value was never cut off.

To test v2.7 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 2.7. Close the running app first, then open Stores & speed and scroll to the Walmart.io fields.

## v2.6 (2026-10-26, test build, includes v2.5)
- New: trial methods. More ways of loading pages, tried one at a time per store so each can be traced.
  For every store only one method runs at once. Each gets a slice of checks (default 20), the normal method
  takes its turns too for a fair comparison, and a method a store blocks sits out for 90 minutes while the
  normal method carries on. If a trial method is blocked, that same check is redone the normal way, so no
  restock check is lost.
- Five trial methods are built in, and three are on by default so each result is easy to read:
  `direct-h2` (plain requests over HTTP/2), `browser-solo` (one steady browser profile instead of rotating)
  and `browser-own` (your own Chrome only). Off by default and one switch away in the Methods lab:
  `direct-warm` (arrive via the store front page with its cookies and Referer) and `browser-slow`
  (rotating profiles at half the pace).
- Two stealth methods, off by default (switch them on in the Methods lab): `direct-impersonate` sends plain
  requests through curl_cffi so the TLS/HTTP2 handshake looks like Chrome's, and `browser-stealth` runs a
  separate "stealth" browser profile on Patchright (Playwright with the automation markers removed; needs
  Chrome installed). They are traced like the others. `browser-stealth` needs an app restart after it is
  switched on. Their packages (`curl_cffi`, `patchright`) are in requirements.txt; run `.\setup.ps1` again.
- Results show in the Methods lab next to the existing methods, a new "Trial methods" panel there lists each
  method, where it came from, where it is running now and where it is resting, with a switch for each.
- Every switch and block is also written to `data\trial-log.jsonl` so a run can be traced afterwards.
- `config.yaml` can set `trials:` (`enabled`, `slice_checks`, `rest_minutes`, `active`, `stores`).
- `direct-h2` needs one extra package, `httpx[http2]`. Run `.\setup.ps1` again, or install it by hand. Until
  it is installed that method is skipped and the log says why.
- Page loads for stores that use page checks are covered (Walmart, GameStop, Costco, Sam's, B&N, BAM, Amazon, Dick's,
  Safeway, Raley's, Walgreens, CVS, Pokemon Center). API stores (Target, Best Buy, Kroger) are not changed.
- Methods lab: the "Left out on purpose" list is gone, since the stealth methods are now trials. CAPTCHA solving and
  proxy rotation are still not built.
- This trial system sits beside the v2.2 feature trial (learned routing, tab rotation) and the side-by-side test; they
  use separate counters. Trial-method checks do not feed the learned-routing counters.

To test v2.6 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
.\setup.ps1
powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 2.6. Close any older copy of the app first. Open Methods lab, scroll to "Trial methods", and switch on one or
two methods at a time. `setup.ps1` installs the new packages (httpx, curl_cffi, patchright).

## v2.5 (2026-10-25, test build, includes v2.4)
- Walmart.io: Stores & keys (web panel and the desktop window) now has Walmart.io fields: Consumer ID, the path to
  your private key .pem file, key version (usually 1) and an optional publisher ID. With them, Walmart stock and prices
  come from Walmart's official affiliate feed (signed requests, done in plain Python, the key file never leaves your PC);
  anything the feed does not return, or any refusal, falls back to the website. The feed's stock can lag the website a little.
- Walgreens API key box added to the desktop window as well (it was already in the web panel since v2.3).
- Version check: v2.4 reached your PC with its VERSION file still saying 2.3. Files are now verified by content, not only size.
- Tests: tests\test_walmart_io.py (signature verified against the key, both key formats, feed path, fallbacks). 141 tests in all.

To test v2.5 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 2.5. Close any older copy of the app first (an already-running app keeps its old screens). Then open Stores & keys: Walmart has the Walmart.io fields, and Walgreens has its API key box.

## v2.4 (2026-10-25, test build, includes v2.3)
- Closing the app closes the browsers: the checking browsers the app opened, and your own Chrome and Edge started
  by start-my-chrome.ps1 and start-my-edge.ps1 (your sign-ins stay in their profiles). It also works when the
  console window is closed, on Ctrl+C, at log off and when another program stops the app. All browsers are told at
  once, checks still waiting are dropped, and no browser re-joins while the app is closing. Turn off the Chrome and
  Edge part with `browser.close_own_on_exit: false` (Stores & keys, Close my Chrome and Edge with the app).
  The control panel tab in your everyday browser is not something the app can close; it just stops answering.
- Tests: tests\test_exit.py (real Chromium started with DevTools closes when the app stops; the setting off leaves it open).
- Every version below has a "To test" block with the PowerShell to run.

To test v2.4 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
`VERSION` should print 2.4. Start it, then close the app window: the Chrome window should close too.

## v2.3 (2026-10-25, test build, includes v2.2)

To test v2.3 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1
powershell -ExecutionPolicy Bypass -File .\learn-traffic.ps1 -Site gamestop -Zip 12345 -ProductId 123456
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
- Trust report: the top of Methods lab now rates every store Reliable (90% or more of recent real checks
  loaded), Flaky (60 to 89%) or Blocked (under 60%), shows what the rating is based on, the best method found
  by the side-by-side test, and what to do about it. It reads only numbers the app already collects (recent
  checks, block counts, side-by-side runs) and needs about 10 checks before it rates a store.
- Official feeds: Best Buy and Kroger have official developer APIs that use no bot checks. A store that is on
  but has no key shows "Needs setup", and a store that is off but could use its feed is listed under the table.
  Target already uses its own data feed. Other stores publish no feed, so they stay on page checks.
- Learn from your own browsing (idea from Klura): `learn-traffic.ps1 -Site gamestop -Zip 12345 -ProductId <id>`
  listens, through your own Chrome's DevTools port on this PC, to the data requests the store's page makes while
  you use its own "check nearby stores" box. It keeps only JSON answers, no cookies or headers, with token-like
  values blanked, ranks the ones that look like stock or store answers, and saves the replayable ones as
  templates in data\learned\endpoints.json. The GameStop store reader tries those first, so it can use the
  store's real request instead of a guess.
- Discord channels no longer repeat each other: online stock goes to the online channel and shows only the
  online side, in-store stock goes to the in-store channel and shows only the shelf stock, and only the side
  that actually changed is posted. If both channels are the same (or only a default channel is set) you still get
  one combined alert. A channel named after a store still shows everything for that store.
- Walgreens: a new optional "API key" box under Stores & keys (Walgreens) takes your key from developer.walgreens.com.
  With it, "Stores near you" lists exact Walgreens stores from Walgreens' Store Locator. Walgreens' public API has no
  stock data, so stock still comes from product pages. The request shape is from public descriptions and is not
  verified against a live key; if it fails, the answer is saved to data\debug and the app says so.
- Tests: tests\test_walgreens.py, tests\test_trust.py, tests\test_learn.py (including a real Chromium recording), tests\test_split.py.

## v2.2 (2026-10-25, test build, includes v2.1)

To test v2.2 (PowerShell):
```
cd "$HOME\Documents\poke-restock"
Get-Content .\VERSION
powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1
powershell -ExecutionPolicy Bypass -File .\start-my-edge.ps1
powershell -ExecutionPolicy Bypass -File .\run.ps1
```
- Side-by-side test: every 15 minutes per store (`browser.compare_every_minutes`, 0 = off) one product page is loaded
  through every method at once (plain request, each browser profile, your own Chrome and Edge). Results are kept
  in data\compare.json and shown in Methods lab as a like-for-like table. A blocked profile rests as usual and a
  comparison never pops a window asking you to verify.
- Learned routing: checks go first to the methods the side-by-side tests found reliable (90% or more loaded over
  5 or more runs) and last to the ones mostly refused (`browser.learn_from_compare`).
- Feature trial: about half of the checks run without learned routing and without tab rotation, and the blocks
  are counted with and without each, so Methods lab can say "Helping", "No clear difference", "Not helping" or
  "Too early to say" (30 checks each side). Turn it off with `browser.feature_trial: false`.
- `run.ps1 -Update` installs the newest stable release before starting (`-Update -Channel test` for the newest
  test build). A snapshot is saved first.
- Tests now include a real Chromium run against a local site (tests\test_live_browser.py), covering joining a
  browser started with DevTools, page fetch GET and POST, the Cloudflare false-positive fix and a real
  side-by-side run. 97 tests in all.

## v2.1 (2026-10-25, test build)
- New method: your own Edge. Run start-my-edge.ps1 (port 9223, profile in data\my-edge) and it joins like your
  own Chrome, so the Methods lab can show which real browser each store accepts. `browser.own_edge_port: 0` turns it off.
- New method: page fetch. When a plain data request is refused (Target's data calls first), the same call is
  repeated from inside the store's own page in a real browser, the way the store's scripts do it. It is counted
  separately in the Methods lab (for example "Page fetch: edge"). `browser.page_fetch: false` turns it off.
- Methods lab: a "Methods to compare" list shows every method with its checks and blocks (or "Not tried yet"),
  and "Left out on purpose" lists what was not taken from the reviewed repositories and why.
- Ideas used from the reviewed repositories are the ones that keep a real, unmodified browser (SeleniumBase's
  DevTools control and page-context calls). Stealth patches, fingerprint mimicry, human-motion imitation, CAPTCHA
  services and proxy rotation stay out, per the project rules.

## v2.0 (2026-10-25, stable release)
- Declared stable by the owner. It is exactly test build v1.2 (saved as build/v1.2), with the version number
  changed to 2.0. Everything listed under v1.2 below is in it.
- Install it with `.\update.ps1` (no channel name). Test builds continue from v2.1.

## v1.2 (2026-10-25, test build)
- Fixed a false "wants a quick human check" on GameStop. Cloudflare adds a harmless script
  (`/cdn-cgi/challenge-platform/.../jsd/main.js`) to ordinary pages it protects, and the app took it for a
  challenge. Only markers that appear on a real challenge page count now, and a "Server: cloudflare" or
  Akamai header alone no longer marks a normal 200 page as blocked.
- GameStop now tries your own Chrome first (added to `browser.own_chrome_sites`; built in, so an old
  config.yaml picks it up too). Run start-my-chrome.ps1 and leave that window open.
- GameStop store stock by area (experimental): with in-store checking on, each GameStop product link is also
  checked for pickup stock around every area ZIP and radius, and stores with stock alert like Target's.
  GameStop does not publish this lookup, so two likely request shapes are tried and the one that answers is
  remembered. If neither is readable the app logs it once and saves the answer to data\debug.
- CVS store counts by area: CVS's own "Check more stores" list returns the shelf count for every store
  around a ZIP (for example 5 at one store, 1 at another). With in-store checking on, each CVS product
  link is asked about every area ZIP through your own Chrome, stores inside the area radius with stock
  alert, and the count and pickup flag are shown. It uses the same request CVS's website makes (found by
  watching the page); `retailers.cvs.api_key` can override the site key if CVS changes it.
- Safeway: no counts found. Safeway only shows in stock or out of stock for your chosen store, so the app
  keeps checking that.

## v1.1 (2026-10-25, test build)
- Your own Chrome now joins while the app is running: start it with start-my-chrome.ps1 at any time and
  checks pick it up within about 15 seconds. No restart needed. If you close it, it is forgotten and
  rejoins when it is running again.
- When CVS or Dick's refuse the app's own browsers and your Chrome is not running, the message now
  says so and names start-my-chrome.ps1, instead of only "refused the request".
## v1.0 (2026-10-25, first stable release)
- Declared stable by the owner. It is exactly test build v0.6 (saved as build/v0.6), with the version number
  changed to 1.0. Everything listed under v0.1 to v0.6 below is in it.
- Install it with `.\update.ps1` (no channel name). Test builds continue from v1.1.

## v0.6 (2026-10-25, test build)
- The version now shows in the control panel (under "Running on this PC", for example "v0.6 test build")
  and in the app window's title bar.
- Delay between links: before loading the next page of the same store, the monitor waits the
  "Delay between links" time (default 4 seconds, plus up to half again at random). Set it under
  Check speed. It applies to browser checks and to plain page checks.
- Tabs per store: a store's pages now rotate through several browser tabs (default 3, 1 to 6)
  instead of reloading one tab. Set it under Stores & keys, in the browser section.
- A saved settings change now reaches the running browsers without a restart.

## v0.5 (2026-10-25, test build)
- Verify window: "Show browser window" now brings forward only the browser that is waiting, restores
  it if minimized and makes Windows give it focus. The banner and log name that browser
  (for example "Chrome"). Untested on Windows until you try it.
- Your own Chrome: `start-my-chrome.ps1` opens a normal Chrome with its own profile and DevTools on
  this PC only. When it is running at start-up the monitor adds it as the "my-chrome" browser and
  checks CVS and Dick's through it first (`browser.own_chrome_sites`), falling back to the others.
  An attached Chrome is never moved off screen.
- Slow-downs after a block are saved in `data\pacing.json` and ease off with a 30 minute half-life, so
  a restart no longer sends a store back to full speed right after it pushed back.

## v0.4 (2026-10-25, test build)
- A store that answers with a flat "Access Denied" page (Akamai on CVS) is no longer reported as
  "waiting for you to verify". There is nothing to verify on that page, so it now shows as refused,
  rests that browser profile for the store, and the other profiles carry on.
- Product links saved with http:// are upgraded to https://.
- The new Glass Aurora control panel file had not reached the PC with v0.3; it is included now.

## v0.3 (2026-10-25, test build)
- update.ps1 stops with a clear message when a channel has no program files (the stable branch is
  empty until a release is declared), instead of reporting a successful update.

## v0.2 (2026-10-25, test build)
- Control panel re-skinned to the Glass Aurora look (dark violet, frosted panels, cyan = in stock).
  No outside fonts or requests; it uses system fonts.
- New Methods lab page: checks per block by method, best method per store, resting profiles.
- Notifications page: Online and In-store channel fields. Areas page: a webhook per area.
- The desktop window stays the lightweight version; bigger visuals go in the control panel.

## v0.1 (2026-10-25, test build, first tagged build)
- Browser profiles: several checking browsers (Edge or Chrome), each with its own cookies. Checks
  rotate across them; a blocked profile rests for that store and the others carry on.
- Optional attach to your own Chrome over DevTools (`cdp_url`).
- Block tracker: counts checks until a block for every method and store, saved in
  `data\block-stats.json`. Shown under More > Block tracker, or `app.py --stats`.
- `app.py --abtest`: runs plain requests and every profile side by side on the same pages.
- Recognizes Dick's "try again after 12 hours" page and honors the wait. Akamai "Access Denied"
  rests that profile instead of the whole store.
- Discord channels: Online, In-store, and an optional webhook per area (that area's stores only).
- Target search retries with simpler settings and falls back to known products, so shelf checks
  run even when search is empty (this was why in-store alerts never fired).
- Discord delivery fixes: an alert spread over many stores could exceed Discord's 6000-character
  embed limit and be refused, and a refused alert was marked as sent and never retried. Embeds are now
  trimmed to fit, failed sends retry on the next check (up to 6 times), and stores fall back to the
  main channel when there is no In-store channel.
- GitHub: `main` = stable, `test` = test builds, `update.ps1` installs either. Versions: see RELEASING.md.
- `versions.ps1`: save, list, mark stable, restore. `NOTES.md`, `RESOURCES.md` added.

## Before tagged builds (3.x)
- Per-store MSRP allowance, alerts grouped by area, Imperva hard-ban handling, duplicate-loop
  and closed-browser fixes, setup script rewrite.
