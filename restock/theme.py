"""Colors for the desktop window: a dark theme that matches the control panel's deep violet look, a light
theme, and "match Windows". The palettes are plain data (checked for readable contrast in tests); apply() and
recolor() paint them onto tkinter's ttk and classic widgets. tkinter is imported only when drawing."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str          # window ground
    surface: str     # fields, tables, the log
    raised: str      # buttons, selected tab, table headings
    hover: str       # button under the pointer
    line: str        # borders
    ink: str         # main text
    muted: str       # secondary text
    faint: str       # disabled or tertiary text
    accent: str      # actions, focus
    accent_ink: str  # text on the accent color
    accent2: str     # the far end of the accent gradient
    select: str      # selected row or text
    ok: str          # text for "in stock"
    ok_bg: str       # an in-stock row
    warn: str
    warn_bg: str     # the setup banner
    bad: str


DARK = Palette("dark", bg="#0b0820", surface="#15112e", raised="#211c44", hover="#2c2658", line="#342e63",
               ink="#ece8ff", muted="#b9b0ec", faint="#8d86bf", accent="#a78bfa", accent_ink="#0b0820",
               accent2="#22d3ee", select="#3b3180", ok="#67e8f9", ok_bg="#0e3342", warn="#fcd34d", warn_bg="#3b3213",
               bad="#fda4af")
LIGHT = Palette("light", bg="#f5f3ff", surface="#ffffff", raised="#ece7fd", hover="#e0d8fb", line="#d4cbf1",
                ink="#1f1b3a", muted="#55517a", faint="#7b7699", accent="#6d4fd6", accent_ink="#ffffff",
                accent2="#0891b2", select="#d9cffc", ok="#0b6b4a", ok_bg="#d4f5e2", warn="#7a5a00", warn_bg="#fff4ce",
                bad="#b4233c")
PALETTES = {"dark": DARK, "light": LIGHT}
MODES = ("dark", "light", "system")


def windows_prefers_light() -> bool:
    """True when Windows is set to light app mode. Any trouble reading the setting means dark."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except Exception:
        return False


def palette_for(mode: str) -> Palette:
    if mode == "system":
        return LIGHT if windows_prefers_light() else DARK
    return PALETTES.get(mode, DARK)


def load_mode(data_dir: str) -> str:
    try:
        with open(os.path.join(data_dir, "gui-theme.txt"), encoding="utf-8") as fh:
            mode = fh.read().strip().lower()
        return mode if mode in MODES else "dark"
    except OSError:
        return "dark"


