"""CAPTCHA-solving service: when a page in a checking browser shows a CAPTCHA, send it to a solving service you
signed up for (2Captcha, Anti-Captcha or CapSolver), put the answer into the page, and carry on, instead of waiting
for you. If it is off, not set up, out of today's budget, or the service fails, the old behavior stands: the window
comes forward and the check waits for you.

What it can answer: reCAPTCHA v2 checkboxes, hCaptcha (2Captcha and Anti-Captcha), Cloudflare Turnstile widgets, and
"type the characters" pictures (Amazon). What it cannot: PerimeterX "Press & hold" (Walmart, Target) and Akamai
checks are not CAPTCHAs these services answer, so those still count as blocks.

What is sent: the page address and the CAPTCHA's public site key (or the picture). Your cookies and sign-ins are not
sent. Each answer costs a fraction of a cent; max_per_day caps how many are sent in a day. Every attempt is counted in
Advanced > Connection methods as the method "captcha-<service>", so you can see whether it pays off at each store.

Settings (Advanced > Connection methods, or config.yaml):
    captcha:
      service: ""            # 2captcha | anticaptcha | capsolver (empty = off)
      api_key: ""
      max_per_day: 30
      stores: []             # only these sites (for example cvs.com); empty = any
"""
from __future__ import annotations

import base64
import os
import threading
import time

import requests

from .util import atomic_write_json, read_json

SERVICES = {"2captcha": "https://api.2captcha.com", "anticaptcha": "https://api.anti-captcha.com",
            "capsolver": "https://api.capsolver.com"}
NAMES = {"2captcha": "2Captcha", "anticaptcha": "Anti-Captcha", "capsolver": "CapSolver"}
TASKS = {
    "recaptcha": {"*": "RecaptchaV2TaskProxyless", "capsolver": "ReCaptchaV2TaskProxyLess"},
    "hcaptcha": {"*": "HCaptchaTaskProxyless", "capsolver": ""},           # CapSolver does not take hCaptcha
    "turnstile": {"*": "TurnstileTaskProxyless", "capsolver": "AntiTurnstileTaskProxyLess"},
    "image": {"*": "ImageToTextTask"},
}
POLL_S = 5
WAIT_S = 150
DEFAULT_PER_DAY = 30
FILE = "captcha.json"

SOLVER = None        # set by the engine: the Solver in use, or None


# Finds a CAPTCHA on the page: {"kind", "sitekey" | "src", "callback"} or null.
DETECT_JS = r"""() => {
  const q = (s) => document.querySelector(s);
  const frames = [...document.querySelectorAll('iframe')].map((i) => i.src || '');
  let el = q('.cf-turnstile[data-sitekey]');
  if (el) return { kind: 'turnstile', sitekey: el.dataset.sitekey, callback: el.dataset.callback || '' };
  for (const s of frames) { const m = s.match(/challenges\.cloudflare\.com\/.*?\/(0x[A-Za-z0-9_-]{10,})\//); if (m) return { kind: 'turnstile', sitekey: m[1], callback: '' }; }
  el = q('.h-captcha[data-sitekey]');
  if (el) return { kind: 'hcaptcha', sitekey: el.dataset.sitekey, callback: el.dataset.callback || '' };
  for (const s of frames) { const m = s.match(/hcaptcha\.com\/.*[?&#]sitekey=([0-9a-fA-F-]{20,})/); if (m) return { kind: 'hcaptcha', sitekey: m[1], callback: '' }; }
  el = q('.g-recaptcha[data-sitekey]');
  if (el) return { kind: 'recaptcha', sitekey: el.dataset.sitekey, callback: el.dataset.callback || '' };
  for (const s of frames) { const m = s.match(/recaptcha\/(?:api2|enterprise)\/anchor\?(?:.*&)?k=([A-Za-z0-9_-]{20,})/); if (m) return { kind: 'recaptcha', sitekey: m[1], callback: '' }; }
  const input = q('#captchacharacters, input[name*="captcha" i][type="text"]');
  const img = q('form[action*="aptcha"] img, img[src*="captcha" i]');
  if (input && img && img.src) return { kind: 'image', src: img.src, callback: '' };
  return null;
}"""

