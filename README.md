# Pokemon Restock Monitor

A Windows app that watches Pokemon TCG stock at 13 retailers, online and on
the shelves of stores near your ZIP codes, and posts to your Discord restock
channel when something comes back in stock at or near MSRP. It finds nearby
stores and Pokemon products on its own, confirms each restock before
alerting, and learns when your stores usually restock. Checks run from your
own PC while the app is open.

The full user guide (setup, every setting, reading alerts, troubleshooting)
is the "Pokemon Restock Monitor: User Guide" document shared with this
download. This file is the short version.

## Setup (PowerShell)

1. Install Python 3.13: `winget install -e --id Python.Python.3.13`, or from
   python.org (tick "Add python.exe to PATH"). Versions 3.11 to 3.14 work;
   brand-new ones such as 3.15 fail to install the packages. Setup picks a
   working version if you have several.
2. Open PowerShell, go into this folder, then run setup:

   ```powershell
   cd "$HOME\Documents\poke-restock"
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

3. Start it (step 4), open the control panel, then:
   - Notifications: paste your channel's webhook URL
     (Server Settings > Integrations > Webhooks > New Webhook > Copy Webhook URL)
   - Areas & radius: your home ZIP and a radius
   - optional: a free Best Buy API key and a free Kroger client ID and secret
4. Start it:

   ```powershell
   .\run.ps1
   ```

   Click **Test Discord** to confirm the channel gets a message.

Optional: `.\add-to-startup.ps1` opens it when you sign in, and
`.\build-exe.ps1` builds a standalone `PokeRestock.exe`.

## Control panel

While the app is open, a control panel runs at **http://127.0.0.1:8765**
(the window has an **Open control panel** button). From there you can:

- see every listing being watched, with in-stock rows highlighted, recent
  alerts and each store's status (OK, blocked, error)
- add, edit, turn off or remove products and keyword searches
- set the keywords an alert must include or must never include, and the MSRP
  caps by product type
- **Test a listing**: paste a product title and price to see whether it would
  alert and why
- mute a single listing, pause all alerts (checks keep running), or check now
- turn retailers on and off, change how often each is checked, set your ZIP
- set your Discord webhook(s), role ping, and send a test message. Optional extra channels:
  Online, In-store, and one per area (set on the Your area tab; it gets only that area's stores)

Save changes and the checks restart with the new settings. The panel only
answers on this PC. To use it from your phone on home Wi-Fi, turn on
**Phone access** under Stores & keys, set a PIN, and restart the app.

## When stores push back

Big retailers run bot protection, and a monitor that ignores it gets blocked
for longer and longer. This one works with it instead:

1. **Recognizes the block.** It tells a rate limit from a JavaScript check from
   a CAPTCHA, and names the vendor (Akamai, PerimeterX, Imperva, Cloudflare,
   DataDome) in the log so you know what happened.
2. **Slows down on its own.** Each block doubles that store's wait (up to 8x),
   and it eases back to normal speed after clean checks. The dashboard shows
   each store's recent success rate and next check time.
3. **Switches to a real browser.** In `auto` mode, once plain requests are
   refused, checks for that store move to an Edge window (built into Windows)
   with its own profile, loading pages the way you would. Many JavaScript
   checks clear by themselves there.
4. **Asks you when a person is needed.** If a store wants a press-and-hold or
   puzzle, the browser window comes on screen, you get a Windows notification
   and a banner in the control panel, and checks for that store wait (without
   reloading) until you finish it. The cookies it earns carry the next checks.

**Several browsers, rotated.** Blocks are usually tied to one browser session (its cookies),
not your connection. The app runs more than one checking browser, each with its own profile
(`browser.profiles` in config.yaml: Edge and Chrome by default), and rotates checks across
them. When a store blocks one, that one rests for that store (as long as the block says, for
example 12 hours for Dick's) while the others keep checking. Edge or Chrome matters less than
having separate cookies. Your own Chrome helps most with CVS, Dick's and
GameStop: run `powershell -ExecutionPolicy Bypass -File .\start-my-chrome.ps1`, leave that Chrome
open. The app adds it as "my-chrome" automatically, even while running and checks those stores first
(`browser.own_chrome_sites`).
Your own Edge works the same way: `powershell -ExecutionPolicy Bypass -File .\start-my-edge.ps1` (port 9223), so the Methods lab can compare the two.
Methods lab also runs a side-by-side test (`browser.compare_every_minutes`), routes checks to the methods that proved reliable,
and A/B tests the app's own features (`browser.feature_trial`) so you can see whether they help. `run.ps1 -Update` updates to the newest stable first.
When a plain data request is refused, it is retried from inside the store's own page (page fetch; `browser.page_fetch`).
Sign in to a store once and it opens in every profile. Restart the app after changing profiles.
To learn a store's real data request from your own browsing (no guessing), start your own Chrome, then run
`powershell -ExecutionPolicy Bypass -File .\learn-traffic.ps1 -Site gamestop -Zip 89436 -ProductId 123456` and use the store's
"check nearby stores" box. Online alerts go to the online channel and in-store alerts to the in-store channel, each showing only its own side.
Methods lab opens with a trust report that rates each store Reliable, Flaky or Blocked from the app's own recent checks, and points out official feeds (Best Buy, Kroger) that are not switched on.

**See what works.** More > Block tracker (or `app.py --stats`) shows, per store and method, how
many checks got through before a block. `app.py --abtest` runs plain requests and every profile
side by side on the same pages at a gentle pace and prints which was blocked last.

What it deliberately does not do: fake its browser fingerprint, hide that it
is automated, pay CAPTCHA-solving services, or rotate proxies to dodge bans.
Those break the stores' terms, get accounts flagged, and are exactly what
scalper bots do. Polite pacing plus a real browser plus you, once in a while,
holds up better over time.

## Know when your stores restock

Every restock the monitor sees while running is logged per store, day and
hour (`data\history.jsonl`). The **Restock times** view in the control panel
turns that into a week grid and lists the most likely windows, for example
"Tue 7 AM to 9 AM" at your nearest Target. With `learn_from_history` on, the
monitor also checks twice as often during those hours. You can add your own
busy and quiet hours under Check speed.

Alerts also say whether a store has **order pickup** available. When it
does, buy online right away and pick it up, instead of hoping the shelf still
has it when you arrive.

## What it watches

- **Found automatically:** every 6 hours it searches Target, Best Buy, Walmart
  and Kroger for Pokemon cards, keeps the sealed products, and tracks them.
  New listings post a blue alert. See the Found products tab.
- **Your products:** a UPC finds the item at Target, Best Buy, Walmart and
  Kroger; product links cover Pokemon Center, GameStop, Costco, Sam's Club,
  Barnes & Noble, Books-A-Million, Amazon, Walgreens, CVS and any other store.
- **Your searches:** extra keyword searches on the searchable stores.

Stores near your areas are mapped weekly (store finders plus OpenStreetMap)
on the Stores near you tab.

## How alerts decide

An alert fires when stock appears that was not there on the last check, and
only if the listing is a sealed card product of a type you want, sold by the
store itself, priced at or under its MSRP cap (plus wiggle room), at a store
inside one of your areas, and still there on a second look a few seconds
later. The same item and store will not re-alert within the quiet period.

## Store coverage

| Store | Online | Shelf stock near you | Needs |
|---|---|---|---|
| Target | yes | units per store, pickup | nothing |
| Best Buy | yes | stores with stock, pickup | free API key |
| Kroger family | no | high/low per store, curbside | free client ID and secret |
| Walmart | yes | pickup at your chosen store | optional: set store in the checking browser |
| Pokemon Center | yes, plus queue alert | no | product links |
| GameStop, Costco, Sam's Club, Barnes & Noble, Books-A-Million | yes | no | product links |
| Amazon | sold by Amazon only | no | product links |
| Dick's Sporting Goods | yes, found automatically | no | nothing (uses the browser) |
| Safeway / Albertsons | yes | for your chosen store | set store in the checking browser |
| Raley's | online listings (untested) | no | product links |
| Walgreens, CVS | online listings | no | product links |

Target's data comes from the same lookups target.com makes, not an official
API. If a store breaks after a site change, turn on "Save raw responses",
run `app.py --once`, and the raw responses land in `data\debug` for fixing.

## Files

- `config.yaml`: your settings and webhook (private, never share)
- `data\config.backup.yaml`: the previous settings, saved each time the panel saves
- `data\state.json`: last seen stock per item, used to detect changes
- `data\resolved.json`: UPC to retailer item id lookups
- `data\restock.log`: activity log (rotates at 1 MB)
- `data\history.jsonl`: restocks seen, for Restock times (kept 180 days)
- `data\catalog.json`: products found automatically
- `data\places.json`: stores near your areas
- `data\block-stats.json`: the block tracker numbers
- `data\browser-profile` (and `browser-profiles\<name>`): the checking browsers' own profiles and cookies
  (separate from your normal Edge; delete the folder to reset it)

## Versions and rollback

```powershell
.\versions.ps1 save "before trying X"   # snapshot of the program files
.\versions.ps1 stable                   # mark the newest snapshot as the known-good one
.\versions.ps1 list
.\versions.ps1 restore                  # back to the stable one (or: restore <name>)
```

Snapshots hold program files only; `config.yaml` and `data` are never touched, and restore
saves your current files first. `CHANGELOG.md` lists changes, `NOTES.md` is the rolling project
memory, `RESOURCES.md` lists the tools reviewed and why each was used or not.

## Commands

```powershell
.\.venv\Scripts\python.exe app.py                # window
.\.venv\Scripts\python.exe app.py --headless     # console only
.\.venv\Scripts\python.exe app.py --once         # one pass, print results
.\.venv\Scripts\python.exe app.py --test-discord
.\.venv\Scripts\python.exe app.py --abtest     # compare checking methods
.\.venv\Scripts\python.exe app.py --stats      # checks-before-block table
```
