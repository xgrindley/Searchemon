"""Desktop window. Monitoring runs while the window is open and stops when it closes.

Tabs: Dashboard (what is happening), Discord (webhook, what gets posted, pings,
quiet hours), Areas (ZIP codes and radius), Stores (which stores, how often,
API keys, signing in to store accounts). Everything else lives in the full
control panel in the browser.
"""
from __future__ import annotations

import copy
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from .accounts import SIGN_IN
from .config import ALL_RETAILERS, DEFAULTS
from .engine import Monitor
from .geo import clean_zip, zip_place
from .models import StockResult
from .notify import DiscordNotifier
from .panel import PanelServer
from .util import clean_url, version_label

STORE_NAMES = {
    "target": "Target", "bestbuy": "Best Buy", "kroger": "Kroger family", "walmart": "Walmart",
    "pokemoncenter": "Pokemon Center", "gamestop": "GameStop", "costco": "Costco", "samsclub": "Sam's Club",
    "barnesandnoble": "Barnes & Noble", "booksamillion": "Books-A-Million", "amazon": "Amazon",
    "dicks": "Dick's Sporting Goods", "safeway": "Safeway / Albertsons", "raleys": "Raley's",
    "walgreens": "Walgreens", "cvs": "CVS", "web": "Other sites (your links)",
}
# Stores checked through web pages, where a signed-in browser helps. Target,
# Best Buy and Kroger are checked through data feeds that ignore sign-in.
SPEEDS = [("30 sec", 30), ("1 min", 60), ("90 sec", 90), ("2 min", 120), ("3 min", 180), ("4 min", 240),
          ("5 min", 300), ("10 min", 600), ("15 min", 900), ("30 min", 1800), ("1 hour", 3600)]
TOLERANCES = ["Default", "0%", "5%", "10%", "15%", "20%", "25%", "30%", "40%", "50%", "75%", "100%"]
SLOWEST_FIRST = {"pokemoncenter": 900}   # stores that ban fast checkers
HOURS = [f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}" for h in range(24)]
WEBHOOK_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                    "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")


def speed_label(seconds: int) -> str:
    best = min(SPEEDS, key=lambda s: (abs(s[1] - int(seconds or 0)), -s[1]))  # ties round slower
    return best[0]


def speed_seconds(label: str) -> int:
    return dict(SPEEDS).get(label, 300)


def hour_to_text(value: str) -> str:
    try:
        return HOURS[int(str(value).split(":")[0]) % 24]
    except (ValueError, IndexError):
        return HOURS[22]


def text_to_hour(text: str) -> str:
    return f"{HOURS.index(text) if text in HOURS else 22}:00"