# Puts the answer where the page's own script looks for it, then lets the page carry on.
INJECT_JS = r"""([kind, token, callback]) => {
  const fill = (sel) => document.querySelectorAll(sel).forEach((e) => { e.value = token; if (e.tagName === 'TEXTAREA') e.innerHTML = token; });
  let anchor = null;
  if (kind === 'recaptcha') fill('textarea[name="g-recaptcha-response"], #g-recaptcha-response');
  if (kind === 'hcaptcha') fill('textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]');
  if (kind === 'turnstile') fill('input[name="cf-turnstile-response"]');
  if (kind === 'image') { anchor = document.querySelector('#captchacharacters, input[name*="captcha" i][type="text"]'); if (anchor) anchor.value = token; }
  if (callback && typeof window[callback] === 'function') { try { window[callback](token); return 'callback'; } catch (e) {} }
  anchor = anchor || document.querySelector('textarea[name$="captcha-response"], input[name="cf-turnstile-response"]');
  const form = anchor && anchor.closest('form');
  if (form) { (form.requestSubmit ? form.requestSubmit() : form.submit()); return 'submitted'; }
  return 'filled';
}"""


def task_for(service: str, found: dict, url: str, image_b64: str = "") -> dict | None:
    kind = found.get("kind")
    names = TASKS.get(kind or "")
    if not names:
        return None
    t = names.get(service, names["*"])
    if not t:
        return None
    if kind == "image":
        return {"type": t, "body": image_b64} if image_b64 else None
    return {"type": t, "websiteURL": url, "websiteKey": found.get("sitekey", "")}


def answer_from(solution: dict) -> str:
    for k in ("gRecaptchaResponse", "token", "text"):
        v = solution.get(k) if isinstance(solution, dict) else None
        if v:
            return str(v)
    return ""


