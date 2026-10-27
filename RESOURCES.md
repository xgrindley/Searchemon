# Tools and resources reviewed

Rolling list. Add a row each time something new is looked at, with what was decided and why.
Earlier versions kept to a rule of no disguise, no proxies and no CAPTCHA services. That rule was lifted at your
request: stealth (v2.6), and rotating User-Agents, proxies, a VPN reconnect command and CAPTCHA services (v5.0) are
all built in as scored methods. Polite pacing still applies to every method.

| Resource | What it is | Decision | Why |
|---|---|---|---|
| PortSwigger/bypass-bot-detection (Apache-2.0) | Burp Suite extension that changes TLS cipher suites to mimic Firefox, Chrome or Safari and forces HTTP/1 | Not used | It is a security-testing aid that disguises the client's TLS fingerprint. That is spoofing. Our approach is to use a real browser instead, which already has a genuine fingerprint |
| seleniumbase/SeleniumBase (MIT) | Selenium/Playwright framework; its UC Mode and CDP Mode are built to avoid detection | Ideas only (v0.5 adds start-my-chrome.ps1) | Its stealth modes are fingerprint hiding. The legitimate ideas it shares with us (a real Chrome, DevTools Protocol, human-paced actions) are already in the app |
| CloakHQ/CloakBrowser (MIT, separate binary license) | Chromium rebuilt with 87 patches that fake canvas, WebGL, audio, fonts, GPU and screen values | Not used | Fingerprint spoofing by design, and a third-party browser binary would run with your sign-ins |
| ultrafunkamsterdam/undetected-chromedriver (GPL-3.0) | Patched chromedriver that hides automation markers | Not used | Hides that the browser is automated. GPL license also complicates reuse. Maintenance status unclear |
| HarimxChoi/anti_bot_scraper | Playwright scraper for a Korean real-estate site with random zoom, drags and mouse movement | Not used | Built around imitating human behavior to dodge detection; different target and purpose |
| crowdsecurity/crowdsec | Server-side tool that reads logs and blocks abusive IPs, with a shared blocklist | Lesson only (v0.5 remembers slow-downs across restarts) | It is what site operators run, not a client tool. Useful only as a reminder of why steady, low-volume traffic from one real IP gets blocked less |
| klura-ai/klura (BSL 1.1, not open source until its change date) | Turns a recorded browser session into a reusable call: it finds the request the site's own page makes and replays it, either directly or from inside the live tab, validates the answer's shape, and hands CAPTCHAs and 2FA to a person | Ideas used (v2.3: learn-traffic.ps1, learned endpoints). No code copied | "Learn from traffic" and "replay the page's own request from inside the page" fit our rules and replace guessing at store endpoints. Its checks that an answer has the expected shape match what we want for trust. Its stealth driver with fingerprint patches is not used, and its license forbids reusing the code in a competing service anyway |
| anti-captcha.com | Paid CAPTCHA-solving service (people and software solve a CAPTCHA you send them) | Used (v5.0), with 2Captcha and CapSolver as choices | Kept as a reference at your request. The app does not call it, and there is no integration. When a store wants a person, the app still asks you to finish the check |

| jef/streetmerchant (MIT) | The best-known open-source restock monitor (graphics cards, consoles); per-store "add to cart" / "sold out" labels, a timestamp on every link, low-bandwidth mode, ordinary page visits between product checks, per-store back-off that halves again on success, and forwarding CAPTCHAs to a person | Ideas used (v4.1: three trial methods, buy-button reading) | Its labels, cache-buster, low-bandwidth and "captcha deterrent" ideas are honest ways to load or read a page, so they became trial methods and a fallback. Back-off that eases off on success was already here (each good check speeds a store back up by 20%). Its CAPTCHA forwarding matches what we already do (the check waits for you) |
| nearyou/pokemon-stock-monitor | Small Python Pokemon monitor: requests + BeautifulSoup, rotating User-Agents, a cache-buster query, plus or minus 20% interval jitter, 1.5 to 3.5 s between products, "add to cart" / "sold out" text checks, restock-time notes, and advice to use VPNs, proxies or CAPTCHA services | Ideas used (v4.1: cache-buster method, buy-button reading; v5.0: rotating User-Agents, proxies and VPNs, CAPTCHA services) | The cache-buster and text checks came first. Interval jitter and gaps between products were already here (jitter_seconds, per-site gaps). Rotating User-Agents, proxies, VPNs and CAPTCHA services were added in v5.0 when you lifted the rule against them. Its restock-time claims are unverified, so the app keeps learning restock times from its own history instead |
| HarperCT/pokemonAvaliabilityBrisbane | Brisbane (Australia) checker for Big W, Kmart and a game shop through their stock APIs; opens the Big W front page first to collect cookies | Idea used (v4.1: the "browse the front page" method) | Its stores are Australian, so none of its endpoints apply. The front-page-first habit is shared with streetmerchant and became part of a trial method |
| Reptop/PokeStock | SvelteKit + Firebase community map of Pokemon vending machines, stocked by people's reports | Not used | A community reporting site, not a monitor. Nothing to take for store checks |
| kadarius0719/drip-drop-pokemon (from the restock-alert topic) | Personal Pokemon TCG drop tracker: Best Buy API, Target RedSky, release-date reminders, and the r/PokemonTCGDeals feed as an early warning; refuses to evade anti-bot systems | Ideas used (v4.1: community tips, newest set names) | Reading r/PokemonTCGDeals (a public page, no account) became community tips that check matching products at once and add linked products. Its pointer to TCGCSV became the daily newest-set-names search. Same stance as ours on anti-bot evasion |
| tcgcsv.com | Free daily mirror of TCGplayer's catalog (sets, products, prices) | Used (v4.1, one request a day) | The Pokemon set list (category 3) gives the newest set names for store searches. Read once a day with a named User-Agent, as its rules ask |
| github.com/topics/restock-alert | Topic page listing restock monitors | Looked at | Besides drip-drop-pokemon, it lists ENCHIGO/apple-pickup-watcher, jamesccupps/UnifiStockWatcher, shali10/vps-monitor, hh-io/refurb-sentry and Mohammed-Shajith/Rewards_Watcher. All watch other kinds of stores (Apple, Ubiquiti, VPS hosts, rewards gift cards), so only their names are recorded here |

