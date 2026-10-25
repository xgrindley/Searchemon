# Changelog

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
