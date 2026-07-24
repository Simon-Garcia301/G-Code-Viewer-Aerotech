#!/usr/bin/env python3
"""
ui_common.py
━━━━━━━━━━━━
Shared UI/theme module for Lee Research Group Tool Suite v4.0.0.
Provides unified styling, reusable widget factories, asset handling,
about dialogs, and shared calibration constants.
"""

import os
import sys
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CONSTANTS & CALIBRATION
# ══════════════════════════════════════════════════════════════════════════════

__version__ = "4.0.0"

LENS_CALIBRATION_UM_PER_PX = {
    "4x": 0.8075,  # Reference only — unsupported for reflectance surface roughness
    "5x": 0.6408,  # Primary coaxial reflectance objective
}

# Theme Palette (Dark Scientific Palette)
COLOR_BG_DARK = "#1e1e2e"
COLOR_PANEL_DARK = "#2a2a3e"
COLOR_BORDER = "#666688"
COLOR_TEXT = "#cccccc"
COLOR_TEXT_HEADER = "#eeeeff"
COLOR_TEXT_MUTED = "#888888"
COLOR_PRIMARY = "#4da6ff"
COLOR_SUCCESS = "#44dd88"
COLOR_WARNING = "#f0c040"
COLOR_ERROR = "#ff5555"

# Font Scale
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_SECTION = ("Segoe UI", 10, "bold")
FONT_BODY = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)

# ══════════════════════════════════════════════════════════════════════════════
#  ASSET & ICON RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

def get_asset_path(filename: str) -> str:
    """Resolve asset paths for source execution or PyInstaller bundles."""
    if hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(base_dir, "assets", filename),
        os.path.join(base_dir, filename),
    ]
    if filename == "st_thomas_logo.png":
        candidates.append(os.path.join(base_dir, "st thomas logo.png"))
        candidates.append(os.path.join(base_dir, "assets", "st thomas logo.png"))
    elif filename == "app_icon.ico":
        candidates.append(os.path.join(base_dir, "assets", "app_icon.ico"))

    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]