class ScrollFrame(ttk.Frame):
    """A frame whose content scrolls with the mouse wheel."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(16, 12))
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class App:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.events: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.title(("Pokemon Restock Monitor  " + version_label()).strip())
        self.root.geometry("1120x720")
        self.root.minsize(860, 520)
        self.rows: dict[str, str] = {}
        self.urls: dict[str, str] = {}
        self.dirty = False
        try:
            self.monitor = Monitor(config_path, self.events)
        except Exception as exc:
            messagebox.showerror("Config problem", f"Could not load {config_path}:\n\n{exc}")
            self.root.destroy()
            raise SystemExit(1)
        self._style()
        self._build()
        self.panel = None
        if (self.monitor.cfg.raw.get("control_panel") or {}).get("enabled", True):
            self.panel = PanelServer(self.monitor)
            if not self.panel.start():
                self.panel = None
        self._fill_retailers()
        self._load_settings_into_tabs()
        self._update_setup_banner()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        from .shutdown import install as _install_exit
        _install_exit(self.monitor.close, self.monitor.log)
        self.root.after(250, self.pump)
        self.start()
        if not self._has_webhook():
            self.tabs.select(self.tab_discord)

    # ---- helpers ----------------------------------------------------------------
    @property
    def raw(self) -> dict:
        return self.monitor.cfg.raw

    def _has_webhook(self) -> bool:
        return (any(v for v in ((self.raw.get("discord") or {}).get("webhooks") or {}).values())
                or any(a.get("webhook") for a in (self.raw.get("areas") or []) if isinstance(a, dict)))

    def _style(self) -> None:
        from tkinter import font as tkfont
        have = set(tkfont.families())
        ui = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Calibri", "Helvetica") if f in have), "TkDefaultFont")
        head = next((f for f in ("Segoe UI Variable Display", "Segoe UI Semibold", ui) if f in have), ui)
        self.mono = next((f for f in ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New") if f in have), "TkFixedFont")
        for name, size in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10), ("TkHeadingFont", 10)):
            try:
                tkfont.nametofont(name).configure(family=ui, size=size)
            except tk.TclError:
                pass
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        ink, muted, accent = "#1f1b3a", "#5b5778", "#6d4fd6"
        style.configure("Treeview", rowheight=28, font=(ui, 10))
        style.configure("Treeview.Heading", font=(ui, 9, "bold"), padding=(6, 5))
        style.configure("TNotebook.Tab", padding=(14, 7), font=(ui, 10))
        style.configure("TButton", padding=(10, 5))
        style.configure("H.TLabel", font=(head, 13, "bold"), foreground=ink)
        style.configure("Sub.TLabel", foreground=muted, font=(ui, 9))
        style.configure("State.TLabel", font=(head, 12, "bold"), foreground=accent)
        style.configure("Banner.TFrame", background="#fff4ce")
        style.configure("Banner.TLabel", background="#fff4ce", font=(ui, 10))
        style.configure("Accent.TButton", font=(ui, 10, "bold"), padding=(14, 6))

    def _section(self, parent, title: str, hint: str = "") -> ttk.Frame:
        ttk.Label(parent, text=title, style="H.TLabel").pack(anchor="w", pady=(14, 2))
        if hint:
            ttk.Label(parent, text=hint, style="Sub.TLabel", wraplength=820, justify="left").pack(anchor="w")
        box = ttk.Frame(parent)
        box.pack(fill="x", pady=(6, 0))
        return box

    def _check(self, parent, text: str, var: tk.Variable) -> ttk.Checkbutton:
        cb = ttk.Checkbutton(parent, text=text, variable=var, command=self.touch)
        cb.pack(anchor="w", pady=1)
        return cb

    def _entry(self, parent, label: str, var: tk.StringVar, width: int = 60, show: str = "",
               label_width: int = 22) -> ttk.Entry:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=label_width).pack(side="left")
        ent = ttk.Entry(row, textvariable=var, width=width, show=show)
        ent.pack(side="left")
        var.trace_add("write", lambda *_: self.touch())
        return ent

    def _save_bar(self, parent) -> None:
        bar = ttk.Frame(parent, padding=(16, 8))
        bar.pack(side="bottom", fill="x")
        ttk.Separator(parent).pack(side="bottom", fill="x")
        btn = ttk.Button(bar, text="Save changes", style="Accent.TButton", command=self.save_all)
        btn.pack(side="right")
        self.save_buttons.append(btn)
        ttk.Button(bar, text="Undo changes", command=self._load_settings_into_tabs).pack(side="right", padx=6)
        lbl = ttk.Label(bar, textvariable=self.save_state, style="Sub.TLabel")
        lbl.pack(side="left")

    def touch(self) -> None:
        if not getattr(self, "_loading", False):
            self.dirty = True
            self.save_state.set("Unsaved changes. Press Save changes to apply them.")

    # ---- layout -------------------------------------------------------------------
    def _build(self) -> None:
        self.save_state = tk.StringVar(value="")
        self.save_buttons: list = []
        bar = ttk.Frame(self.root, padding=(12, 8))
        bar.pack(fill="x")
        self.state_var = tk.StringVar(value="Starting...")
        ttk.Label(bar, textvariable=self.state_var, style="State.TLabel").pack(side="left")
        more = ttk.Menubutton(bar, text="More")
        menu = tk.Menu(more, tearoff=False)
        menu.add_command(label="Full control panel (products, filters, searches)", command=self.open_panel)
        menu.add_command(label="Search stores for Pokemon products now", command=self.rediscover)
        menu.add_command(label="Show the checking browser", command=lambda: self.monitor.show_browser())
        menu.add_command(label="Block tracker (checks before a store blocks)", command=self.show_tracker)
        menu.add_command(label="Browser cleanup (Reset profile, in Stores & speed)",
                         command=lambda: self.tabs.select(self.tab_stores))
        menu.add_separator()
        menu.add_command(label="Reload settings from file", command=self.reload)
        menu.add_command(label="Edit settings file (advanced)", command=self.edit_config)
        more["menu"] = menu
        more.pack(side="right", padx=3)
        ttk.Button(bar, text="Control panel", command=self.open_panel).pack(side="right", padx=3)
        self.pause_btn = ttk.Button(bar, text="Pause alerts", command=self.toggle_pause)
        self.pause_btn.pack(side="right", padx=3)
        ttk.Button(bar, text="Check now", command=self.check_now).pack(side="right", padx=3)
        self.run_btn = ttk.Button(bar, text="Stop", command=self.toggle_run)
        self.run_btn.pack(side="right", padx=3)

        self.banner = ttk.Frame(self.root, style="Banner.TFrame", padding=(12, 8))
        self.banner_text = tk.StringVar()
        ttk.Label(self.banner, textvariable=self.banner_text, style="Banner.TLabel").pack(side="left")
        self.banner_btns = ttk.Frame(self.banner, style="Banner.TFrame")
        self.banner_btns.pack(side="right")

        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tab_dash = ttk.Frame(self.tabs)
        self.tab_discord = ttk.Frame(self.tabs)
        self.tab_areas = ttk.Frame(self.tabs)
        self.tab_stores = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_dash, text="  Dashboard  ")
        self.tabs.add(self.tab_discord, text="  Discord & alerts  ")
        self.tabs.add(self.tab_areas, text="  Your area  ")
        self.tabs.add(self.tab_stores, text="  Stores & speed  ")
        self._build_dashboard(self.tab_dash)
        self._build_discord(self.tab_discord)
        self._build_areas(self.tab_areas)
        self._build_stores(self.tab_stores)

    def _build_dashboard(self, tab) -> None:
        panes = ttk.PanedWindow(tab, orient="vertical")
        panes.pack(fill="both", expand=True, padx=6, pady=6)
        top = ttk.Frame(panes)
        self.retail_list = ttk.Treeview(top, columns=("retailer", "status"), show="headings", height=6)
        self.retail_list.heading("retailer", text="Store")
        self.retail_list.heading("status", text="Last check")
        self.retail_list.column("retailer", width=170, stretch=False)
        self.retail_list.pack(fill="x", pady=(0, 6))
        cols = ("retailer", "title", "status", "price", "source", "checked")
        self.table = ttk.Treeview(top, columns=cols, show="headings")
        for col, label, width in (("retailer", "Store", 110), ("title", "Product", 380),
                                  ("status", "Stock", 220), ("price", "Price", 80),
                                  ("source", "Matched", 170), ("checked", "Checked", 80)):
            self.table.heading(col, text=label)
            self.table.column(col, width=width, stretch=col == "title")
        self.table.tag_configure("instock", background="#d4f5e2", foreground="#0b5a2b")
        self.table.tag_configure("ignored", foreground="#8a8a8a")
        self.table.bind("<Double-1>", self.open_selected)
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        panes.add(top, weight=3)
        bottom = ttk.Frame(panes)
        ttk.Label(bottom, text="Activity (double-click a product to open it)").pack(anchor="w")
        self.log = tk.Text(bottom, height=10, wrap="word", font=(self.mono, 9), state="disabled", padx=8, pady=6, relief="flat", borderwidth=1)
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("alert", foreground="#0a7a32", font=(self.mono, 9, "bold"))
        panes.add(bottom, weight=1)

    def _build_discord(self, tab) -> None:
        self._save_bar(tab)
        page = ScrollFrame(tab)
        page.pack(fill="both", expand=True)
        p = page.inner
        self.v = {}
        v = self.v

        box = self._section(p, "Connect your Discord channel",
                            "In Discord: open your server, Server Settings > Integrations > Webhooks > New Webhook, "
                            "pick your restock channel, then Copy Webhook URL and paste it here.")
        v["webhook"] = tk.StringVar()
        row = ttk.Frame(box)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Webhook URL", width=22).pack(side="left")
        self.hook_entry = ttk.Entry(row, textvariable=v["webhook"], width=70, show="*")
        self.hook_entry.pack(side="left")
        v["webhook"].trace_add("write", lambda *_: self.touch())
        ttk.Button(row, text="Paste", command=self.paste_webhook).pack(side="left", padx=4)
        v["show_hook"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Show", variable=v["show_hook"],
                        command=lambda: self.hook_entry.configure(show="" if v["show_hook"].get() else "*")
                        ).pack(side="left")
        row2 = ttk.Frame(box)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="", width=22).pack(side="left")
        ttk.Button(row2, text="Send test message", command=self.test_discord).pack(side="left")
        self.test_result = tk.StringVar()
        ttk.Label(row2, textvariable=self.test_result, style="Sub.TLabel").pack(side="left", padx=10)
        v["username"] = tk.StringVar()
        self._entry(box, "Name shown in Discord", v["username"], width=30)

        box = self._section(p, "Separate channels (optional)",
                            "Leave these blank to use the main webhook above. Online restocks go to the Online "
                            "channel, shelf stock near you goes to the In-store channel, and each area on the "
                            "Your area tab can have its own channel too. Anything with no match uses the main one.")
        v["webhook_online"] = tk.StringVar()
        v["webhook_in_store"] = tk.StringVar()
        for key, label in (("webhook_online", "Online restocks"), ("webhook_in_store", "In-store stock")):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=22).pack(side="left")
            ttk.Entry(row, textvariable=v[key], width=70, show="*").pack(side="left")
            v[key].trace_add("write", lambda *_: self.touch())

        box = self._section(p, "Who gets pinged",
                            "Optional. To copy an ID: Discord Settings > Advanced > turn on Developer Mode, "
                            "then right-click the role or your name and choose Copy ID.")
        v["role"] = tk.StringVar()
        v["user"] = tk.StringVar()
        self._entry(box, "Role ID to ping", v["role"], width=30)
        self._entry(box, "Your user ID to ping", v["user"], width=30)
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="Ping for", width=22).pack(side="left")
        for key, label in (("restock", "Restocks"), ("queue", "Pokemon Center queue"), ("new_listing", "New listings")):
            v["ping_" + key] = tk.BooleanVar()
            ttk.Checkbutton(row, text=label, variable=v["ping_" + key], command=self.touch).pack(side="left", padx=(0, 14))

        box = self._section(p, "What gets posted")
        for key, label in (("online", "Online restocks"),
                           ("in_store", "In-store restocks at stores in your area"),
                           ("pickup_only", "In-store only when order pickup is available (fewer wasted trips)"),
                           ("new_listings", "New listings (a store lists a product for the first time)"),
                           ("queue", "Pokemon Center queue opening (a drop is starting)"),
                           ("sold_out", "Sold out notices"),
                           ("human_check", "A store needs me to finish a bot check in the browser"),
                           ("toast", "Also show Windows pop-up notifications")):
            v["n_" + key] = tk.BooleanVar()
            self._check(box, label, v["n_" + key])

        box = self._section(p, "Which stores can alert", "Untick a store to keep checking it without posting its alerts.")
        grid = ttk.Frame(box)
        grid.pack(fill="x")
        v["alert_stores"] = {}
        for i, name in enumerate(ALL_RETAILERS):
            var = tk.BooleanVar(value=True)
            v["alert_stores"][name] = var
            ttk.Checkbutton(grid, text=STORE_NAMES.get(name, name), variable=var, command=self.touch
                            ).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 30), pady=1)

        box = self._section(p, "Quiet hours", "For example overnight, so pings don't wake anyone.")
        v["quiet_on"] = tk.BooleanVar()
        self._check(box, "Use quiet hours", v["quiet_on"])
        row = ttk.Frame(box)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="From", width=22).pack(side="left")
        v["quiet_start"] = tk.StringVar()
        v["quiet_end"] = tk.StringVar()
        cb = ttk.Combobox(row, values=HOURS, textvariable=v["quiet_start"], width=10, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.touch())
        ttk.Label(row, text="  to  ").pack(side="left")
        cb = ttk.Combobox(row, values=HOURS, textvariable=v["quiet_end"], width=10, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.touch())
        row = ttk.Frame(box)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="During quiet hours", width=22).pack(side="left")
        v["quiet_mode"] = tk.StringVar()
        for val, label in (("no_ping", "Post without pinging"), ("skip", "Don't post")):
            ttk.Radiobutton(row, text=label, value=val, variable=v["quiet_mode"], command=self.touch).pack(side="left", padx=(0, 14))

    def _build_areas(self, tab) -> None:
        self._save_bar(tab)
        page = ScrollFrame(tab)
        page.pack(fill="both", expand=True)
        p = page.inner
        box = self._section(p, "Where you shop",
                            "Stores inside any of these circles are checked for shelf stock and can alert. "
                            "Add home, work, or anywhere you drive past. Distance is straight-line miles from the ZIP's center.")
        self.area_list = ttk.Treeview(box, columns=("name", "zip", "town", "radius", "channel", "hook"),
                                      displaycolumns=("name", "zip", "town", "radius", "channel"),
                                      show="headings", height=6)
        for col, label, width in (("name", "Name", 160), ("zip", "ZIP", 90), ("town", "Town", 200),
                                  ("radius", "Radius", 90), ("channel", "Discord channel", 130)):
            self.area_list.heading(col, text=label)
            self.area_list.column(col, width=width, stretch=False)
        self.area_list.pack(anchor="w")
        self.area_list.bind("<<TreeviewSelect>>", self._area_selected)

        form = self._section(p, "Add or change an area", "Select an area above to change it, or fill this in to add a new one.")
        self.a_name = tk.StringVar(value="Home")
        self.a_zip = tk.StringVar()
        self.a_radius = tk.DoubleVar(value=15)
        self.a_town = tk.StringVar()
        self.a_hook = tk.StringVar()
        row = ttk.Frame(form)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Name", width=22).pack(side="left")
        ttk.Entry(row, textvariable=self.a_name, width=24).pack(side="left")
        row = ttk.Frame(form)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="ZIP code", width=22).pack(side="left")
        ttk.Entry(row, textvariable=self.a_zip, width=10).pack(side="left")
        ttk.Label(row, textvariable=self.a_town, style="Sub.TLabel").pack(side="left", padx=10)
        self.a_zip.trace_add("write", lambda *_: self.a_town.set(zip_place(clean_zip(self.a_zip.get()))
                                                                  if len(clean_zip(self.a_zip.get())) == 5 else ""))
        row = ttk.Frame(form)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Radius", width=22).pack(side="left")
        self.a_radius_text = tk.StringVar(value="15 miles")
        ttk.Scale(row, from_=1, to=100, orient="horizontal", length=320,
                  command=lambda val: self.a_radius_text.set(f"{int(round(float(val)))} miles"),
                  variable=self.a_radius).pack(side="left")
        ttk.Label(row, textvariable=self.a_radius_text, width=10).pack(side="left", padx=8)
        row = ttk.Frame(form)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Own Discord webhook", width=22).pack(side="left")
        ttk.Entry(row, textvariable=self.a_hook, width=60, show="*").pack(side="left")
        ttk.Label(row, text="(optional)", style="Sub.TLabel").pack(side="left", padx=8)
        row = ttk.Frame(form)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="", width=22).pack(side="left")
        ttk.Button(row, text="Add area", command=self.area_add).pack(side="left")
        ttk.Button(row, text="Update selected", command=self.area_update).pack(side="left", padx=6)
        ttk.Button(row, text="Remove selected", command=self.area_remove).pack(side="left")

        box = self._section(p, "Shelf checks")
        self.v["in_store"] = tk.BooleanVar()
        self._check(box, "Check shelf stock at stores in my areas (Target, Best Buy, Kroger)", self.v["in_store"])

    def _build_stores(self, tab) -> None:
        self._save_bar(tab)
        page = ScrollFrame(tab)
        page.pack(fill="both", expand=True)
        p = page.inner
        box = self._section(p, "Stores and how often each is checked",
                            "Faster checks catch restocks sooner but make bot checks and blocks more likely. "
                            "Pokemon Center bans fast checkers, so keep it at 15 minutes or slower.")
        presets = ttk.Frame(box)
        presets.pack(fill="x", pady=(0, 8))
        ttk.Label(presets, text="Quick set:").pack(side="left")
        for label, factor in (("Gentle", 2.0), ("Balanced", 1.0), ("Fast", 0.5)):
            ttk.Button(presets, text=label, command=lambda f=factor: self.preset(f)).pack(side="left", padx=4)
        grid = ttk.Frame(box)
        grid.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Default allowance over MSRP").pack(side="left")
        self.v["tol_default"] = tk.StringVar()
        cb = ttk.Combobox(row, values=TOLERANCES[1:], textvariable=self.v["tol_default"], width=7, state="readonly")
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self.touch())
        ttk.Label(row, text="A store alerts only at or under MSRP plus this much. Set a store's own allowance in "
                            "the Over MSRP column, for example 20% for Target so its $59.99 Elite Trainer Boxes alert.",
                  style="Sub.TLabel", wraplength=560, justify="left").pack(side="left")
        for col, text in enumerate(("Check", "Store", "Every", "Over MSRP", "Status", "")):
            ttk.Label(grid, text=text, style="Sub.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 16), pady=(0, 4))
        self.store_vars: dict[str, tuple[tk.BooleanVar, tk.StringVar]] = {}
        self.store_status: dict[str, tk.StringVar] = {}
        self.store_tol: dict[str, tk.StringVar] = {}
        for i, name in enumerate(ALL_RETAILERS, start=1):
            on, speed, status = tk.BooleanVar(), tk.StringVar(), tk.StringVar(value="")
            self.store_vars[name] = (on, speed)
            self.store_status[name] = status
            ttk.Checkbutton(grid, variable=on, command=self.touch).grid(row=i, column=0, sticky="w")
            ttk.Label(grid, text=STORE_NAMES.get(name, name)).grid(row=i, column=1, sticky="w", padx=(0, 16), pady=2)
            cb = ttk.Combobox(grid, values=[s[0] for s in SPEEDS], textvariable=speed, width=9, state="readonly")
            cb.grid(row=i, column=2, sticky="w", padx=(0, 16))
            cb.bind("<<ComboboxSelected>>", lambda e: self.touch())
            tol = tk.StringVar(value="Default")
            self.store_tol[name] = tol
            cb = ttk.Combobox(grid, values=TOLERANCES, textvariable=tol, width=8, state="readonly")
            cb.grid(row=i, column=3, sticky="w", padx=(0, 16))
            cb.bind("<<ComboboxSelected>>", lambda e: self.touch())
            ttk.Label(grid, textvariable=status, style="Sub.TLabel", width=56).grid(row=i, column=4, sticky="w", padx=(0, 16))
            if name in SIGN_IN:
                ttk.Button(grid, text="Sign in", width=9,
                           command=lambda n=name: self.sign_in(n)).grid(row=i, column=5, sticky="w")

        box = self._section(p, "Fewer bot checks: sign in to your own store accounts",
                            "Stores trust a browser that is signed in to a real account with history more than an "
                            "anonymous one. Press Sign in next to a store, sign in to your own account in the window "
                            "that opens, then close nothing: the checking browser keeps those cookies for later checks. "
                            "For Walmart, also choose your store there so pickup shows for it. Target, Best Buy and "
                            "Kroger are checked through data feeds that don't use sign-in or show bot checks.")

        box = self._section(p, "Blocked by Akamai or PerimeterX? Clean up a checking browser",
                            "A store can remember a browser's cookies with a bad reputation and keep blocking it. "
                            "Clear bot-check cookies removes only those and keeps your sign-ins. Reset profile deletes "
                            "everything that browser saved (sign-ins too) and it starts fresh on the next check.")
        row = ttk.Frame(box)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Browser").pack(side="left")
        self.profile_var = tk.StringVar()
        self.profile_box = ttk.Combobox(row, textvariable=self.profile_var, width=24, state="readonly",
                                        postcommand=self._refresh_profiles)
        self.profile_box.pack(side="left", padx=8)
        ttk.Button(row, text="Clear bot-check cookies", command=self.profile_clear_bot).pack(side="left", padx=4)
        ttk.Button(row, text="Reset profile", command=self.profile_reset).pack(side="left", padx=4)
        self._refresh_profiles()

        box = self._section(p, "Free keys for more shelf checks")
        self.v["bestbuy_key"] = tk.StringVar()
        self.v["kroger_id"] = tk.StringVar()
        self.v["kroger_secret"] = tk.StringVar()
        self._entry(box, "Best Buy API key", self.v["bestbuy_key"], width=40, show="*", label_width=28)
        ttk.Label(box, text="Free at developer.bestbuy.com. Turns on Best Buy store checks.", style="Sub.TLabel").pack(anchor="w", padx=(200, 0))
        self._entry(box, "Kroger client ID", self.v["kroger_id"], width=40, label_width=28)
        self._entry(box, "Kroger client secret", self.v["kroger_secret"], width=40, show="*", label_width=28)
        ttk.Label(box, text="Free at developer.kroger.com (Products scope). Covers Kroger, Smith's, Fred Meyer and more.",
                  style="Sub.TLabel").pack(anchor="w", padx=(200, 0))
        for key in ("walgreens_key", "walmart_consumer", "walmart_keyfile", "walmart_keyver", "walmart_publisher"):
            self.v[key] = tk.StringVar()
        self._entry(box, "Walgreens API key", self.v["walgreens_key"], width=40, show="*", label_width=28)
        ttk.Label(box, text="Optional, from developer.walgreens.com. Adds exact Walgreens stores to Stores near you (no stock data).",
                  style="Sub.TLabel").pack(anchor="w", padx=(200, 0))
        self._entry(box, "Walmart.io Consumer ID", self.v["walmart_consumer"], width=40, label_width=28)
        self._entry(box, "Walmart.io private key file", self.v["walmart_keyfile"], width=80, label_width=28)
        self._entry(box, "Walmart.io key version", self.v["walmart_keyver"], width=10, label_width=28)
        self._entry(box, "Walmart.io publisher ID", self.v["walmart_publisher"], width=40, label_width=28)
        ttk.Label(box, text="From walmart.io (your app's Consumer ID, the .pem private key you made, and the key version, "
                            "usually 1). Publisher ID is optional. Walmart stock then comes from Walmart's own feed.",
                  style="Sub.TLabel", wraplength=760).pack(anchor="w", padx=(200, 0))

    # ---- settings <-> tabs ----------------------------------------------------------
    def _load_settings_into_tabs(self) -> None:
        self._loading = True
        raw, v = self.raw, self.v
        d = raw.get("discord") or {}
        from .rules import rules as notify_rules
        n = notify_rules(raw)
        s = raw.get("settings") or {}
        v["webhook"].set(((d.get("webhooks") or {}).get("default")) or "")
        v["webhook_online"].set(((d.get("webhooks") or {}).get("online")) or "")
        v["webhook_in_store"].set(((d.get("webhooks") or {}).get("in_store")) or "")
        v["username"].set(d.get("username") or "Restock Monitor")
        v["role"].set(str(d.get("mention_role_id") or ""))
        v["user"].set(str(d.get("mention_user_id") or ""))
        for key in ("restock", "queue", "new_listing"):
            v["ping_" + key].set(key in (n.get("ping_on") or []))
        v["n_online"].set(bool(n.get("online")))
        v["n_in_store"].set(bool(n.get("in_store")))
        v["n_pickup_only"].set(bool(n.get("pickup_only")))
        v["n_new_listings"].set(bool(n.get("new_listings")))
        v["n_queue"].set(bool(n.get("queue")))
        v["n_sold_out"].set(bool(s.get("notify_sold_out")))
        v["n_human_check"].set(bool((raw.get("browser") or {}).get("notify_discord")))
        v["n_toast"].set(bool(s.get("windows_toast", True)))
        allowed = n.get("retailers") or []
        for name, var in v["alert_stores"].items():
            var.set(not allowed or name in allowed)
        qh = (n.get("quiet_hours") or [])
        v["quiet_on"].set(bool(qh))
        first = qh[0] if qh else {"start": "22:00", "end": "7:00"}
        v["quiet_start"].set(hour_to_text(first.get("start", "22:00")))
        v["quiet_end"].set(hour_to_text(first.get("end", "7:00")))
        v["quiet_mode"].set(n.get("quiet_mode") or "no_ping")

        self.area_list.delete(*self.area_list.get_children())
        areas = raw.get("areas") or []
        if not areas and (raw.get("location") or {}).get("zip"):
            loc = raw["location"]
            areas = [{"name": "Home", "zip": loc.get("zip"), "radius_miles": loc.get("radius_miles", 25)}]
        for a in areas:
            if not clean_zip(a.get("zip")):
                continue
            z = clean_zip(a.get("zip"))
            hook = str(a.get("webhook") or "").strip()
            self.area_list.insert("", "end", values=(a.get("name") or "Area", z, zip_place(z),
                                                     f"{int(a.get('radius_miles') or 15)} miles",
                                                     "Own channel" if hook else "Main", hook))
        v["in_store"].set(bool(s.get("in_store", True)))

        rets = raw.get("retailers") or {}
        for name, (on, speed) in self.store_vars.items():
            r = rets.get(name) or DEFAULTS["retailers"].get(name, {})
            on.set(bool(r.get("enabled")))
            speed.set(speed_label(int(r.get("interval_seconds") or 300)))
            own = r.get("msrp_tolerance_pct")
            self.store_tol[name].set("Default" if own in (None, "") else f"{float(own):g}%")
        v["tol_default"].set(f"{float(s.get('msrp_tolerance_pct') or 0):g}%")
        v["bestbuy_key"].set((rets.get("bestbuy") or {}).get("api_key") or "")
        v["kroger_id"].set((rets.get("kroger") or {}).get("client_id") or "")
        v["kroger_secret"].set((rets.get("kroger") or {}).get("client_secret") or "")
        v["walgreens_key"].set((rets.get("walgreens") or {}).get("api_key") or "")
        wm = rets.get("walmart") or {}
        v["walmart_consumer"].set(wm.get("consumer_id") or "")
        v["walmart_keyfile"].set(wm.get("private_key_file") or "")
        v["walmart_keyver"].set(str(wm.get("key_version") or "1"))
        v["walmart_publisher"].set(wm.get("publisher_id") or "")
        self._loading = False
        self.dirty = False
        self.save_state.set("")

    def _areas_from_list(self) -> list[dict]:
        out = []
        for iid in self.area_list.get_children():
            name, z, _town, radius, _chan, hook = self.area_list.item(iid, "values")
            entry = {"name": name, "zip": str(z), "radius_miles": int(str(radius).split()[0])}
            if hook:
                entry["webhook"] = str(hook)
            out.append(entry)
        return out

    def _collect(self) -> dict:
        raw = copy.deepcopy(self.raw)
        v = self.v
        d = raw.setdefault("discord", {})
        hooks = dict(d.get("webhooks") or {})
        hooks["default"] = v["webhook"].get().strip()
        hooks["online"] = v["webhook_online"].get().strip()
        hooks["in_store"] = v["webhook_in_store"].get().strip()
        d["webhooks"] = hooks
        d["username"] = v["username"].get().strip() or "Restock Monitor"
        d["mention_role_id"] = "".join(ch for ch in v["role"].get() if ch.isdigit())
        d["mention_user_id"] = "".join(ch for ch in v["user"].get() if ch.isdigit())

        n = dict(raw.get("notify") or {})
        n["ping_on"] = [k for k in ("restock", "queue", "new_listing") if v["ping_" + k].get()]
        for key in ("online", "in_store", "pickup_only", "new_listings", "queue"):
            n[key] = bool(v["n_" + key].get())
        chosen = [name for name, var in v["alert_stores"].items() if var.get()]
        n["retailers"] = [] if len(chosen) == len(v["alert_stores"]) else chosen
        n["quiet_hours"] = ([{"days": "all", "start": text_to_hour(v["quiet_start"].get()),
                              "end": text_to_hour(v["quiet_end"].get())}] if v["quiet_on"].get() else [])
        n["quiet_mode"] = v["quiet_mode"].get() or "no_ping"
        raw["notify"] = n

        s = raw.setdefault("settings", {})
        s["notify_sold_out"] = bool(v["n_sold_out"].get())
        s["windows_toast"] = bool(v["n_toast"].get())
        s["in_store"] = bool(v["in_store"].get())
        try:
            s["msrp_tolerance_pct"] = float((v["tol_default"].get() or "5%").rstrip("%"))
        except ValueError:
            pass
        raw.setdefault("browser", {})["notify_discord"] = bool(v["n_human_check"].get())

        raw["areas"] = self._areas_from_list()
        if raw["areas"]:
            raw.setdefault("location", {})["zip"] = raw["areas"][0]["zip"]
            raw["location"]["radius_miles"] = raw["areas"][0]["radius_miles"]

        rets = raw.setdefault("retailers", {})
        for name, (on, speed) in self.store_vars.items():
            r = dict(rets.get(name) or DEFAULTS["retailers"].get(name, {}))
            r["enabled"] = bool(on.get())
            r["interval_seconds"] = speed_seconds(speed.get())
            tol = self.store_tol[name].get()
            if tol and tol != "Default":
                r["msrp_tolerance_pct"] = float(tol.rstrip("%"))
            else:
                r.pop("msrp_tolerance_pct", None)
            rets[name] = r
        rets["bestbuy"]["api_key"] = v["bestbuy_key"].get().strip()
        rets["kroger"]["client_id"] = v["kroger_id"].get().strip()
        rets["kroger"]["client_secret"] = v["kroger_secret"].get().strip()
        rets.setdefault("walgreens", {})["api_key"] = v["walgreens_key"].get().strip()
        wm = rets.setdefault("walmart", {})
        wm["consumer_id"] = v["walmart_consumer"].get().strip()
        wm["private_key_file"] = v["walmart_keyfile"].get().strip().strip('"')
        wm["key_version"] = v["walmart_keyver"].get().strip() or "1"
        wm["publisher_id"] = v["walmart_publisher"].get().strip()
        return raw

    def save_all(self) -> None:
        hook = self.v["webhook"].get().strip()
        if hook and not hook.startswith(WEBHOOK_PREFIXES):
            messagebox.showwarning("Webhook", "That doesn't look like a Discord webhook URL. It should start with "
                                              "https://discord.com/api/webhooks/")
            return
        rets = self.store_vars
        if rets["bestbuy"][0].get() and not self.v["bestbuy_key"].get().strip():
            if not messagebox.askyesno("Best Buy", "Best Buy needs a free API key to work. Save anyway?"):
                return
        raw = self._collect()
        self.save_state.set("Saving...")
        for b in self.save_buttons:
            b.state(["disabled"])

        def work():
            try:
                self.monitor.save_settings(raw)
                self.events.put(("saved", None))
            except Exception as exc:
                self.events.put(("save_failed", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    # ---- block tracker -----------------------------------------------------------------
    def show_tracker(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Block tracker")
        win.geometry("760x420")
        ttk.Label(win, text="How many checks each method gets through before a store blocks it. "
                            "Numbers keep growing across restarts.", wraplength=720).pack(anchor="w", padx=10, pady=8)
        text = tk.Text(win, font=(self.mono, 9), wrap="none")
        text.pack(fill="both", expand=True, padx=10)

        def refresh():
            tracker = self.monitor.tracker
            browser = self.monitor.browser
            body = tracker.report() if tracker else "Not running yet."
            rest = browser.resting() if browser else []
            if rest:
                body += "\n\nResting right now:\n" + "\n".join(
                    f"  {r['profile']} on {r['site']}: about {r['minutes']} min" for r in rest)
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", body)
            text.configure(state="disabled")
        refresh()
        ttk.Button(win, text="Refresh", command=refresh).pack(pady=8)

    # ---- area editing ----------------------------------------------------------------
    def _area_selected(self, _event=None) -> None:
        sel = self.area_list.selection()
        if sel:
            name, z, _t, radius, _chan, hook = self.area_list.item(sel[0], "values")
            self.a_hook.set(hook)
            self.a_name.set(name)
            self.a_zip.set(z)
            r = int(str(radius).split()[0])
            self.a_radius.set(r)
            self.a_radius_text.set(f"{r} miles")

    def _area_values(self):
        z = clean_zip(self.a_zip.get())
        if len(z) != 5:
            messagebox.showwarning("ZIP code", "Enter a 5-digit ZIP code.")
            return None
        r = max(1, min(100, int(round(self.a_radius.get()))))
        hook = self.a_hook.get().strip()
        if hook and not hook.startswith(WEBHOOK_PREFIXES):
            messagebox.showwarning("Webhook", "That doesn't look like a Discord webhook URL. It should start with "
                                              "https://discord.com/api/webhooks/")
            return None
        return (self.a_name.get().strip() or "Area", z, zip_place(z), f"{r} miles",
                "Own channel" if hook else "Main", hook)

    def area_add(self) -> None:
        vals = self._area_values()
        if vals:
            self.area_list.insert("", "end", values=vals)
            self.touch()

    def area_update(self) -> None:
        sel = self.area_list.selection()
        vals = self._area_values()
        if not sel:
            messagebox.showinfo("Areas", "Select an area in the list first, or use Add area.")
        elif vals:
            self.area_list.item(sel[0], values=vals)
            self.touch()

    def area_remove(self) -> None:
        for iid in self.area_list.selection():
            self.area_list.delete(iid)
            self.touch()

    # ---- actions ------------------------------------------------------------------
    def paste_webhook(self) -> None:
        try:
            self.v["webhook"].set(self.root.clipboard_get().strip())
        except tk.TclError:
            pass

    def preset(self, factor: float) -> None:
        for name, (_on, speed) in self.store_vars.items():
            base = int((DEFAULTS["retailers"].get(name) or {}).get("interval_seconds") or 300)
            secs = max(30, int(base * factor), SLOWEST_FIRST.get(name, 0))
            speed.set(speed_label(secs))
        self.touch()

    def _refresh_profiles(self) -> None:
        names = self.monitor.browser.names() if self.monitor.browser else []
        self.profile_box["values"] = names
        if names and self.profile_var.get() not in names:
            self.profile_var.set(names[0])

    def _profile_job(self, work, busy: str) -> None:
        self.write(busy)
        def run():
            try:
                work()                      # the result is posted to the Activity log by the monitor
            except Exception as exc:
                self.events.put(("log", f"Browser cleanup failed: {exc}"))
        threading.Thread(target=run, daemon=True).start()

    def profile_clear_bot(self) -> None:
        name = self.profile_var.get()
        if not name:
            messagebox.showinfo("No browser", "No checking browser is set up yet.")
            return
        if messagebox.askyesno("Clear bot-check cookies",
                               f"Delete the bot-check cookies (Akamai, PerimeterX, Cloudflare) in '{name}'?\n\n"
                               "Your store sign-ins are kept."):
            self._profile_job(lambda: self.monitor.profile_clear_bot(name), f"Clearing bot-check cookies in '{name}'...")

    def profile_reset(self) -> None:
        name = self.profile_var.get()
        if not name:
            messagebox.showinfo("No browser", "No checking browser is set up yet.")
            return
        if messagebox.askyesno("Reset profile",
                               f"Delete everything '{name}' saved (cookies, sign-ins, cache)?\n\n"
                               "You will need to sign in to your stores again. It starts fresh on the next check.",
                               icon="warning"):
            self._profile_job(lambda: self.monitor.profile_reset(name), f"Resetting '{name}'...")

    def sign_in(self, name: str) -> None:
        url = SIGN_IN[name]
        self.monitor.open_in_browser(url)
        self.write(f"Opened {STORE_NAMES[name]} in the checking browser. Sign in to your own account there"
                   + (" and choose your store." if name == "walmart" else "."))

    def toggle_run(self) -> None:
        if self.monitor.running:
            threading.Thread(target=self.monitor.stop, daemon=True).start()
            self.state_var.set("Stopping...")
        else:
            self.start()

    def toggle_pause(self) -> None:
        paused = not bool((self.raw.get("settings") or {}).get("alerts_paused"))
        threading.Thread(target=self.monitor.set_paused, args=(paused,), daemon=True).start()
        self.root.after(400, self._update_pause_btn)

    def _update_pause_btn(self) -> None:
        paused = bool((self.raw.get("settings") or {}).get("alerts_paused"))
        self.pause_btn.configure(text="Resume alerts" if paused else "Pause alerts")

    def _update_setup_banner(self) -> None:
        for w in self.banner_btns.winfo_children():
            w.destroy()
        todo = []
        if not self._has_webhook():
            todo.append(("Connect Discord", self.tab_discord))
        if not (self.raw.get("areas") or (self.raw.get("location") or {}).get("zip")):
            todo.append(("Set your area", self.tab_areas))
        if todo:
            self.banner_text.set("Finish setting up so alerts reach you:")
            for label, tab in todo:
                ttk.Button(self.banner_btns, text=label, command=lambda t=tab: self.tabs.select(t)).pack(side="left", padx=4)
            self.banner.pack(fill="x", padx=10, pady=(0, 6), before=self.tabs)
        else:
            self.banner.pack_forget()

    def start(self) -> None:
        self.monitor.start()
        self.state_var.set("Running")

    def rediscover(self) -> None:
        threading.Thread(target=self.monitor.rediscover, daemon=True).start()

    def check_now(self) -> None:
        self.monitor.check_now()
        self.write("Checking all stores now")

    def reload(self) -> None:
        def work():
            try:
                self.monitor.reload()
            except Exception as exc:
                self.events.put(("log", f"Reload failed: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def test_discord(self) -> None:
        hook = self.v["webhook"].get().strip()
        if not hook:
            self.test_result.set("Paste your webhook URL first.")
            return
        if not hook.startswith(WEBHOOK_PREFIXES):
            self.test_result.set("That doesn't look like a Discord webhook URL.")
            return
        self.test_result.set("Sending...")
        cfg = {"webhooks": {"default": hook}, "username": self.v["username"].get().strip() or "Restock Monitor"}

        def work():
            ok = DiscordNotifier(cfg, self.monitor.log).test().get("default")
            self.events.put(("test_result", "Sent. Check your Discord channel." if ok else
                             "Failed. Check the URL, or make a new webhook in Discord."))
        threading.Thread(target=work, daemon=True).start()

    def edit_config(self) -> None:
        path = os.path.abspath(self.config_path)
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])

    def open_panel(self) -> None:
        if self.panel:
            webbrowser.open(self.panel.url)
        else:
            messagebox.showinfo("Control panel", "The control panel is off or its port is in use.")

    def open_selected(self, _event=None) -> None:
        sel = self.table.selection()
        if sel and self.urls.get(sel[0]):
            webbrowser.open(clean_url(self.urls[sel[0]]))

    def on_close(self) -> None:
        if self.dirty and messagebox.askyesno("Unsaved changes", "Save your changes before closing?"):
            raw = self._collect()
            try:
                self.monitor.stop()
                from .config import save_config
                save_config(self.config_path, raw, backup_dir=self.monitor.cfg.data_dir)
            except Exception as exc:
                messagebox.showerror("Not saved", str(exc))
        self.state_var.set("Stopping...")
        self.root.update_idletasks()
        self.monitor.close()
        if self.panel:
            self.panel.stop()
        self.root.destroy()

    # ---- event pump (UI thread only) -----------------------------------------------
    def _fill_retailers(self) -> None:
        self.retail_list.delete(*self.retail_list.get_children())
        for name, r in self.monitor.retailers.items():
            self.retail_list.insert("", "end", iid=name, values=(r.display, "Waiting"))
        for name, status in self.store_status.items():
            status.set("Waiting for first check" if name in self.monitor.retailers else "Off")

    def write(self, msg: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n", tag or ())
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 1500:
            self.log.delete("1.0", f"{lines - 1500}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_result(self, res: StockResult) -> None:
        status = res.note or res.status_text()
        if res.stores and not res.note:
            status = f"{status} (nearest: {res.stores[0].label()})"
        values = (res.retailer_name, res.title, status,
                  f"${res.price:.2f}" if res.price else "", res.watch_name or res.source,
                  time.strftime("%H:%M:%S"))
        tag = ("ignored",) if res.note.startswith("ignored") else (("instock",) if res.in_stock else ())
        iid = self.rows.get(res.key)
        if iid and self.table.exists(iid):
            self.table.item(iid, values=values, tags=tag)
        else:
            iid = self.table.insert("", "end", values=values, tags=tag)
            self.rows[res.key] = iid
        self.urls[iid] = res.url

    def pump(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self.write(event[1])
                elif kind == "result":
                    self.show_result(event[1])
                elif kind == "status":
                    r = self.monitor.retailers.get(event[1])
                    if self.retail_list.exists(event[1]):
                        self.retail_list.item(event[1], values=(r.display if r else event[1], event[2]))
                    if event[1] in self.store_status:
                        self.store_status[event[1]].set(str(event[2])[:80])
                elif kind == "alert":
                    res, reason, sent = event[1], event[2], event[3]
                    self.write(f"IN STOCK  {res.retailer_name}: {res.title} | {reason}"
                               f"{'' if sent else ' (Discord not sent)'}", "alert")
                    self.root.bell()
                elif kind == "human_check":
                    self.write(f"{event[1]} wants a quick human check. Finish it in the browser window "
                               "that opened, then checks continue on their own.", "alert")
                    self.root.bell()
                elif kind == "reloaded":
                    self.table.delete(*self.table.get_children())
                    self.rows.clear()
                    self.urls.clear()
                    self._fill_retailers()
                    self._update_setup_banner()
                    self._update_pause_btn()
                elif kind in ("saved", "save_failed"):
                    for b in self.save_buttons:
                        b.state(["!disabled"])
                if kind == "saved":
                    self.dirty = False
                    self.save_state.set(f"Saved at {time.strftime('%I:%M %p').lstrip('0')}. Checks restarted with the new settings.")
                elif kind == "save_failed":
                    self.save_state.set("Not saved.")
                    messagebox.showerror("Not saved", event[1])
                elif kind == "test_result":
                    self.test_result.set(event[1])
        except queue.Empty:
            pass
        running = self.monitor.running
        paused = bool((self.raw.get("settings") or {}).get("alerts_paused"))
        self.state_var.set(("Running" + (", alerts paused" if paused else "")) if running else "Stopped")
        self.run_btn.configure(text="Stop" if running else "Start")
        self.root.after(300, self.pump)

    def run(self) -> None:
        self.root.mainloop()


def run_gui(config_path: str) -> None:
    App(config_path).run()
