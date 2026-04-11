"""
theme.py — Color palettes, theme switching, and widget registry.
"""

import tkinter as tk

# ─────────────────────────────────────────────────────────────────────────────
# PALETTES
# ─────────────────────────────────────────────────────────────────────────────

DARK: dict[str, str] = {
    "bg":          "#0b1220",
    "bg2":         "#121c2e",
    "card":        "#101a2b",
    "card2":       "#162236",
    "input":       "#0d1727",
    "border":      "#24344c",
    "border2":     "#324764",
    "accent":      "#4da3ff",
    "accent_dk":   "#2f7ed8",
    "green":       "#1fb87a",
    "green_dk":    "#159963",
    "violet":      "#51627d",
    "violet_dk":   "#44536b",
    "amber":       "#f59e0b",
    "red":         "#ef4444",
    "text":        "#edf3ff",
    "text2":       "#b7c7de",
    "text3":       "#7588a6",
    "tag_bg":      "#15263c",
    "tag_fg":      "#9dc8ff",
    "white":       "#ffffff",
    "mode":        "dark",
}

LIGHT: dict[str, str] = {
    "bg":          "#eff3f8",
    "bg2":         "#e4ebf4",
    "card":        "#ffffff",
    "card2":       "#f7f9fc",
    "input":       "#ffffff",
    "border":      "#d2dbe7",
    "border2":     "#bac8d9",
    "accent":      "#2c7ed6",
    "accent_dk":   "#1f68b7",
    "green":       "#159963",
    "green_dk":    "#117d52",
    "violet":      "#5e6f86",
    "violet_dk":   "#4f5f75",
    "amber":       "#d97706",
    "red":         "#dc2626",
    "text":        "#13243a",
    "text2":       "#51657f",
    "text3":       "#8193aa",
    "tag_bg":      "#e7f0fb",
    "tag_fg":      "#2c7ed6",
    "white":       "#ffffff",
    "mode":        "light",
}

# Active theme — mutable dict, updated in place on toggle
C: dict[str, str] = dict(DARK)


def apply_theme(theme: dict[str, str]) -> None:
    """Switch the active theme in place."""
    C.clear()
    C.update(theme)


def toggle_theme() -> None:
    """Toggle between dark and light."""
    apply_theme(LIGHT if C["mode"] == "dark" else DARK)


def darken(hex_color: str, amount: int = 25) -> str:
    """Return a darker shade of *hex_color*."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{max(0, r - amount):02x}{max(0, g - amount):02x}{max(0, b - amount):02x}"


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET REGISTRY — live theme repaint
# ─────────────────────────────────────────────────────────────────────────────

class ThemeRegistry:
    _entries: list[tuple] = []

    @classmethod
    def register(cls, widget, cfg_fn) -> None:
        cls._entries.append((widget, cfg_fn))

    @classmethod
    def repaint(cls) -> None:
        dead = []
        for i, (w, fn) in enumerate(cls._entries):
            try:
                fn(w)
            except tk.TclError:
                dead.append(i)
        for i in reversed(dead):
            cls._entries.pop(i)

    @classmethod
    def reset(cls) -> None:
        cls._entries.clear()


def reg(widget, cfg_fn):
    """Register a widget for theme repainting and return it."""
    ThemeRegistry.register(widget, cfg_fn)
    return widget


# ─────────────────────────────────────────────────────────────────────────────
# FONTS
# ─────────────────────────────────────────────────────────────────────────────

FH  = ("Segoe UI Semibold", 17)  # hero title
FL  = ("Segoe UI Semibold", 11)  # section label
FS  = ("Segoe UI", 9)            # small / caption
FM  = ("Consolas", 9)            # mono
FB  = ("Segoe UI Semibold", 10)  # button primary
FBS = ("Segoe UI Semibold", 9)   # button secondary
FT  = ("Segoe UI", 8)            # tag / badge
