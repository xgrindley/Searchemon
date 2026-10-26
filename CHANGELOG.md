# Changelog

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
