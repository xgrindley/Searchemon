# Tools and resources reviewed

Rolling list. Add a row each time something new is looked at, with what was decided and why.
Standing rule for this project: pace politely, use a real browser, sign in with your own
accounts, and let a person finish checks.

| Resource | What it is | Decision | Why |
|---|---|---|---|
| PortSwigger/bypass-bot-detection (Apache-2.0) | Burp Suite extension that changes TLS cipher suites to mimic Firefox, Chrome or Safari and forces HTTP/1 | Not used | It is a security-testing aid that disguises the client's TLS fingerprint. That is spoofing. Our approach is to use a real browser instead, which already has a genuine fingerprint |
| seleniumbase/SeleniumBase (MIT) | Selenium/Playwright framework; its UC Mode and CDP Mode are built to avoid detection | Ideas only (v0.5 adds start-my-chrome.ps1) | Its stealth modes are fingerprint hiding. The legitimate ideas it shares with us (a real Chrome, DevTools Protocol, human-paced actions) are already in the app |
| CloakHQ/CloakBrowser (MIT, separate binary license) | Chromium rebuilt with 87 patches that fake canvas, WebGL, audio, fonts, GPU and screen values | Not used | Fingerprint spoofing by design, and a third-party browser binary would run with your sign-ins |
| ultrafunkamsterdam/undetected-chromedriver (GPL-3.0) | Patched chromedriver that hides automation markers | Not used | Hides that the browser is automated. GPL license also complicates reuse. Maintenance status unclear |
| HarimxChoi/anti_bot_scraper | Playwright scraper for a Korean real-estate site with random zoom, drags and mouse movement | Not used | Built around imitating human behavior to dodge detection; different target and purpose |
| crowdsecurity/crowdsec | Server-side tool that reads logs and blocks abusive IPs, with a shared blocklist | Lesson only (v0.5 remembers slow-downs across restarts) | It is what site operators run, not a client tool. Useful only as a reminder of why steady, low-volume traffic from one real IP gets blocked less |
| klura-ai/klura (BSL 1.1, not open source until its change date) | Turns a recorded browser session into a reusable call: it finds the request the site's own page makes and replays it, either directly or from inside the live tab, validates the answer's shape, and hands CAPTCHAs and 2FA to a person | Ideas used (v2.3: learn-traffic.ps1, learned endpoints). No code copied | "Learn from traffic" and "replay the page's own request from inside the page" fit our rules and replace guessing at store endpoints. Its checks that an answer has the expected shape match what we want for trust. Its stealth driver with fingerprint patches is not used, and its license forbids reusing the code in a competing service anyway |
| anti-captcha.com | Paid CAPTCHA-solving service (people and software solve a CAPTCHA you send them) | Noted only, not built | Kept as a reference at your request. The app does not call it, and there is no integration. When a store wants a person, the app still asks you to finish the check |

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
