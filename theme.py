"""
theme.py — Color palettes, theme switching, and widget registry.
"""

import tkinter as tk

# ─────────────────────────────────────────────────────────────────────────────
# PALETTES
# ─────────────────────────────────────────────────────────────────────────────

DARK: dict[str, str] = {
    "bg":          "#0d1117",
    "bg2":         "#10141c",
    "card":        "#161b27",
    "card2":       "#1c2133",
    "input":       "#1a1f2e",
    "border":      "#252d40",
    "border2":     "#2e3850",
    "accent":      "#3b82f6",
    "accent_dk":   "#2563eb",
    "green":       "#22c55e",
    "green_dk":    "#16a34a",
    "violet":      "#8b5cf6",
    "violet_dk":   "#7c3aed",
    "amber":       "#f59e0b",
    "red":         "#ef4444",
    "text":        "#f1f5f9",
    "text2":       "#94a3b8",
    "text3":       "#4a5568",
    "tag_bg":      "#1e2d40",
    "tag_fg":      "#60a5fa",
    "white":       "#ffffff",
    "mode":        "dark",
}

LIGHT: dict[str, str] = {
    "bg":          "#f8fafc",
    "bg2":         "#f1f5f9",
    "card":        "#ffffff",
    "card2":       "#f8fafc",
    "input":       "#ffffff",
    "border":      "#e2e8f0",
    "border2":     "#cbd5e1",
    "accent":      "#3b82f6",
    "accent_dk":   "#2563eb",
    "green":       "#16a34a",
    "green_dk":    "#15803d",
    "violet":      "#7c3aed",
    "violet_dk":   "#6d28d9",
    "amber":       "#d97706",
    "red":         "#dc2626",
    "text":        "#0f172a",
    "text2":       "#475569",
    "text3":       "#94a3b8",
    "tag_bg":      "#dbeafe",
    "tag_fg":      "#2563eb",
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

FH  = ("Segoe UI", 16, "bold")   # hero title
FL  = ("Segoe UI", 10, "bold")   # section label
FS  = ("Segoe UI",  9)           # small / caption
FM  = ("Consolas",  9)           # mono
FB  = ("Segoe UI", 10, "bold")   # button primary
FBS = ("Segoe UI",  9, "bold")   # button secondary
FT  = ("Segoe UI",  8)           # tag / badge
