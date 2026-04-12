"""
ui.py - Premium Tkinter GUI for Contexta.
"""

from __future__ import annotations

import base64
import struct
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from context_engine import (
    AI_PROFILE_OPTIONS,
    APP_NAME,
    COMPRESSION_OPTIONS,
    CONTEXT_MODE_OPTIONS,
    MODEL_PROMPT_GUIDANCE,
    PACK_DEFAULTS,
    PACK_OPTIONS,
    TASK_PROFILE_OPTIONS,
)
from renderer import __version__, generate_markdown, section_titles_for_preview
from scanner import build_tree, count_files, get_git_changed_files, load_gitignore_patterns
from theme import C, FB, FBS, FH, FL, FM, FS, FT, ThemeRegistry, darken, reg, toggle_theme
from utils import get_desktop, safe_project_name


PACK_HELP = {
    "custom": "Leaves every control in your hands without forcing a workflow.",
    "chatgpt": "Good general-purpose preset for everyday ChatGPT-assisted work.",
    "onboarding": "Best first stop to understand a new codebase fast.",
    "debug": "Pushes changed and suspicious files to the top for bug hunting.",
    "pr_review": "Shapes the pack around code review, risk spotting, and recent changes.",
    "frontend": "Biases the selection toward interface flows, views, widgets, and user-facing assets.",
    "backend": "Biases the selection toward non-UI application logic, data flow, and integration-heavy modules.",
    "changes_related": "Starts from recent changes and expands outward to the most relevant nearby files.",
}

MODE_HELP = {
    "full": "Includes as much useful project context as possible.",
    "debug": "Prefers hotspots, recent edits, and files near the reported issue.",
    "feature": "Curates files around the feature or area named in Focus.",
    "diff": "Starts from git changes and expands only where it adds context.",
    "onboarding": "Builds a clean project tour with architecture and entry points.",
    "refactor": "Collects core modules plus the files they are connected to.",
}

AI_HELP = {key: str(entry["summary"]) for key, entry in MODEL_PROMPT_GUIDANCE.items()}


def format_model_guidance(profile: str) -> str:
    guidance = MODEL_PROMPT_GUIDANCE.get(profile, MODEL_PROMPT_GUIDANCE["generic"])
    lines = [
        str(guidance["label"]),
        "- Usually works well:",
    ]
    lines.extend(f"  - {entry}" for entry in guidance["works_well"])
    lines.append("- Usually avoid:")
    lines.extend(f"  - {entry}" for entry in guidance["avoid"])
    lines.append("- Rough usage profile:")
    lines.extend(f"  - {entry}" for entry in guidance["usage"])
    return "\n".join(lines)

TASK_HELP = {
    "general": "Keeps the export broadly useful for follow-up questions and implementation work.",
    "ai_handoff": "Prepares a pack that another AI can pick up quickly with minimal extra prompting.",
    "explain_project": "Prioritizes architecture, purpose, and how the project fits together.",
    "bug_report": "Emphasizes suspicious files, flows, and recent changes tied to a bug.",
    "code_review": "Frames the export for quality, risk, and code review feedback.",
    "refactor_request": "Emphasizes central modules and coupling for refactor ideas.",
    "write_tests": "Highlights behaviors, entry points, and related tests for test generation.",
    "find_dead_code": "Pushes utilities, disconnected modules, and unused-looking files higher.",
    "pr_summary": "Shapes the pack so an AI can summarize a PR or a set of changes quickly.",
}

COMPRESSION_HELP = {
    "full": "Keep full file payloads and add guidance around them. Best when fidelity matters more than token cost.",
    "balanced": "Mix summaries, key excerpts, and full payloads for the most important files.",
    "focused": "Trim aggressively and keep only the parts most likely to matter for the task.",
    "signatures": "Prefer structural summaries and signatures when you need a rapid, low-token project map.",
}

OPTION_GUIDE = (
    "Hidden files: include dotfiles and hidden folders like .env or .github.\n"
    "Unknown extensions: include files with uncommon or extensionless names.\n"
    "Prefer recent git changes: prioritize modified files during selection.\n"
    "Staged only: when diff mode is on, use only git staged changes.\n"
    "Copy latest pack: automatically copy the generated Markdown to the clipboard."
)


def resolve_pack_focus(current_focus: str, previous_auto_focus: str, preset_focus: str) -> tuple[str, str]:
    current = current_focus.strip()
    previous = previous_auto_focus.strip()
    preset = preset_focus.strip()

    if not current or current == previous:
        return preset, preset
    return current, previous


def estimate_selected_files(total_files: int, changed_files: int, mode_key: str, has_focus: bool) -> int:
    if total_files <= 0:
        return 0
    if mode_key == "full":
        return total_files
    if mode_key == "diff":
        return min(max(changed_files * 2, changed_files or 0), min(total_files, 20))
    if mode_key == "debug":
        return min(max((changed_files * 3) if changed_files else 8, 8), min(total_files, 20))
    if mode_key == "feature":
        return min(12 if has_focus else 10, min(total_files, 20))
    if mode_key == "refactor":
        return min(16, min(total_files, 20))
    if mode_key == "onboarding":
        return min(10, min(total_files, 12))
    return min(12, min(total_files, 20))


def estimate_tokens_for_preview(selected_files: int, compression_key: str) -> int:
    per_file = {
        "full": 900,
        "balanced": 430,
        "focused": 230,
        "signatures": 130,
    }.get(compression_key, 430)
    overhead = 1400
    return max(0, overhead + (selected_files * per_file))


def format_token_k(tokens: int) -> str:
    return f"~{tokens / 1000:.1f}k"


def _icon_path() -> Path | None:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon = root / "icon.ico"
    return icon if icon.is_file() else None


def _enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _extract_icon_png(icon_path: Path) -> bytes | None:
    try:
        data = icon_path.read_bytes()
    except OSError:
        return None

    if len(data) < 6:
        return None

    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count < 1:
        return None

    best_entry: tuple[int, bytes] | None = None
    for index in range(count):
        offset = 6 + index * 16
        if offset + 16 > len(data):
            continue
        width, height, _colors, _reserved, _planes, _bitcount, size, data_offset = struct.unpack_from("<BBBBHHII", data, offset)
        if data_offset + size > len(data):
            continue
        blob = data[data_offset : data_offset + size]
        if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
            continue
        edge = max(width or 256, height or 256)
        if best_entry is None or edge > best_entry[0]:
            best_entry = (edge, blob)

    return best_entry[1] if best_entry else None