def save_mode(data_dir: str, mode: str) -> None:
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "gui-theme.txt"), "w", encoding="utf-8") as fh:
            fh.write(mode if mode in MODES else "dark")
    except OSError:
        pass


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two #rrggbb colors."""
    def lum(c: str) -> float:
        r, g, b_ = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b_)
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """The color t of the way from a to b (0 = a, 1 = b)."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


def apply(root, style, p: Palette, ui: str, head: str) -> None:
    """Paint the ttk styles. Call recolor() afterwards for the classic widgets (canvas, text, menu)."""
    if "clam" in style.theme_names():
        style.theme_use("clam")          # the one built-in theme that honors custom colors everywhere
    root.configure(background=p.bg)
    root.option_add("*TCombobox*Listbox.background", p.surface)
    root.option_add("*TCombobox*Listbox.foreground", p.ink)
    root.option_add("*TCombobox*Listbox.selectBackground", p.select)
    root.option_add("*TCombobox*Listbox.selectForeground", p.ink)
    root.option_add("*TCombobox*Listbox.font", (ui, 10))
    c = style.configure
    m = style.map
    c(".", background=p.bg, foreground=p.ink, fieldbackground=p.surface, bordercolor=p.line, lightcolor=p.bg,
      darkcolor=p.bg, troughcolor=p.surface, focuscolor=p.accent, selectbackground=p.select,
      selectforeground=p.ink, insertcolor=p.ink, font=(ui, 10))
    m(".", foreground=[("disabled", p.faint)])
    c("TFrame", background=p.bg)
    c("TLabel", background=p.bg, foreground=p.ink)
    c("TSeparator", background=p.line)
    c("H.TLabel", background=p.bg, foreground=p.ink, font=(head, 13, "bold"))
    c("Sub.TLabel", background=p.bg, foreground=p.muted, font=(ui, 9))
    c("State.TLabel", background=p.bg, foreground=p.accent, font=(head, 12, "bold"))
    c("Banner.TFrame", background=p.warn_bg)
    c("Banner.TLabel", background=p.warn_bg, foreground=p.warn, font=(ui, 10))

    c("TButton", background=p.raised, foreground=p.ink, bordercolor=p.line, lightcolor=p.raised, darkcolor=p.raised,
      focusthickness=1, focuscolor=p.accent, padding=(12, 6), relief="flat", borderwidth=1)
    m("TButton", background=[("pressed", p.line), ("active", p.hover)], bordercolor=[("focus", p.accent), ("active", p.muted)],
      lightcolor=[("active", p.hover)], darkcolor=[("active", p.hover)])
    c("Accent.TButton", background=p.accent, foreground=p.accent_ink, bordercolor=p.accent, lightcolor=p.accent,
      darkcolor=p.accent, font=(ui, 10, "bold"), padding=(16, 7))
    m("Accent.TButton", background=[("pressed", mix(p.accent, p.ink, .2)), ("active", mix(p.accent, p.ink, .12))],
      lightcolor=[("active", mix(p.accent, p.ink, .12))], darkcolor=[("active", mix(p.accent, p.ink, .12))])
    c("TMenubutton", background=p.raised, foreground=p.ink, bordercolor=p.line, arrowcolor=p.muted, padding=(12, 6))
    m("TMenubutton", background=[("active", p.hover)])

    for name in ("TCheckbutton", "TRadiobutton"):
        c(name, background=p.bg, foreground=p.ink, indicatorbackground=p.surface, indicatorforeground=p.accent_ink,
          indicatormargin=(0, 0, 6, 0), upperbordercolor=p.line, lowerbordercolor=p.line)
        m(name, background=[("active", p.bg)], indicatorbackground=[("selected", p.accent), ("pressed", p.hover)],
          foreground=[("disabled", p.faint)])
    c("TEntry", fieldbackground=p.surface, foreground=p.ink, bordercolor=p.line, lightcolor=p.surface,
      darkcolor=p.surface, insertcolor=p.ink, padding=(6, 4))
    m("TEntry", bordercolor=[("focus", p.accent)], lightcolor=[("focus", p.accent)], darkcolor=[("focus", p.accent)],
      fieldbackground=[("disabled", p.bg)])
    c("TCombobox", fieldbackground=p.surface, background=p.raised, foreground=p.ink, arrowcolor=p.muted,
      bordercolor=p.line, lightcolor=p.surface, darkcolor=p.surface, selectbackground=p.surface,
      selectforeground=p.ink, padding=(6, 4))
    m("TCombobox", fieldbackground=[("readonly", p.surface), ("disabled", p.bg)], foreground=[("readonly", p.ink)],
      background=[("active", p.hover)], bordercolor=[("focus", p.accent)], arrowcolor=[("active", p.ink)])
    c("TSpinbox", fieldbackground=p.surface, foreground=p.ink, bordercolor=p.line, arrowcolor=p.muted)
    c("Horizontal.TScale", background=p.bg, troughcolor=p.surface, bordercolor=p.line)

    c("TNotebook", background=p.bg, bordercolor=p.line, lightcolor=p.bg, darkcolor=p.bg, tabmargins=(2, 4, 2, 0))
    c("TNotebook.Tab", background=p.surface, foreground=p.muted, bordercolor=p.line, lightcolor=p.surface,
      darkcolor=p.surface, padding=(14, 7), font=(ui, 10))
    m("TNotebook.Tab", background=[("selected", p.raised), ("active", p.hover)],
      foreground=[("selected", p.ink), ("active", p.ink)], lightcolor=[("selected", p.accent)],
      bordercolor=[("selected", p.accent)])

    c("Treeview", background=p.surface, fieldbackground=p.surface, foreground=p.ink, bordercolor=p.line,
      lightcolor=p.surface, darkcolor=p.surface, rowheight=28, font=(ui, 10))
    m("Treeview", background=[("selected", p.select)], foreground=[("selected", p.ink)])
    c("Treeview.Heading", background=p.raised, foreground=p.muted, bordercolor=p.line, lightcolor=p.raised,
      darkcolor=p.raised, relief="flat", font=(ui, 9, "bold"), padding=(6, 5))
    m("Treeview.Heading", background=[("active", p.hover)], foreground=[("active", p.ink)])
    c("TScrollbar", background=p.raised, troughcolor=p.bg, bordercolor=p.bg, lightcolor=p.raised, darkcolor=p.raised,
      arrowcolor=p.muted, gripcount=0)
    m("TScrollbar", background=[("active", p.hover), ("pressed", p.line)])
    c("TPanedwindow", background=p.bg)
    c("Sash", sashthickness=6, background=p.line)
    c("TProgressbar", background=p.accent, troughcolor=p.surface, bordercolor=p.line)


def recolor(widget, p: Palette, mono: str) -> None:
    """Paint classic (non-ttk) widgets under `widget`: canvases, text boxes, menus, plain windows."""
    import tkinter as tk
    stack = [widget]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        try:
            if isinstance(w, GradientBar):
                w.set_colors(p.accent, p.accent2, p.bg)
            elif isinstance(w, tk.Canvas):
                w.configure(background=p.bg, highlightthickness=0)
            elif isinstance(w, tk.Text):
                w.configure(background=p.surface, foreground=p.ink, insertbackground=p.ink, selectbackground=p.select,
                            selectforeground=p.ink, highlightthickness=1, highlightbackground=p.line,
                            highlightcolor=p.accent, relief="flat")
                w.tag_configure("alert", foreground=p.ok, font=(mono, 9, "bold"))
            elif isinstance(w, tk.Menu):
                w.configure(background=p.surface, foreground=p.ink, activebackground=p.accent,
                            activeforeground=p.accent_ink, disabledforeground=p.faint, relief="flat", borderwidth=0)
            elif isinstance(w, (tk.Toplevel, tk.Tk)):
                w.configure(background=p.bg)
        except tk.TclError:
            pass


def gradient_bar_class():
    import tkinter as tk

    class _GradientBar(tk.Canvas):
        """A thin strip that fades from one color to another, echoing the control panel's accent line."""

        def __init__(self, parent, height: int = 3):
            super().__init__(parent, height=height, highlightthickness=0, borderwidth=0)
            self._a, self._b, self._bg = DARK.accent, DARK.accent2, DARK.bg
            self.bind("<Configure>", lambda e: self._draw())

        def set_colors(self, a: str, b: str, bg: str) -> None:
            self._a, self._b, self._bg = a, b, bg
            self.configure(background=bg)
            self._draw()

        def _draw(self) -> None:
            self.delete("all")
            width, height = max(self.winfo_width(), 2), int(self["height"])
            steps = min(width, 240)
            for i in range(steps):
                x0, x1 = i * width / steps, (i + 1) * width / steps + 1
                self.create_rectangle(x0, 0, x1, height, outline="", fill=mix(self._a, self._b, i / max(steps - 1, 1)))

    return _GradientBar


try:                                    # a real class so isinstance() works; absent only where tkinter is missing
    GradientBar = gradient_bar_class()
except Exception:                       # pragma: no cover
    class GradientBar:                  # type: ignore[no-redef]
        pass
