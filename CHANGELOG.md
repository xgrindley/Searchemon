# Changelog

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