def _load_icon_photo(target_px: int | None = None) -> tk.PhotoImage | None:
    icon = _icon_path()
    png_bytes = _extract_icon_png(icon) if icon else None
    if not png_bytes:
        return None
    try:
        photo = tk.PhotoImage(data=base64.b64encode(png_bytes).decode("ascii"))
    except tk.TclError:
        return None
    if target_px and photo.width() > target_px:
        factor = max(1, round(photo.width() / target_px))
        if factor > 1:
            photo = photo.subsample(factor, factor)
    return photo


class BrandMark(tk.Canvas):
    SIZE = 46

    def __init__(self, parent):
        super().__init__(parent, width=self.SIZE, height=self.SIZE, highlightthickness=0, bd=0, bg=C["card"])
        reg(self, lambda w: w._draw())
        self._draw()

    def _draw(self):
        self.delete("all")
        self.configure(bg=C["card"])
        self.create_oval(4, 4, self.SIZE - 4, self.SIZE - 4, fill=C["tag_bg"], outline=C["tag_bg"])
        self.create_arc(11, 11, self.SIZE - 11, self.SIZE - 11, start=40, extent=280, style="arc", outline=C["accent"], width=3)
        self.create_line(26, 12, 20, 23, 29, 23, 18, 35, fill=C["accent"], width=3, capstyle="round", joinstyle="round")


class FlatBtn(tk.Frame):
    def __init__(self, parent, text: str, color_key: str, command, font=None, padx: int = 18, pady: int = 9, surface_key: str = "bg"):
        super().__init__(parent, bg=C[surface_key])
        self._color_key = color_key
        self._surface_key = surface_key
        self._enabled = True
        self._btn = tk.Button(
            self,
            text=text,
            font=font or FB,
            bg=C[color_key],
            fg=C["white"],
            activebackground=darken(C[color_key]),
            activeforeground=C["white"],
            relief="flat",
            bd=0,
            padx=padx,
            pady=pady,
            cursor="hand2",
            command=command,
        )
        self._btn.pack(fill="both", expand=True)
        self._btn.bind("<Enter>", self._hover_on)
        self._btn.bind("<Leave>", self._hover_off)
        reg(self, lambda w: w._repaint())

    def _repaint(self):
        super().configure(bg=C[self._surface_key])
        if self._enabled:
            self._btn.configure(bg=C[self._color_key], fg=C["white"], activebackground=darken(C[self._color_key]), cursor="hand2")
        else:
            self._btn.configure(bg=C["border"], fg=C["text3"], cursor="arrow")

    def _hover_on(self, _=None):
        if self._enabled:
            self._btn.configure(bg=darken(C[self._color_key]))

    def _hover_off(self, _=None):
        if self._enabled:
            self._btn.configure(bg=C[self._color_key])

    def configure(self, **kw):
        if "state" in kw:
            self._enabled = kw.pop("state") != "disabled"
            self._btn.configure(state="normal" if self._enabled else "disabled")
            self._repaint()
        if "text" in kw:
            self._btn.configure(text=kw.pop("text"))
        if kw:
            super().configure(**kw)


class Card(tk.Frame):
    def __init__(self, parent, pad: int = 16):
        super().__init__(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
        self._pad = pad
        reg(self, lambda w: w.configure(bg=C["card"], highlightbackground=C["border"]))

    def inner(self):
        frame = tk.Frame(self, bg=C["card"])
        frame.pack(fill="both", expand=True, padx=self._pad, pady=self._pad)
        reg(frame, lambda w: w.configure(bg=C["card"]))
        return frame


class ScrollArea(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=C["bg"])
        self._active = False
        reg(self, lambda w: w._repaint())

        self._canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        self._canvas.pack(side="left", fill="both", expand=True)
        reg(self._canvas, lambda w: w.configure(bg=C["bg"]))

        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self.content = tk.Frame(self._canvas, bg=C["bg"])
        reg(self.content, lambda w: w.configure(bg=C["bg"]))
        self._window = self._canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.content.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        for widget in (self, self._canvas, self.content):
            widget.bind("<Enter>", self._bind_mousewheel, add="+")
            widget.bind("<Leave>", self._unbind_mousewheel, add="+")

    def _repaint(self):
        self.configure(bg=C["bg"])
        self._canvas.configure(bg=C["bg"])
        self.content.configure(bg=C["bg"])

    def _on_content_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._window, width=event.width)

    def _bind_mousewheel(self, _event=None):
        if not self._active:
            self._canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
            self._active = True

    def _unbind_mousewheel(self, _event=None):
        if self._active:
            self._canvas.unbind_all("<MouseWheel>")
            self._active = False

    def _on_mousewheel(self, event):
        if event.delta:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")


class Toggle(tk.Frame):
    WIDTH = 38
    HEIGHT = 22

    def __init__(self, parent, text: str, variable: tk.BooleanVar):
        super().__init__(parent, bg=C["card"])
        self._var = variable
        self._enabled = True
        self._canvas = tk.Canvas(self, width=self.WIDTH, height=self.HEIGHT, highlightthickness=0, bg=C["card"], cursor="hand2")
        self._canvas.pack(side="left")
        self._label = tk.Label(self, text=text, font=FS, bg=C["card"], fg=C["text2"], cursor="hand2")
        self._label.pack(side="left", padx=(10, 0))
        for widget in (self, self._canvas, self._label):
            widget.bind("<Button-1>", self._toggle)
        reg(self, lambda w: w._repaint())
        self._draw()

    def _repaint(self):
        self.configure(bg=C["card"])
        self._canvas.configure(bg=C["card"], cursor="hand2" if self._enabled else "arrow")
        self._label.configure(bg=C["card"], fg=C["text2"] if self._enabled else C["text3"], cursor="hand2" if self._enabled else "arrow")
        self._draw()

    def _draw(self):
        self._canvas.delete("all")
        radius = self.HEIGHT // 2
        track = C["accent"] if self._var.get() and self._enabled else C["border2"]
        if not self._enabled:
            track = C["border"]
        self._canvas.create_oval(0, 0, self.HEIGHT, self.HEIGHT, fill=track, outline=track)
        self._canvas.create_oval(self.WIDTH - self.HEIGHT, 0, self.WIDTH, self.HEIGHT, fill=track, outline=track)
        self._canvas.create_rectangle(radius, 0, self.WIDTH - radius, self.HEIGHT, fill=track, outline=track)
        knob_x = self.WIDTH - radius if self._var.get() else radius
        self._canvas.create_oval(knob_x - radius + 3, 3, knob_x + radius - 3, self.HEIGHT - 3, fill=C["white"], outline="")

    def _toggle(self, _=None):
        if not self._enabled:
            return
        self._var.set(not self._var.get())
        self._draw()

    def configure(self, **kw):
        if "state" in kw:
            self._enabled = kw.pop("state") != "disabled"
            self._repaint()
        if kw:
            super().configure(**kw)


