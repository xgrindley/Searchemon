"""The desktop window's colors: readable in both themes, saved between runs."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import theme  # noqa: E402


class ThemeTests(unittest.TestCase):
    def test_text_is_readable_on_every_surface_in_both_themes(self):
        for p in (theme.DARK, theme.LIGHT):
            for fg, bg, need in (
                (p.ink, p.bg, 7), (p.ink, p.surface, 7), (p.ink, p.raised, 7), (p.ink, p.select, 4.5),
                (p.muted, p.bg, 4.5), (p.muted, p.surface, 4.5), (p.muted, p.raised, 4.5),
                (p.faint, p.bg, 3), (p.accent_ink, p.accent, 4.5), (p.accent, p.bg, 3),
                (p.ok, p.ok_bg, 4.5), (p.warn, p.warn_bg, 4.5), (p.bad, p.surface, 4.5),
            ):
                self.assertGreaterEqual(theme.contrast(fg, bg), need, f"{p.name}: {fg} on {bg}")

    def test_dark_is_dark_and_light_is_light(self):
        self.assertGreater(theme.contrast(theme.DARK.ink, theme.DARK.bg), 10)
        self.assertLess(theme.contrast(theme.LIGHT.ink, theme.LIGHT.bg), 18)
        self.assertGreater(theme.contrast(theme.LIGHT.bg, theme.DARK.bg), 15)

    def test_mode_is_saved_and_bad_values_fall_back_to_dark(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(theme.load_mode(d), "dark")
            theme.save_mode(d, "light")
            self.assertEqual(theme.load_mode(d), "light")
            theme.save_mode(d, "nonsense")
            self.assertEqual(theme.load_mode(d), "dark")

    def test_gradient_mix_and_palette_lookup(self):
        self.assertEqual(theme.mix("#000000", "#ffffff", .5), "#808080")
        self.assertIs(theme.palette_for("light"), theme.LIGHT)
        self.assertIs(theme.palette_for("whatever"), theme.DARK)


if __name__ == "__main__":
    unittest.main()


class PaintTests(unittest.TestCase):
    def test_both_themes_paint_a_real_window(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
        except Exception as exc:              # no tkinter or no display (a headless server): nothing to paint
            self.skipTest(str(exc))
        try:
            canvas = tk.Canvas(root)
            canvas.pack()
            text = tk.Text(root)
            text.pack()
            ttk.Button(root, text="x").pack()
            bar = theme.GradientBar(root)
            bar.pack(fill="x")
            style = ttk.Style()
            for p in (theme.DARK, theme.LIGHT):
                theme.apply(root, style, p, "TkDefaultFont", "TkDefaultFont")
                theme.recolor(root, p, "TkFixedFont")
                root.update()
                self.assertEqual(str(canvas["background"]), p.bg)
                self.assertEqual(str(text["background"]), p.surface)
                self.assertEqual(style.lookup("TButton", "background"), p.raised)
        finally:
            root.destroy()


class PanelMapTests(unittest.TestCase):
    def test_areas_page_has_a_live_map_and_the_status_channel_fields(self):
        from restock.panel_page import PAGE
        for needle in ("function mapView(", "function drawAreaMap(", 'id: "area-map"', "Status channel (optional)",
                       "status_block_after"):
            self.assertIn(needle, PAGE)
        self.assertNotIn("openstreetmap.org/", PAGE.replace("OpenStreetMap search", ""))     # no outside map tiles