class Solver:
    def __init__(self, raw: dict, data_dir: str, log, tracker=None):
        self.raw = raw
        self.path = os.path.join(data_dir, FILE)
        self.log = log
        self.tracker = tracker
        self.lock = threading.Lock()
        self.data = read_json(self.path, {}) or {}
        self.http = requests.Session()

    def attach(self, raw: dict) -> None:
        self.raw = raw

    @property
    def cfg(self) -> dict:
        c = self.raw.get("captcha") if isinstance(self.raw, dict) else None
        return c if isinstance(c, dict) else {}

    @property
    def service(self) -> str:
        s = str(self.cfg.get("service") or "").lower().replace("-", "").replace(" ", "")
        return s if s in SERVICES and str(self.cfg.get("api_key") or "").strip() else ""

    def allowed(self, site: str) -> tuple[bool, str]:
        if not self.service:
            return False, "no CAPTCHA service is set up"
        only = [str(s).lower().removeprefix("www.") for s in self.cfg.get("stores") or [] if str(s).strip()]
        site = site.lower().removeprefix("www.")
        if only and not any(site == s or site.endswith("." + s) for s in only):
            return False, "not switched on for this site"
        if self._used_today() >= int(self.cfg.get("max_per_day") or DEFAULT_PER_DAY):
            return False, "today's CAPTCHA budget is used up"
        return True, ""

    def _used_today(self) -> int:
        today = time.strftime("%Y-%m-%d")
        return int(self.data.get("used", 0)) if self.data.get("day") == today else 0

    def _count(self, site: str, ok: bool) -> None:
        today = time.strftime("%Y-%m-%d")
        with self.lock:
            if self.data.get("day") != today:
                self.data["day"], self.data["used"] = today, 0
            self.data["used"] = int(self.data.get("used", 0)) + 1
            st = self.data.setdefault("sites", {}).setdefault(site, {"tried": 0, "solved": 0})
            st["tried"] += 1
            st["solved"] += 1 if ok else 0
            try:
                atomic_write_json(self.path, self.data)
            except OSError:
                pass
        if self.tracker:
            self.tracker.record(f"captcha-{self.service}", site, ok, "" if ok else "captcha")

    # ---- the service ---------------------------------------------------------------------
    def solve(self, task: dict) -> str:
        """Send one task and wait for the answer. Raises on any problem."""
        base = SERVICES[self.service]
        key = str(self.cfg.get("api_key") or "").strip()
        r = self.http.post(f"{base}/createTask", json={"clientKey": key, "task": task}, timeout=30).json()
        if r.get("errorId"):
            raise RuntimeError(r.get("errorDescription") or r.get("errorCode") or "the service refused the task")
        if r.get("status") == "ready" and r.get("solution"):
            return answer_from(r["solution"])
        tid = r.get("taskId")
        if not tid:
            raise RuntimeError("the service gave no task number")
        end = time.time() + WAIT_S
        while time.time() < end:
            time.sleep(POLL_S)
            g = self.http.post(f"{base}/getTaskResult", json={"clientKey": key, "taskId": tid}, timeout=30).json()
            if g.get("errorId"):
                raise RuntimeError(g.get("errorDescription") or g.get("errorCode") or "the service could not solve it")
            if g.get("status") == "ready":
                ans = answer_from(g.get("solution") or {})
                if not ans:
                    raise RuntimeError("the service answered with nothing")
                return ans
        raise RuntimeError(f"no answer within {WAIT_S} s")

    def balance(self) -> str:
        if not self.service:
            return ""
        try:
            r = self.http.post(f"{SERVICES[self.service]}/getBalance",
                               json={"clientKey": str(self.cfg.get("api_key") or "").strip()}, timeout=20).json()
            return "" if r.get("errorId") else f"${float(r.get('balance') or 0):.2f}"
        except Exception:
            return ""

    # ---- in the page (runs on the browser's own thread) ---------------------------------------
    def attempt(self, page, site: str, url: str) -> bool:
        """Try to clear a CAPTCHA on this page. True when an answer was put in (the caller re-reads the page)."""
        ok, why = self.allowed(site)
        if not ok:
            return False
        try:
            found = page.evaluate(DETECT_JS)
        except Exception:
            found = None
        if not found:
            return False
        image = ""
        if found.get("kind") == "image":
            try:
                image = base64.b64encode(page.request.get(found["src"], timeout=20000).body()).decode()
            except Exception:
                image = ""
        task = task_for(self.service, found, page.url or url, image)
        if not task:
            self.log.info("%s: %s cannot answer this kind of CAPTCHA (%s)", site, NAMES[self.service], found.get("kind"))
            return False
        self.log.info("%s: sending a %s CAPTCHA to %s", site, found.get("kind"), NAMES[self.service])
        try:
            answer = self.solve(task)
            how = page.evaluate(INJECT_JS, [found.get("kind"), answer, found.get("callback") or ""])
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(4000)
            self.log.info("%s: %s answered the CAPTCHA (%s)", site, NAMES[self.service], how)
            return True
        except Exception as exc:
            self.log.info("%s: %s could not answer the CAPTCHA: %s", site, NAMES[self.service], str(exc)[:120])
            self._count(site, False)
            return False

    def outcome(self, site: str, cleared: bool) -> None:
        """After attempt() returned True: did the page actually let us through?"""
        self._count(site, cleared)

    def view(self) -> dict:
        today = self._used_today()
        return {"service": self.service, "name": NAMES.get(self.service, ""), "used_today": today,
                "max_per_day": int(self.cfg.get("max_per_day") or DEFAULT_PER_DAY),
                "sites": dict(self.data.get("sites") or {})}