class ThemeToggleBtn(tk.Canvas):
    SIZE = 30

    def __init__(self, parent, command):
        super().__init__(parent, width=self.SIZE, height=self.SIZE, highlightthickness=0, bd=0, bg=C["card"], cursor="hand2")
        self._command = command
        self.bind("<Button-1>", lambda _: self._command())
        self.bind("<Enter>", lambda _: self._draw(True))
        self.bind("<Leave>", lambda _: self._draw(False))
        reg(self, lambda w: w._draw(False))
        self._draw(False)

    def _draw(self, hover: bool):
        self.delete("all")
        self.configure(bg=C["card"])
        color = C["accent"] if hover else C["text2"]
        center = self.SIZE // 2
        if C["mode"] == "dark":
            self.create_oval(center - 4, center - 4, center + 4, center + 4, fill=color, outline=color)
            for x1, y1, x2, y2 in (
                (center, 4, center, 7),
                (center, self.SIZE - 4, center, self.SIZE - 7),
                (4, center, 7, center),
                (self.SIZE - 4, center, self.SIZE - 7, center),
                (7, 7, 9, 9),
                (self.SIZE - 7, 7, self.SIZE - 9, 9),
                (7, self.SIZE - 7, 9, self.SIZE - 9),
                (self.SIZE - 7, self.SIZE - 7, self.SIZE - 9, self.SIZE - 9),
            ):
                self.create_line(x1, y1, x2, y2, fill=color, width=1.6, capstyle="round")
        else:
            self.create_oval(center - 6, center - 6, center + 6, center + 6, fill=color, outline=color)
            self.create_oval(center - 2, center - 7, center + 7, center + 5, fill=C["card"], outline=C["card"])