## Implemented as trial methods (v2.1)

Each is switched on or off in the Methods lab, runs one at a time per store, and is traced in
`data\trial-log.jsonl` and in the Methods lab tables.

| Method | Idea taken from | What was taken | What was left out |
|---|---|---|---|
| direct-h2 | PortSwigger/bypass-bot-detection | Real clients speak HTTP/2 and Python's requests speaks HTTP/1.1, so try the same honest request over HTTP/2 | The cipher suite and header mimicry of Firefox, Chrome or Safari |
| direct-warm | SeleniumBase | Arrive the way a person does: front page first, cookies kept, then the product with a Referer | UC Mode and CDP stealth patches |
| browser-solo | CrowdSec | Steady, low-volume traffic from one real session is blocked less than a spread across many | Shared blocklists (server side only) |
| browser-own | SeleniumBase CDP mode | Drive a real, visible, signed-in Chrome or Edge over the DevTools Protocol (start-my-chrome.ps1) | Anything that hides that it is automated |
| direct-impersonate | PortSwigger/bypass-bot-detection | TLS and HTTP/2 fingerprint of Chrome, via the curl_cffi library | Burp Suite itself |
| browser-stealth | undetected-chromedriver, SeleniumBase UC mode, CloakBrowser | Hiding automation markers, via Patchright in its own profile | Fake canvas/WebGL/audio values, third-party browser binaries |
| browser-slow | CrowdSec | Half the pace on a store while it runs | None |
| direct-fresh (v4.1) | jef/streetmerchant, nearyou/pokemon-stock-monitor | A throwaway time stamp on each link so no cache answers with an old page; the stamp never shows in links or alerts | None |
| browser-light (v4.1) | jef/streetmerchant | Low-bandwidth mode: no pictures, video or fonts, so less traffic per check | Its ad blocker |
| browser-warm (v4.1) | jef/streetmerchant, HarperCT/pokemonAvaliabilityBrisbane | Open the store's front page now and then before a product, like browsing | Searching unrelated words (its "deterrent" searches) |

| direct-ua (v5.0) | nearyou/pokemon-stock-monitor | Each check as a different current desktop browser, each with its own cookies | None |
| direct-proxy (v5.0) | nearyou/pokemon-stock-monitor | Plain requests through your proxies in turn; a blocked proxy rests at that store | None |
| browser-proxy (v5.0) | nearyou/pokemon-stock-monitor | A separate, never signed-in browser profile through your proxies, moving on after a block | None |

Also in v5.0, outside the trial rotation: a CAPTCHA-solving service (2Captcha, Anti-Captcha or CapSolver) answers
CAPTCHAs in the checking browsers, counted per store as "captcha-<service>", and a VPN reconnect command (config.yaml only)
runs after several blocks in a row.

New methods are switched on once by themselves after an update, so every method gets checked and scored.
Once every method at a store has about 8 recent checks, the best one there gets about four normal turns for each
turn the others get (they keep short turns, so a change at the store is still noticed). A method that keeps failing
is still stopped by itself, and your own on/off choice always wins.

## What we took from them (the honest part)

- A real signed-in Chrome or Edge profile behaves like a person's browser. Several separate
  profiles, each with its own cookies, share the load, so one session is not asked for everything.
- Chrome DevTools Protocol is the right way to control a real browser (Playwright already uses
  it). The app can also attach to a Chrome you start yourself, so it uses a profile you know.
- Calling a store's data from inside its own page, in a real browser (SeleniumBase's CDP mode idea, minus its
  stealth), is the "page fetch" method. A second real browser (your own Edge) joins beside your own Chrome.
- Measure, don't guess, and keep measuring: side-by-side runs, learned routing and the feature trial show
  which methods and features earn their place.
- From Klura: learn a store's real data request from your own browsing instead of guessing it
  (learn-traffic.ps1 saves the page's own request as a template with {zip}, {pid}, {radius} slots in
  data\learned\endpoints.json, and the monitor tries it first), keep nothing sensitive while doing it (no cookies or
  headers, token-like values blanked), and judge a result by whether the answer has the expected shape rather
  than by a 200 status. A person handles human checks, as Klura also does.
- Measure, don't guess: the block tracker and `--abtest` show which method lasts longest per store.

## Tools in use

Python 3.13, requests, PyYAML, Playwright (Edge or Chrome channels), zipcodes (offline ZIP data),
winotify, tkinter. Target "redsky" web endpoints, Best Buy API, Kroger API, page JSON-LD parsing.