def ensure_assets_exist() -> None:
    """Ensure assets directory exists and generate app_icon.ico from logo PNG if missing."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(base_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    png_source = get_asset_path("st_thomas_logo.png")
    ico_target = os.path.join(assets_dir, "app_icon.ico")

    if not os.path.exists(ico_target) and os.path.exists(png_source):
        try:
            from PIL import Image
            img = Image.open(png_source)
            img.save(ico_target, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
        except Exception as err:
            print(f"[ui_common] Warning: Could not generate app_icon.ico: {err}")

def load_app_icon(root: tk.Tk | ttk.Window) -> None:
    """Set window and taskbar icon on all top-level windows."""
    ensure_assets_exist()
    ico_path = get_asset_path("app_icon.ico")
    png_path = get_asset_path("st_thomas_logo.png")

    if os.path.exists(ico_path):
        try:
            root.iconbitmap(default=ico_path)
            return
        except Exception:
            pass

    if os.path.exists(png_path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(png_path)
            photo = ImageTk.PhotoImage(img)
            root.iconphoto(True, photo)
            root._app_icon_ref = photo  # Prevent garbage collection
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════════════
#  UI FACTORIES & COMPONENT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def attach_tooltip(widget: tk.Widget, text: str) -> None:
    """Attach an interactive hover tooltip to a Tkinter/ttk widget."""
    tooltip_window = None

    def enter(event=None):
        nonlocal tooltip_window
        if tooltip_window or not text:
            return
        x = widget.winfo_rootx() + 20
        y = widget.winfo_rooty() + widget.winfo_height() + 5

        tooltip_window = tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        lbl = tk.Label(
            tw,
            text=text,
            justify=tk.LEFT,
            background=COLOR_PANEL_DARK,
            foreground=COLOR_TEXT_HEADER,
            relief=tk.SOLID,
            borderwidth=1,
            font=FONT_SMALL,
            padx=8,
            pady=4,
        )
        lbl.pack()

    def leave(event=None):
        nonlocal tooltip_window
        if tooltip_window:
            tooltip_window.destroy()
            tooltip_window = None

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", leave, add="+")

def make_scrollable_left_panel(parent: tk.Widget) -> tuple[tk.Canvas, ttk.Frame]:
    """Return a scrollable left panel frame with auto-width and mousewheel binding."""
    canvas = tk.Canvas(parent, highlightthickness=0, bg=COLOR_BG_DARK)
    scrollbar = ttk.Scrollbar(parent, orient=VERTICAL, command=canvas.yview)
    inner_frame = ttk.Frame(canvas, padding=(0, 0, 5, 0))

    inner_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas_window = canvas.create_window((0, 0), window=inner_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side=LEFT, fill=BOTH, expand=YES)
    scrollbar.pack(side=RIGHT, fill=Y)

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+"))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def _configure_width(event):
        canvas.itemconfig(canvas_window, width=event.width)

    canvas.bind("<Configure>", _configure_width)
    return canvas, inner_frame

def section_label(parent: tk.Widget, text: str) -> ttk.Label:
    """Canonical section header label."""
    lbl = ttk.Label(parent, text=text, font=FONT_SECTION, foreground=COLOR_TEXT, anchor=W)
    lbl.pack(fill=X, pady=(12, 4))
    return lbl

def small_label(parent: tk.Widget, text: str) -> ttk.Label:
    """Canonical small print label."""
    lbl = ttk.Label(parent, text=text, font=FONT_SMALL, foreground=COLOR_TEXT_MUTED, anchor=W)
    lbl.pack(fill=X, pady=(0, 2))
    return lbl

def make_status_label(parent: tk.Widget, text: str = "Ready") -> ttk.Label:
    """Canonical status label component."""
    lbl = ttk.Label(
        parent,
        text=text,
        foreground=COLOR_TEXT_MUTED,
        font=FONT_BODY,
        anchor=CENTER,
        wraplength=280,
    )
    lbl.pack(fill=X, pady=(4, 4))
    return lbl

def set_status(label: ttk.Label, text: str, level: str = "info") -> None:
    """Map status levels ('info'|'success'|'warning'|'error') to consistent palette colors."""
    color_map = {
        "info": COLOR_TEXT_MUTED,
        "success": COLOR_SUCCESS,
        "warning": COLOR_WARNING,
        "error": COLOR_ERROR,
    }
    color = color_map.get(level.lower(), level if level.startswith("#") else COLOR_TEXT_MUTED)
    label.config(text=text, foreground=color)

def make_progress_bar(parent: tk.Widget) -> ttk.Progressbar:
    """Standard indeterminate striped progress bar factory."""
    bar = ttk.Progressbar(parent, bootstyle="striped-info.TProgressbar", mode="indeterminate")
    bar.pack(fill=X, pady=(4, 4))
    return bar

def make_action_button(
    parent: tk.Widget,
    text: str,
    bootstyle: str = "primary.TButton",
    command: callable = None,
    state: str = "normal",
    width: int = None,
    padding: tuple = (10, 8),
) -> ttk.Button:
    """Unified button factory ensuring consistent sizing and padding across windows."""
    kwargs = {
        "text": text,
        "style": bootstyle,
        "state": state,
        "padding": padding,
    }
    if command is not None:
        kwargs["command"] = command
    if width is not None:
        kwargs["width"] = width

    btn = ttk.Button(parent, **kwargs)
    btn.pack(fill=X, pady=(0, 6))
    return btn

def make_titled_panel(parent: tk.Widget, title: str) -> ttk.LabelFrame:
    """Unified titled section panel factory using ttk.LabelFrame."""
    lf = ttk.LabelFrame(parent, text=title, padding=10)
    lf.configure(style="primary.TLabelframe")
    lf.pack(fill=X, padx=2, pady=5)
    return lf

def make_app_header(
    parent: tk.Widget,
    title: str,
    subtitle: str = None,
    on_return: callable = None,
    on_about: callable = None,
) -> ttk.Frame:
    """Common app header component rendered at the top of windows."""
    header = ttk.Frame(parent, padding=(10, 10, 10, 8))
    header.pack(fill=X, side=TOP)

    if on_return is not None:
        btn_ret = ttk.Button(
            header,
            text="🏠 Return to Launcher",
            bootstyle="secondary-outline",
            command=on_return,
            padding=(8, 4),
        )
        btn_ret.pack(side=LEFT, padx=(0, 15))
        attach_tooltip(btn_ret, "Close this application and return to the launcher menu")

    title_block = ttk.Frame(header)
    title_block.pack(side=LEFT, fill=X, expand=YES)

    t_lbl = ttk.Label(
        title_block,
        text=title,
        font=FONT_TITLE,
        foreground=COLOR_TEXT_HEADER,
        anchor=W if on_return else CENTER,
    )
    t_lbl.pack(fill=X)

    if subtitle:
        sub_text = f"{subtitle}  |  v{__version__}"
        s_lbl = ttk.Label(
            title_block,
            text=sub_text,
            font=FONT_BODY,
            foreground=COLOR_TEXT_MUTED,
            anchor=W if on_return else CENTER,
        )
        s_lbl.pack(fill=X)

    if on_about is not None:
        btn_about = ttk.Button(
            header,
            text="ⓘ About",
            bootstyle="info-outline",
            command=on_about,
            padding=(8, 4),
        )
        btn_about.pack(side=RIGHT, padx=(15, 0))
        attach_tooltip(btn_about, "Show Lee Research Group Suite version and application info")

    ttk.Separator(parent, orient=HORIZONTAL).pack(fill=X, pady=(0, 5))
    return header

def make_app_footer(parent: tk.Widget) -> ttk.Label:
    """Persistent lab attribution footer placed at the bottom of screens."""
    footer = ttk.Label(
        parent,
        text="Lee Research Group — University of St. Thomas",
        font=FONT_SMALL,
        foreground="#555566",
        anchor=CENTER,
        padding=(0, 4, 0, 4),
    )
    footer.pack(fill=X, side=BOTTOM)
    return footer

def show_about_dialog(parent_root: tk.Widget) -> None:
    """Render a modal About dialog displaying lab, suite, and tool details."""
    dialog = ttk.Toplevel(parent_root)
    dialog.title("About — Lee Research Group Tool Suite")
    dialog.geometry("520x480")
    dialog.resizable(False, False)
    dialog.transient(parent_root)
    dialog.grab_set()

    logo_path = get_asset_path("st_thomas_logo.png")
    if os.path.exists(logo_path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(logo_path)
            img.thumbnail((110, 110))
            photo = ImageTk.PhotoImage(img)
            logo_lbl = tk.Label(dialog, image=photo, bg=COLOR_BG_DARK)
            logo_lbl.image = photo
            logo_lbl.pack(pady=(15, 5))
        except Exception:
            pass

    ttk.Label(
        dialog,
        text="Lee Research Group Tool Suite",
        font=FONT_TITLE,
        foreground=COLOR_TEXT_HEADER,
        anchor=CENTER,
    ).pack(fill=X, pady=(5, 2))

    ttk.Label(
        dialog,
        text=f"University of St. Thomas  |  v{__version__}",
        font=FONT_SECTION,
        foreground=COLOR_PRIMARY,
        anchor=CENTER,
    ).pack(fill=X, pady=(0, 8))

    ttk.Separator(dialog, orient=HORIZONTAL).pack(fill=X, padx=20, pady=5)

    desc_frame = ttk.Frame(dialog, padding=(25, 5, 25, 5))
    desc_frame.pack(fill=BOTH, expand=YES)

    tools_info = [
        ("⚙ G-Code Converter & Visualizer", "Convert Aerotech G-Code to PNG with 2D/3D layer path inspection."),
        ("🔬 Line Width Image Analysis", "Automated line width measurement, edge detection, and CV% profiling."),
        ("📊 Surface Roughness Analysis", "Reflectance-based 5x coaxial surface roughness & flat-field corrected CV%."),
    ]

    for tool_title, tool_desc in tools_info:
        t = ttk.Label(desc_frame, text=tool_title, font=FONT_SECTION, foreground=COLOR_SUCCESS)
        t.pack(anchor=W, pady=(4, 0))
        d = ttk.Label(desc_frame, text=tool_desc, font=FONT_BODY, foreground=COLOR_TEXT, wraplength=460)
        d.pack(anchor=W, pady=(0, 6))

    btn_close = ttk.Button(
        dialog,
        text="Close",
        bootstyle="primary",
        padding=(20, 6),
        command=dialog.destroy,
    )
    btn_close.pack(pady=(5, 15))

    dialog.bind("<Escape>", lambda e: dialog.destroy())