class App(tk.Tk):
    def __init__(self):
        _enable_windows_dpi_awareness()
        super().__init__()
        self.title(f"{APP_NAME} v{__version__}")
        self.configure(bg=C["bg"])
        self.geometry("1120x760")
        self.minsize(920, 620)
        self.resizable(True, True)

        self._project_path: Path | None = None
        self._running = False
        self._last_md = ""
        self._help_window: tk.Toplevel | None = None
        self._icon_photo = _load_icon_photo()
        self._brand_logo = _load_icon_photo(52)

        icon = _icon_path()
        if self._icon_photo:
            try:
                self.iconphoto(True, self._icon_photo)
            except Exception:
                pass
        if icon:
            try:
                self.wm_iconbitmap(str(icon))
                self.iconbitmap(default=str(icon))
            except Exception:
                pass

        self._setup_ttk()
        self._init_vars()
        self._build_ui()
        self._configure_scaling()
        self._apply_pack_profile()
        self._sync_option_states()
        self._refresh_preview()
        self._center()

    def _init_vars(self):
        self._combo_widgets: dict[str, tuple[tk.Variable, ttk.Combobox, dict[str, str]]] = {}
        self._last_auto_focus = ""
        self._preview_snapshot: dict[str, int] | None = None
        self._path_var = tk.StringVar()
        self._focus_var = tk.StringVar()
        self._pack_var = tk.StringVar(value="onboarding")
        self._mode_var = tk.StringVar(value="onboarding")
        self._ai_var = tk.StringVar(value="generic")
        self._task_var = tk.StringVar(value="explain_project")
        self._compression_var = tk.StringVar(value="balanced")
        self._hidden_var = tk.BooleanVar()
        self._unknown_var = tk.BooleanVar()
        self._diff_var = tk.BooleanVar()
        self._staged_var = tk.BooleanVar()
        self._copy_var = tk.BooleanVar(value=True)

    def _setup_ttk(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            padding=6,
            fieldbackground=C["input"],
            background=C["input"],
            foreground=C["text"],
            bordercolor=C["border"],
            arrowcolor=C["text2"],
            lightcolor=C["input"],
            darkcolor=C["input"],
            insertcolor=C["accent"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", C["input"])],
            foreground=[("readonly", C["text"])],
            selectbackground=[("readonly", C["input"])],
            selectforeground=[("readonly", C["text"])],
        )
        style.configure("TProgressbar", troughcolor=C["bg2"], background=C["accent"], bordercolor=C["bg"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=7)
        style.configure("TScrollbar", troughcolor=C["card"], background=C["border"], arrowcolor=C["text3"], bordercolor=C["card"], relief="flat")

    def _refresh_ttk(self):
        self._setup_ttk()

    def _configure_scaling(self):
        try:
            dpi_scale = max(self.winfo_fpixels("1i") / 72.0, 1.0)
            self.tk.call("tk", "scaling", dpi_scale)
        except Exception:
            pass

    def _build_ui(self):
        ThemeRegistry.reset()

        header = tk.Frame(self, bg=C["card"])
        header.pack(fill="x")
        reg(header, lambda w: w.configure(bg=C["card"]))

        header_inner = tk.Frame(header, bg=C["card"])
        header_inner.pack(fill="both", expand=True, padx=22, pady=(18, 16))
        reg(header_inner, lambda w: w.configure(bg=C["card"]))

        left = tk.Frame(header_inner, bg=C["card"])
        left.pack(side="left", fill="x", expand=True)
        reg(left, lambda w: w.configure(bg=C["card"]))

        if self._brand_logo:
            brand = tk.Label(left, image=self._brand_logo, bg=C["card"])
            brand.pack(side="left", padx=(0, 14))
            reg(brand, lambda w: w.configure(bg=C["card"]))
        else:
            BrandMark(left).pack(side="left", padx=(0, 14))

        titles = tk.Frame(left, bg=C["card"])
        titles.pack(side="left", fill="x", expand=True)
        reg(titles, lambda w: w.configure(bg=C["card"]))

        title = tk.Label(titles, text=APP_NAME, font=FH, bg=C["card"], fg=C["text"])
        title.pack(anchor="w")
        reg(title, lambda w: w.configure(bg=C["card"], fg=C["text"]))

        subtitle = tk.Label(titles, text="Curated context packs for debugging, onboarding, reviews, and refactors.", font=FS, bg=C["card"], fg=C["text2"], wraplength=760, justify="left")
        subtitle.pack(anchor="w", pady=(3, 0))
        reg(subtitle, lambda w: w.configure(bg=C["card"], fg=C["text2"]))

        right = tk.Frame(header_inner, bg=C["card"])
        right.pack(side="right")
        reg(right, lambda w: w.configure(bg=C["card"]))

        self._version_badge = tk.Label(right, text=f"v{__version__}", font=FT, bg=C["tag_bg"], fg=C["tag_fg"], padx=12, pady=5)
        self._version_badge.pack(side="right", padx=(10, 0))
        reg(self._version_badge, lambda w: w.configure(bg=C["tag_bg"], fg=C["tag_fg"]))
        self._help_btn = FlatBtn(right, "Quick Guide", "violet", self._open_help, font=FBS, padx=14, pady=7, surface_key="card")
        self._help_btn.pack(side="right", padx=(0, 10))
        ThemeToggleBtn(right, self._toggle_theme).pack(side="right")

        self._scroll_shell = ScrollArea(self)
        self._scroll_shell.pack(fill="both", expand=True, padx=18, pady=(18, 10))
        shell = self._scroll_shell.content
        shell.grid_columnconfigure(0, weight=11, uniform="cols")
        shell.grid_columnconfigure(1, weight=13, uniform="cols")

        self._build_controls(shell)
        self._build_preview(shell)
        self._build_log(shell)
        self._build_footer()
        self._bind_preview_updates()

    def _build_controls(self, parent):
        left = tk.Frame(parent, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_columnconfigure(0, weight=1)
        reg(left, lambda w: w.configure(bg=C["bg"]))

        project_card = Card(left)
        project_card.grid(row=0, column=0, sticky="ew")
        project_inner = project_card.inner()
        self._section(project_inner, "Project Source", "Choose the folder that will be analyzed.").pack(anchor="w")
        row = tk.Frame(project_inner, bg=C["card"])
        row.pack(fill="x", pady=(12, 0))
        reg(row, lambda w: w.configure(bg=C["card"]))
        entry = tk.Entry(row, textvariable=self._path_var, font=FM, bg=C["input"], fg=C["text"], insertbackground=C["accent"], relief="flat", bd=0)
        entry.pack(side="left", fill="x", expand=True, ipady=9, padx=(12, 0))
        reg(entry, lambda w: w.configure(bg=C["input"], fg=C["text"], insertbackground=C["accent"]))
        self._btn_pick = FlatBtn(row, "Browse", "accent_dk", self._pick_folder, font=FBS, surface_key="card")
        self._btn_pick.pack(side="left", padx=(10, 0))

        guide_card = Card(left)
        guide_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        guide_inner = guide_card.inner()
        self._section(guide_inner, "Quick Start", "Use this as your default flow when you just want a good pack fast.").pack(anchor="w")
        guide_steps = tk.Label(
            guide_inner,
            text="1. Choose a project folder.\n2. Pick a Context Pack.\n3. Add Focus only if you want to bias the selection.\n4. Create Context Pack from the fixed action bar below.",
            justify="left",
            font=FS,
            bg=C["card"],
            fg=C["text2"],
            wraplength=360,
        )
        guide_steps.pack(anchor="w", pady=(12, 0))
        reg(guide_steps, lambda w: w.configure(bg=C["card"], fg=C["text2"]))
        self._guide_cta = FlatBtn(guide_inner, "Open Detailed Guide", "violet", self._open_help, font=FBS, padx=14, pady=7, surface_key="card")
        self._guide_cta.pack(anchor="w", pady=(12, 0))

        strategy_card = Card(left)
        strategy_card.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        strategy_inner = strategy_card.inner()
        self._section(strategy_inner, "Context Strategy", "Packs and modes define how Contexta curates the codebase.").pack(anchor="w")
        self._combo_field(strategy_inner, "Context Pack", self._pack_var, PACK_OPTIONS, "Preset workflow bundle. Good default if you do not want to fine-tune each option.").pack(fill="x", pady=(12, 0))
        self._combo_field(strategy_inner, "Context Mode", self._mode_var, CONTEXT_MODE_OPTIONS, "How Contexta chooses files and relationships for the pack.").pack(fill="x", pady=(10, 0))
        self._entry_field(strategy_inner, "Focus", self._focus_var, "Bug, feature, area, or keyword", "Optional. Use names like login, payments, renderer, or memory leak to bias the selection.").pack(fill="x", pady=(10, 0))

        output_card = Card(left)
        output_card.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        output_inner = output_card.inner()
        self._section(output_inner, "AI Output Profile", "Tune the pack for the model and the job you want done.").pack(anchor="w")
        self._combo_field(output_inner, "AI Target", self._ai_var, AI_PROFILE_OPTIONS, "Adjusts formatting and structure for the AI you plan to use.").pack(fill="x", pady=(12, 0))
        self._combo_field(output_inner, "Task Mode", self._task_var, TASK_PROFILE_OPTIONS, "Tells Contexta what you want the AI to do with this project.").pack(fill="x", pady=(10, 0))
        self._combo_field(output_inner, "Compression", self._compression_var, COMPRESSION_OPTIONS, "Controls how much raw code is kept versus summaries and signatures.").pack(fill="x", pady=(10, 0))

        goal_label = tk.Label(output_inner, text="Custom Goal", font=FT, bg=C["card"], fg=C["text3"])
        goal_label.pack(anchor="w", pady=(12, 6))
        reg(goal_label, lambda w: w.configure(bg=C["card"], fg=C["text3"]))
        self._prompt = tk.Text(output_inner, height=4, font=FS, bg=C["input"], fg=C["text"], insertbackground=C["accent"], relief="flat", bd=0, padx=12, pady=10, wrap="word")
        self._prompt.pack(fill="x")
        reg(self._prompt, lambda w: w.configure(bg=C["input"], fg=C["text"], insertbackground=C["accent"]))

        options_card = Card(left)
        options_card.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        options_inner = options_card.inner()
        self._section(options_inner, "Options", "Practical toggles for scanning and exporting.").pack(anchor="w")
        toggles = tk.Frame(options_inner, bg=C["card"])
        toggles.pack(fill="x", pady=(12, 0))
        reg(toggles, lambda w: w.configure(bg=C["card"]))
        self._toggle_hidden = Toggle(toggles, "Include hidden files", self._hidden_var)
        self._toggle_hidden.pack(anchor="w", pady=(0, 8))
        self._toggle_unknown = Toggle(toggles, "Include unknown extensions", self._unknown_var)
        self._toggle_unknown.pack(anchor="w", pady=(0, 8))
        self._toggle_diff = Toggle(toggles, "Prefer recent git changes", self._diff_var)
        self._toggle_diff.pack(anchor="w", pady=(0, 8))
        self._toggle_staged = Toggle(toggles, "Staged only", self._staged_var)
        self._toggle_staged.pack(anchor="w", pady=(0, 8))
        self._toggle_copy = Toggle(toggles, "Copy latest pack after export", self._copy_var)
        self._toggle_copy.pack(anchor="w")
        option_help = tk.Label(options_inner, text=OPTION_GUIDE, justify="left", wraplength=360, font=FT, bg=C["card"], fg=C["text3"])
        option_help.pack(anchor="w", pady=(12, 0))
        reg(option_help, lambda w: w.configure(bg=C["card"], fg=C["text3"]))

    def _build_preview(self, parent):
        right = tk.Frame(parent, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        reg(right, lambda w: w.configure(bg=C["bg"]))

        preview_card = Card(right)
        preview_card.grid(row=0, column=0, sticky="nsew")
        preview_inner = preview_card.inner()
        preview_inner.grid_columnconfigure(0, weight=1)
        preview_inner.grid_rowconfigure(1, weight=1)
        self._section(preview_inner, "Pack Preview", "What Contexta will prioritize in the generated pack.").grid(row=0, column=0, sticky="w")
        preview_shell = tk.Frame(preview_inner, bg=C["bg2"], highlightthickness=1, highlightbackground=C["border"])
        preview_shell.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        preview_shell.grid_columnconfigure(0, weight=1)
        preview_shell.grid_rowconfigure(0, weight=1)
        reg(preview_shell, lambda w: w.configure(bg=C["bg2"], highlightbackground=C["border"]))
        self._preview = tk.Text(preview_shell, height=18, font=FS, bg=C["bg2"], fg=C["text"], insertbackground=C["accent"], relief="flat", bd=0, padx=14, pady=14, wrap="word", state="disabled")
        self._preview.grid(row=0, column=0, sticky="nsew")
        reg(self._preview, lambda w: w.configure(bg=C["bg2"], fg=C["text"], insertbackground=C["accent"]))
        preview_scroll = ttk.Scrollbar(preview_shell, orient="vertical", command=self._preview.yview)
        preview_scroll.grid(row=0, column=1, sticky="ns")
        self._preview.configure(yscrollcommand=preview_scroll.set)

        note_card = Card(right)
        note_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        note_inner = note_card.inner()
        self._section(note_inner, "Reading Tips", "How to use the main controls without guessing.").pack(anchor="w")
        tips = tk.Label(
            note_inner,
            text="Context Pack is the preset. Context Mode is the selection strategy. AI Target changes formatting. Task Mode changes the reading lens. Compression controls how much raw code survives. Focus boosts scoring, ordering, excerpts, and related context instead of blindly filtering files.",
            justify="left",
            wraplength=500,
            font=FS,
            bg=C["card"],
            fg=C["text2"],
        )
        tips.pack(anchor="w", pady=(12, 0))
        reg(tips, lambda w: w.configure(bg=C["card"], fg=C["text2"]))

    def _build_log(self, parent):
        log_card = Card(parent)
        log_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        log_inner = log_card.inner()
        log_inner.grid_columnconfigure(0, weight=1)
        self._section(log_inner, "Activity", "Scan progress, selection notes, and export messages.").grid(row=0, column=0, sticky="w")
        log_shell = tk.Frame(log_inner, bg=C["bg2"], highlightthickness=1, highlightbackground=C["border"])
        log_shell.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        log_shell.grid_columnconfigure(0, weight=1)
        log_shell.grid_rowconfigure(0, weight=1)
        reg(log_shell, lambda w: w.configure(bg=C["bg2"], highlightbackground=C["border"]))
        self._log = tk.Text(log_shell, height=9, font=FM, bg=C["bg2"], fg=C["text"], insertbackground=C["accent"], relief="flat", bd=0, padx=12, pady=12, wrap="word", state="disabled")
        self._log.grid(row=0, column=0, sticky="nsew")
        reg(self._log, lambda w: w.configure(bg=C["bg2"], fg=C["text"], insertbackground=C["accent"]))
        scrollbar = ttk.Scrollbar(log_shell, orient="vertical", command=self._log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._log.configure(yscrollcommand=scrollbar.set)

        for tag, color_key in (("ok", "green"), ("warn", "amber"), ("err", "red"), ("info", "accent"), ("muted", "text3")):
            self._log.tag_config(tag, foreground=C[color_key])

    def _build_footer(self):
        footer = tk.Frame(self, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
        footer.pack(fill="x", padx=18, pady=(0, 18))
        reg(footer, lambda w: w.configure(bg=C["card"], highlightbackground=C["border"]))

        inner = tk.Frame(footer, bg=C["card"])
        inner.pack(fill="x", padx=16, pady=14)
        reg(inner, lambda w: w.configure(bg=C["card"]))
        inner.grid_columnconfigure(1, weight=1)

        label = tk.Label(inner, text="Export Actions", font=FL, bg=C["card"], fg=C["text"])
        label.grid(row=0, column=0, sticky="w")
        reg(label, lambda w: w.configure(bg=C["card"], fg=C["text"]))
        hint = tk.Label(inner, text="Generate from here at any time. The page above can scroll independently.", font=FT, bg=C["card"], fg=C["text3"])
        hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))
        reg(hint, lambda w: w.configure(bg=C["card"], fg=C["text3"]))

        self._status = tk.Label(inner, text="Idle", font=FT, bg=C["tag_bg"], fg=C["tag_fg"], padx=12, pady=6)
        self._status.grid(row=0, column=2, sticky="e")
        reg(self._status, lambda w: w.configure(bg=C["tag_bg"], fg=C["tag_fg"]))

        self._progress = ttk.Progressbar(inner, style="TProgressbar", mode="indeterminate")
        self._progress.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        actions = tk.Frame(inner, bg=C["card"])
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        reg(actions, lambda w: w.configure(bg=C["card"]))
        actions.grid_columnconfigure(2, weight=1)

        self._btn_generate = FlatBtn(actions, "Create Context Pack", "green", self._start, surface_key="card")
        self._btn_generate.configure(state="disabled")
        self._btn_generate.grid(row=0, column=0, sticky="w")
        self._btn_copy = FlatBtn(actions, "Copy Latest", "violet", self._copy_to_clipboard, font=FBS, surface_key="card")
        self._btn_copy.configure(state="disabled")
        self._btn_copy.grid(row=0, column=1, sticky="w", padx=(10, 0))

    def _section(self, parent, title: str, subtitle: str):
        row = tk.Frame(parent, bg=C["card"])
        reg(row, lambda w: w.configure(bg=C["card"]))
        title_label = tk.Label(row, text=title, font=FL, bg=C["card"], fg=C["text"])
        title_label.pack(anchor="w")
        reg(title_label, lambda w: w.configure(bg=C["card"], fg=C["text"]))
        subtitle_label = tk.Label(row, text=subtitle, font=FT, bg=C["card"], fg=C["text3"])
        subtitle_label.pack(anchor="w", pady=(3, 0))
        reg(subtitle_label, lambda w: w.configure(bg=C["card"], fg=C["text3"]))
        return row

    def _combo_field(self, parent, label: str, var: tk.StringVar, options: dict[str, str], helper_text: str = ""):
        frame = tk.Frame(parent, bg=C["card"])
        reg(frame, lambda w: w.configure(bg=C["card"]))
        label_widget = tk.Label(frame, text=label, font=FT, bg=C["card"], fg=C["text3"])
        label_widget.pack(anchor="w", pady=(0, 6))
        reg(label_widget, lambda w: w.configure(bg=C["card"], fg=C["text3"]))
        values = [f"{key} - {value}" for key, value in options.items()]
        combo = ttk.Combobox(frame, values=values, state="readonly", font=FS)
        combo.pack(fill="x")
        current_label = f"{var.get()} - {options[var.get()]}"
        combo.set(current_label)
        combo.bind("<<ComboboxSelected>>", lambda _e, v=var, c=combo: v.set(c.get().split(" - ", 1)[0]))
        self._combo_widgets[str(var)] = (var, combo, options)
        if helper_text:
            helper = tk.Label(frame, text=helper_text, font=FT, bg=C["card"], fg=C["text3"], wraplength=360, justify="left")
            helper.pack(anchor="w", pady=(6, 0))
            reg(helper, lambda w: w.configure(bg=C["card"], fg=C["text3"]))
        return frame

    def _entry_field(self, parent, label: str, var: tk.StringVar, hint: str, helper_text: str = ""):
        frame = tk.Frame(parent, bg=C["card"])
        reg(frame, lambda w: w.configure(bg=C["card"]))
        label_widget = tk.Label(frame, text=label, font=FT, bg=C["card"], fg=C["text3"])
        label_widget.pack(anchor="w", pady=(0, 6))
        reg(label_widget, lambda w: w.configure(bg=C["card"], fg=C["text3"]))
        entry = tk.Entry(frame, textvariable=var, font=FS, bg=C["input"], fg=C["text"], insertbackground=C["accent"], relief="flat", bd=0)
        entry.pack(fill="x", ipady=8, padx=(12, 0))
        reg(entry, lambda w: w.configure(bg=C["input"], fg=C["text"], insertbackground=C["accent"]))
        helper = tk.Label(frame, text=hint, font=FT, bg=C["card"], fg=C["text3"])
        helper.pack(anchor="w", pady=(6, 0))
        reg(helper, lambda w: w.configure(bg=C["card"], fg=C["text3"]))
        if helper_text:
            explainer = tk.Label(frame, text=helper_text, font=FT, bg=C["card"], fg=C["text3"], wraplength=360, justify="left")
            explainer.pack(anchor="w", pady=(6, 0))
            reg(explainer, lambda w: w.configure(bg=C["card"], fg=C["text3"]))
        return frame

    def _bind_preview_updates(self):
        self._pack_var.trace_add("write", lambda *_: self._apply_pack_profile())
        for var in (self._mode_var, self._ai_var, self._task_var, self._compression_var, self._focus_var):
            var.trace_add("write", lambda *_: self._refresh_preview())
        for var in (self._diff_var, self._staged_var, self._hidden_var, self._unknown_var):
            var.trace_add("write", lambda *_: self._invalidate_preview_snapshot())
        self._diff_var.trace_add("write", lambda *_: self._sync_option_states())
        self._prompt.bind("<KeyRelease>", lambda _e: self._refresh_preview())

    def _invalidate_preview_snapshot(self):
        self._preview_snapshot = None
        self._refresh_preview()

    def _load_preview_snapshot(self) -> dict[str, int] | None:
        if not self._project_path:
            return None
        if self._preview_snapshot is not None:
            return self._preview_snapshot
        try:
            gitignore_patterns = load_gitignore_patterns(self._project_path)
            counter = [0]
            tree = build_tree(
                self._project_path,
                self._hidden_var.get(),
                self._unknown_var.get(),
                lambda *_args, **_kwargs: None,
                counter,
                gitignore_patterns,
                self._project_path,
            )
            total_files = count_files(tree)
            changed_files = get_git_changed_files(self._project_path, staged_only=self._staged_var.get()) or []
            self._preview_snapshot = {
                "total_files": total_files,
                "changed_files": len(changed_files),
            }
        except Exception:
            self._preview_snapshot = {
                "total_files": 0,
                "changed_files": 0,
            }
        return self._preview_snapshot

    def _apply_pack_profile(self):
        preset = PACK_DEFAULTS.get(self._pack_var.get())
        if preset:
            if "context_mode" in preset:
                self._mode_var.set(preset["context_mode"])
            if "ai_profile" in preset:
                self._ai_var.set(preset["ai_profile"])
            if "task_profile" in preset:
                self._task_var.set(preset["task_profile"])
            if "compression" in preset:
                self._compression_var.set(preset["compression"])
        preset_focus = preset.get("focus_query", "") if preset else ""
        next_focus, self._last_auto_focus = resolve_pack_focus(
            self._focus_var.get(),
            self._last_auto_focus,
            preset_focus,
        )
        if next_focus != self._focus_var.get():
            self._focus_var.set(next_focus)

        for _name, (variable, combo, options) in self._combo_widgets.items():
            key = variable.get()
            if key in options:
                combo.set(f"{key} - {options[key]}")
        self._refresh_preview()

    def _sync_option_states(self):
        if not self._diff_var.get():
            self._staged_var.set(False)
        self._toggle_staged.configure(state="normal" if self._diff_var.get() else "disabled")

    def _refresh_preview(self):
        pack_key = self._pack_var.get()
        mode_key = self._mode_var.get()
        ai_key = self._ai_var.get()
        task_key = self._task_var.get()
        compression_key = self._compression_var.get()
        focus_text = self._focus_var.get().strip()
        snapshot = self._load_preview_snapshot()
        total_files = snapshot["total_files"] if snapshot else 0
        changed_files = snapshot["changed_files"] if snapshot else 0
        estimated_files = estimate_selected_files(total_files, changed_files, mode_key, bool(focus_text))
        estimated_tokens = estimate_tokens_for_preview(estimated_files, compression_key)
        full_tokens = estimate_tokens_for_preview(estimate_selected_files(total_files, changed_files, mode_key, bool(focus_text)), "full")
        balanced_tokens = estimate_tokens_for_preview(estimated_files, "balanced")
        focused_tokens = estimate_tokens_for_preview(estimated_files, "focused")
        signatures_tokens = estimate_tokens_for_preview(estimated_files, "signatures")
        reduction_vs_full = 0
        if full_tokens:
            reduction_vs_full = max(0, round((1 - (estimated_tokens / full_tokens)) * 100))
        custom_goal = self._prompt.get("1.0", "end").strip()
        section_titles = section_titles_for_preview(mode_key, task_key, bool(custom_goal))
        guidance_lines = format_model_guidance(ai_key).splitlines()

        lines = [
            f"Pack: {PACK_OPTIONS.get(pack_key, 'Custom Pack')}",
            f"Why this pack: {PACK_HELP.get(pack_key, 'Custom workflow bundle.')}",
            "",
            f"Mode: {CONTEXT_MODE_OPTIONS.get(mode_key, mode_key)}",
            f"What mode does: {MODE_HELP.get(mode_key, 'Controls how Contexta curates project files.')}",
            "",
            f"AI target: {AI_PROFILE_OPTIONS.get(ai_key, ai_key)}",
            f"What AI target changes: {AI_HELP.get(ai_key, 'Adjusts formatting for the selected model.')}",
            "",
            f"Task: {TASK_PROFILE_OPTIONS.get(task_key, task_key)}",
            f"What task changes: {TASK_HELP.get(task_key, 'Shapes the summary and prompt framing.')}",
            "",
            f"Compression: {COMPRESSION_OPTIONS.get(compression_key, compression_key)}",
            f"What compression does: {COMPRESSION_HELP.get(compression_key, 'Controls how much raw code is kept.')}",
            "",
            "Decision Preview:",
            f"- Estimated files selected: ~{estimated_files}" if snapshot else "- Estimated files selected: choose a project folder to calculate",
            f"- Rough output tokens: {format_token_k(estimated_tokens)}" if snapshot else "- Rough output tokens: choose a project folder to calculate",
            f"- Files scanned under current filters: {total_files}" if snapshot else "- Files scanned under current filters: unavailable until a folder is selected",
            f"- Changed files detected: {changed_files}" if snapshot else "- Changed files detected: unavailable until a folder is selected",
            "",
            "Selection strategy:",
            f"- Primary strategy: {MODE_HELP.get(mode_key, 'Controls how Contexta curates project files.')}",
            f"- Focus impact: {'boosts scoring, ordering, excerpts, and related context' if focus_text else 'inactive until you provide a focus query'}",
            f"- Diff impact: {'changed files and nearby context move up hard' if self._diff_var.get() else 'git changes are only a background signal unless diff mode is enabled'}",
            "",
            "Compression comparison:",
            f"- Full: {format_token_k(full_tokens)}",
            f"- Balanced: {format_token_k(balanced_tokens)}",
            f"- Focused: {format_token_k(focused_tokens)}",
            f"- Signatures: {format_token_k(signatures_tokens)}",
            f"- Reduction vs Full: {reduction_vs_full}%",
            "- Token counts are rough and depend on context size, visible output, and model behavior.",
            "",
            "Likely sections in the export:",
        ]
        lines.extend(f"- {title}" for title in section_titles[:10])
        if len(section_titles) > 10:
            lines.append(f"- ...plus {len(section_titles) - 10} more section(s)")
        lines.extend([
            "",
            "Model guidance snapshot:",
        ])
        lines.extend(f"- {line}" for line in guidance_lines[:8] if line.strip())
        lines.extend([
            "",
            "Contexta will generate:",
            "- Read This First and Main Flow guides before the payload",
            "- File-by-file selection reasons and score clues for the most important files",
            "- Project Summary with technologies, entry points, important files, architecture, and hotspots",
            "- Relationship map between central files and likely related tests",
            "- Changed Files + Context when git changes are present",
            "- Suggested prompts and an AI handoff section for paste-ready use",
            "- A compressed payload shaped for the selected task and AI target",
        ])
        if focus_text:
            lines.append(f"- Extra focus on: {focus_text}")
        if self._diff_var.get():
            lines.append("- Git changes will be used as a strong signal during selection")
        if custom_goal:
            lines.extend(["", "Custom goal:", custom_goal])

        self._preview.configure(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.insert("end", "\n".join(lines))
        self._preview.configure(state="disabled")

    def _toggle_theme(self):
        toggle_theme()
        self._refresh_ttk()
        ThemeRegistry.repaint()
        self.configure(bg=C["bg"])
        self._refresh_preview()
        for tag, color_key in (("ok", "green"), ("warn", "amber"), ("err", "red"), ("info", "accent"), ("muted", "text3")):
            self._log.tag_config(tag, foreground=C[color_key])
        if self._help_window and self._help_window.winfo_exists():
            self._render_help()

    def _pick_folder(self):
        path = filedialog.askdirectory(title="Select project folder")
        if not path:
            return
        self._project_path = Path(path)
        self._preview_snapshot = None
        self._path_var.set(str(self._project_path))
        self._btn_generate.configure(state="normal")
        self._log_clear()
        self._log_write(f"Project folder selected: {self._project_path}", "info")
        self._set_status(self._project_path.name, "tag_bg", "tag_fg")
        self._refresh_preview()

    def _start(self):
        if self._running or not self._project_path:
            return
        self._running = True
        self._btn_generate.configure(state="disabled", text="Creating Pack...")
        self._btn_pick.configure(state="disabled")
        self._btn_copy.configure(state="disabled")
        self._progress.start(10)
        self._log_clear()
        self._set_status("Working", "accent", "white")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            custom_goal = self._prompt.get("1.0", "end").strip()
            markdown = generate_markdown(
                self._project_path,
                include_hidden=self._hidden_var.get(),
                include_unknown=self._unknown_var.get(),
                diff_mode=self._diff_var.get(),
                staged_only=self._staged_var.get(),
                system_prompt=custom_goal,
                context_mode=self._mode_var.get(),
                ai_profile=self._ai_var.get(),
                task_profile=self._task_var.get(),
                compression=self._compression_var.get(),
                pack_profile=self._pack_var.get(),
                focus_query=self._focus_var.get().strip(),
                log_cb=self._log_write,
            )
            desktop = get_desktop()
            safe_name = safe_project_name(self._project_path.name)
            out_file = desktop / f"contexta - {safe_name}.md"
            out_file.write_text(markdown, encoding="utf-8")
            self.after(0, lambda: self._finish_success(markdown, out_file, self._copy_var.get()))
        except Exception as exc:
            self._log_write(f"Error: {exc}", "err")
            self.after(0, lambda: self._set_status("Error", "red", "white"))
            self.after(0, lambda: messagebox.showerror("Contexta", str(exc)))
        finally:
            self._running = False
            self.after(0, self._progress.stop)
            self.after(0, lambda: self._btn_generate.configure(state="normal", text="Create Context Pack"))
            self.after(0, lambda: self._btn_pick.configure(state="normal"))

    def _finish_success(self, markdown: str, out_file: Path, copy_requested: bool):
        self._last_md = markdown
        if copy_requested:
            self._do_copy(markdown)
            self._log_write("Copied latest pack to clipboard.", "ok")
        self._log_write(f"Saved: {out_file}", "ok")
        self._btn_copy.configure(state="normal")
        self._set_status("Ready", "green", "white")
        messagebox.showinfo("Contexta", f"Context pack created at:\n\n{out_file}")

    def _copy_to_clipboard(self):
        if not self._last_md:
            messagebox.showwarning("Contexta", "Create a context pack first.")
            return
        self._do_copy(self._last_md)
        self._set_status("Copied", "green", "white")

    def _do_copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()

    def _set_status(self, text: str, bg_key: str, fg_key: str):
        self._status.configure(text=text, bg=C[bg_key], fg=C[fg_key])

    def _log_clear(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _log_write(self, msg: str, tag: str = ""):
        def _write():
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n", tag)
            self._log.see("end")
            self._log.configure(state="disabled")

        self.after(0, _write)

    def _center(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+{(screen_width - width) // 2}+{(screen_height - height) // 2}")

    def _open_help(self):
        if self._help_window and self._help_window.winfo_exists():
            self._help_window.lift()
            self._help_window.focus_force()
            return

        self._help_window = tk.Toplevel(self)
        self._help_window.title("Contexta Guide")
        self._help_window.geometry("760x620")
        self._help_window.minsize(620, 460)
        self._help_window.configure(bg=C["bg"])
        if self._icon_photo:
            try:
                self._help_window.iconphoto(True, self._icon_photo)
            except Exception:
                pass
        self._render_help()

    def _render_help(self):
        if not self._help_window or not self._help_window.winfo_exists():
            return

        for child in self._help_window.winfo_children():
            child.destroy()

        shell = tk.Frame(self._help_window, bg=C["bg"])
        shell.pack(fill="both", expand=True, padx=18, pady=18)
        reg(shell, lambda w: w.configure(bg=C["bg"]))

        title = tk.Label(shell, text="How to use Contexta", font=FH, bg=C["bg"], fg=C["text"])
        title.pack(anchor="w")
        reg(title, lambda w: w.configure(bg=C["bg"], fg=C["text"]))
        subtitle = tk.Label(shell, text="A quick explanation of the controls so you can build the right context pack faster.", font=FS, bg=C["bg"], fg=C["text2"])
        subtitle.pack(anchor="w", pady=(4, 14))
        reg(subtitle, lambda w: w.configure(bg=C["bg"], fg=C["text2"]))

        text_shell = tk.Frame(shell, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
        text_shell.pack(fill="both", expand=True)
        text_shell.grid_columnconfigure(0, weight=1)
        text_shell.grid_rowconfigure(0, weight=1)
        reg(text_shell, lambda w: w.configure(bg=C["card"], highlightbackground=C["border"]))

        guide = tk.Text(text_shell, font=FS, bg=C["card"], fg=C["text"], relief="flat", bd=0, wrap="word", padx=16, pady=16)
        guide.grid(row=0, column=0, sticky="nsew")
        guide.configure(insertbackground=C["accent"])
        reg(guide, lambda w: w.configure(bg=C["card"], fg=C["text"], insertbackground=C["accent"]))
        scroll = ttk.Scrollbar(text_shell, orient="vertical", command=guide.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        guide.configure(yscrollcommand=scroll.set)

        sections = [
            ("Quick start", "Choose a folder, pick a Context Pack, optionally add Focus, then click Create Context Pack in the fixed footer."),
            ("Context Pack", "\n".join(f"- {label}: {PACK_HELP.get(key, '')}" for key, label in PACK_OPTIONS.items())),
            ("Context Mode", "\n".join(f"- {label}: {MODE_HELP.get(key, '')}" for key, label in CONTEXT_MODE_OPTIONS.items())),
            ("AI Target", "\n".join(f"- {label}: {AI_HELP.get(key, '')}" for key, label in AI_PROFILE_OPTIONS.items())),
            ("AI Target guidance", "\n\n".join(format_model_guidance(key) for key in AI_PROFILE_OPTIONS)),
            ("Task Mode", "\n".join(f"- {label}: {TASK_HELP.get(key, '')}" for key, label in TASK_PROFILE_OPTIONS.items())),
            ("Compression", "\n".join(f"- {label}: {COMPRESSION_HELP.get(key, '')}" for key, label in COMPRESSION_OPTIONS.items())),
            ("Focus", "Use a bug name, feature, route, service, file name, or keyword when you want Contexta to bias scoring, ordering, excerpts, and related files around a specific area."),
            ("Options", OPTION_GUIDE),
        ]

        for heading, body in sections:
            guide.insert("end", heading + "\n")
            guide.insert("end", body + "\n\n")

        guide.configure(state="disabled")

        close_row = tk.Frame(shell, bg=C["bg"])
        close_row.pack(fill="x", pady=(12, 0))
        reg(close_row, lambda w: w.configure(bg=C["bg"]))
        close_btn = FlatBtn(close_row, "Close Guide", "accent_dk", self._help_window.destroy, font=FBS, surface_key="bg")
        close_btn.pack(anchor="e")
