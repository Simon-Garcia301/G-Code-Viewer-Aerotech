#!/usr/bin/env python3
"""
gcode_converter_gui.py
━━━━━━━━━━━━━━━━━━━━━━
Desktop GUI front-end for the Aerotech G-Code → PNG converter.
Includes an interactive 2-D / 3-D layer preview via Matplotlib/TkAgg.
"""

import os
import threading
import subprocess

import tkinter as tk
from tkinter import filedialog

import matplotlib
matplotlib.use('TkAgg')          # must be set before any other matplotlib import

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import mpl_toolkits.mplot3d       # noqa: F401 — registers the '3d' projection

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

from gcode_engine import (
    convert_gcode_to_png,
    preprocess,
    parse_gcode_to_layers,
    PrintLayer,
)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL STATE
# ══════════════════════════════════════════════════════════════════════════════

_output_manually_set: bool = False
_last_browse_dir:     str  = os.path.expanduser("~")
_LATEST_LAYERS:       list = []   # list[PrintLayer], filled after parsing


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _set_entry(widget: ttk.Entry, text: str) -> None:
    widget.config(state="normal")
    widget.delete(0, tk.END)
    widget.insert(0, text)
    widget.config(state="readonly")


def _set_status(label: ttk.Label, text: str, colour: str = "#888888") -> None:
    label.config(text=text, foreground=colour)


def _open_folder(path: str) -> None:
    if os.path.isdir(path):
        subprocess.Popen(f'explorer "{path}"')


def _update_convert_btn(input_var, output_var, btn) -> None:
    btn.config(
        state="normal" if (input_var.get() and output_var.get()) else "disabled"
    )


def _clean_dnd_path(raw: str) -> str:
    path = raw.strip()
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]
    return path


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSE CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

def browse_input(input_var, output_var, input_entry, output_entry, btn):
    global _last_browse_dir, _output_manually_set
    path = filedialog.askopenfilename(
        title="Select G-Code File",
        initialdir=_last_browse_dir,
        filetypes=[
            ("G-Code / AeroScript", "*.gcode *.nc *.gco *.cnc *.txt *.ascript"),
            ("All files", "*.*"),
        ],
    )
    if not path:
        return
    path = os.path.normpath(path)
    _last_browse_dir = os.path.dirname(path)
    _set_entry(input_entry, path)
    input_var.set(path)
    if not _output_manually_set:
        folder = os.path.dirname(path)
        _set_entry(output_entry, folder)
        output_var.set(folder)
    _update_convert_btn(input_var, output_var, btn)


def browse_output(input_var, output_var, output_entry, btn):
    global _last_browse_dir, _output_manually_set
    folder = filedialog.askdirectory(
        title="Select Output Folder",
        initialdir=output_var.get() or _last_browse_dir,
    )
    if not folder:
        return
    folder = os.path.normpath(folder)
    _last_browse_dir     = folder
    _output_manually_set = True
    _set_entry(output_entry, folder)
    output_var.set(folder)
    _update_convert_btn(input_var, output_var, btn)


# ══════════════════════════════════════════════════════════════════════════════
#  DRAG-AND-DROP
# ══════════════════════════════════════════════════════════════════════════════

def on_file_drop(event, input_var, output_var, input_entry, output_entry,
                 btn, trigger_parse_cb):
    global _output_manually_set
    path = _clean_dnd_path(event.data)
    ext  = os.path.splitext(path)[1].lower()
    if ext not in (".gcode", ".nc", ".gco", ".cnc", ".txt", ".ascript"):
        return
    path = os.path.normpath(path)
    _set_entry(input_entry, path)
    input_var.set(path)
    if not _output_manually_set:
        folder = os.path.dirname(path)
        _set_entry(output_entry, folder)
        output_var.set(folder)
    _update_convert_btn(input_var, output_var, btn)
    trigger_parse_cb()


# ══════════════════════════════════════════════════════════════════════════════
#  STATIC PNG CONVERSION
# ══════════════════════════════════════════════════════════════════════════════

def run_conversion(
    input_var, output_var,
    bed_w_var, bed_h_var,
    convert_btn, progress_bar,
    status_label, root,
    parse_and_preview_cb,
):
    gcode_path    = input_var.get().strip()
    output_folder = output_var.get().strip()

    if not gcode_path:
        _set_status(status_label, "Error: No input file selected.", "red"); return
    if not os.path.isfile(gcode_path):
        _set_status(status_label, "Error: File not found.", "red"); return
    if not output_folder:
        _set_status(status_label, "Error: No output folder selected.", "red"); return

    try:
        bed_w = float(bed_w_var.get()) if bed_w_var.get().strip() else None
        bed_h = float(bed_h_var.get()) if bed_h_var.get().strip() else None
    except ValueError:
        _set_status(status_label, "Error: Bed dimensions must be numbers.", "red")
        return

    convert_btn.config(state="disabled")
    _set_status(status_label, "Converting to PNG…", "#f0c040")
    progress_bar.start(12)

    threading.Thread(
        target=_png_worker,
        args=(gcode_path, output_folder, bed_w, bed_h,
              convert_btn, progress_bar, status_label, root,
              parse_and_preview_cb),
        daemon=True,
    ).start()


def _png_worker(gcode_path, output_folder, bed_w, bed_h,
                convert_btn, progress_bar, status_label, root,
                parse_and_preview_cb):
    result = convert_gcode_to_png(gcode_path, output_folder,
                                  bed_w=bed_w, bed_h=bed_h)
    root.after(0, _png_done, result, output_folder,
               convert_btn, progress_bar, status_label, parse_and_preview_cb)


def _png_done(result, output_folder, convert_btn, progress_bar,
              status_label, parse_and_preview_cb):
    progress_bar.stop()
    progress_bar["value"] = 0
    if result == "SUCCESS":
        _set_status(
            status_label,
            f"PNG saved to: {output_folder}  — loading interactive preview…",
            "#44dd88",
        )
        parse_and_preview_cb()
    else:
        _set_status(status_label, result, "red")
        convert_btn.config(state="normal")


# ══════════════════════════════════════════════════════════════════════════════
#  LAYERED PARSE + INTERACTIVE PREVIEW
# ══════════════════════════════════════════════════════════════════════════════

def _start_parse_and_preview(
    input_var, bed_w_var, bed_h_var,
    convert_btn, status_label,
    layer_slider, snapshot_btn,
    fig, canvas, view_mode_var,
    root,
):
    """Validate inputs, then launch the background parse thread."""
    gcode_path = input_var.get().strip()
    if not gcode_path or not os.path.isfile(gcode_path):
        _set_status(status_label, "Error: No valid input file.", "red")
        return

    try:
        bed_w = float(bed_w_var.get()) if bed_w_var.get().strip() else None
        bed_h = float(bed_h_var.get()) if bed_h_var.get().strip() else None
    except ValueError:
        bed_w = bed_h = None   # preview continues without bed outline

    convert_btn.config(state="disabled")
    _set_status(status_label, "Parsing G-code…", "#f0c040")

    threading.Thread(
        target=_parse_worker,
        args=(gcode_path, bed_w, bed_h,
              convert_btn, status_label,
              layer_slider, snapshot_btn,
              fig, canvas, view_mode_var, root),
        daemon=True,
    ).start()


def _parse_worker(
    gcode_path, bed_w, bed_h,
    convert_btn, status_label,
    layer_slider, snapshot_btn,
    fig, canvas, view_mode_var, root,
):
    """Background thread: parse, then schedule UI update on the main thread."""
    try:
        with open(gcode_path, 'r', encoding='utf-8', errors='replace') as fh:
            raw = fh.read()
        lines         = preprocess(raw)
        layers, state = parse_gcode_to_layers(lines)
        root.after(
            0, _on_parsing_done,
            layers, bed_w, bed_h, state,
            convert_btn, status_label,
            layer_slider, snapshot_btn,
            fig, canvas, view_mode_var,
        )
    except Exception as exc:
        root.after(
            0, _on_parsing_error,
            f"Parse error: {type(exc).__name__}: {exc}",
            convert_btn, status_label,
        )


def _on_parsing_done(
    layers, bed_w, bed_h, state,
    convert_btn, status_label,
    layer_slider, snapshot_btn,
    fig, canvas, view_mode_var,
):
    """Main-thread callback: update all widgets after successful parse."""
    global _LATEST_LAYERS
    _LATEST_LAYERS = layers

    if not layers:
        _on_parsing_error(
            "Warning: No motion data found in file.",
            convert_btn, status_label,
        )
        return

    # Always reset to "2D Top" on a fresh load so the user gets a clean start.
    # This also ensures the slider is re-enabled if it was previously disabled
    # by "3D All Layers" mode during a prior session.
    view_mode_var.set("2D Top")

    # Configure slider — always re-enable it since we just reset to "2D Top"
    n_layers = len(layers)
    layer_slider.config(state="normal", from_=0, to=max(n_layers - 1, 0))
    layer_slider.set(0)

    # Resolve bed dimensions (may have been passed as None)
    try:
        bw = float(bed_w) if bed_w is not None else None
        bh = float(bed_h) if bed_h is not None else None
    except (TypeError, ValueError):
        bw = bh = None

    # Render layer 0 in 2D Top mode
    _redraw_preview(
        layer_idx    = 0,
        fig          = fig,
        canvas       = canvas,
        view_mode_var= view_mode_var,
        layer_slider = layer_slider,
        bed_w        = bw,
        bed_h        = bh,
        unit_label   = "mm" if state.unit_mm else "in",
    )

    snapshot_btn.config(state="normal")
    convert_btn.config(state="normal")
    _set_status(
        status_label,
        f"Ready — {n_layers} layer(s) loaded.  Interactive preview active.",
        "#44dd88",
    )


def _on_parsing_error(message, convert_btn, status_label):
    """Main-thread callback: show error and re-enable the convert button."""
    _set_status(status_label, message, "red")
    convert_btn.config(state="normal")


# ══════════════════════════════════════════════════════════════════════════════
#  REDRAW  (called from main thread only)
# ══════════════════════════════════════════════════════════════════════════════

def _redraw_preview(
    layer_idx     = None,
    fig           = None,
    canvas        = None,
    view_mode_var = None,
    layer_slider  = None,
    bed_w         = None,
    bed_h         = None,
    unit_label    = "mm",
):
    """Clear *fig*, draw the requested layer/all-layers, and refresh *canvas*."""
    if not _LATEST_LAYERS:
        return

    mode = view_mode_var.get() if view_mode_var is not None else "2D Top"

    fig.clear()
    fig.patch.set_facecolor('#1e1e2e')

    if mode == "3D All Layers":
        # All-layers stacked view — no single layer needed
        ax = fig.add_subplot(111, projection='3d')
        _draw_3d_all_layers(ax, bed_w, bed_h, unit_label)
    else:
        # Resolve index for single-layer modes
        if layer_idx is None:
            try:
                layer_idx = int(float(layer_slider.get()))
            except Exception:
                layer_idx = 0
        layer_idx = max(0, min(layer_idx, len(_LATEST_LAYERS) - 1))
        layer     = _LATEST_LAYERS[layer_idx]

        if mode == "3D Interactive":
            ax = fig.add_subplot(111, projection='3d')
            _draw_3d(ax, layer, bed_w, bed_h, unit_label, layer_idx)
        else:
            ax = fig.add_subplot(111)
            _draw_2d(ax, layer, bed_w, bed_h, unit_label, layer_idx)

    fig.tight_layout()
    canvas.draw()


# ── 2-D draw ──────────────────────────────────────────────────────────────────

def _draw_2d(ax, layer: PrintLayer, bed_w, bed_h, unit_label, layer_idx):
    ax.set_facecolor('#1e1e2e')
    ax.set_title(
        f"Layer {layer_idx}  –  Z = {layer.z:.4f} {unit_label}  [2D Top View]",
        color='#eeeeff', fontsize=12, fontweight='bold', pad=8,
    )

    # Travel segments
    for seg in layer.travel_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        ax.plot(xs, ys, color='#888888', linewidth=0.9,
                linestyle='--', alpha=0.55, zorder=2)

    # Print segments
    for seg in layer.print_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        ax.plot(xs, ys, color='#ff8844', linewidth=1.6,
                solid_capstyle='round', zorder=3)

    # Bed outline
    if bed_w is not None and bed_h is not None:
        import matplotlib.patches as mpatches
        rect = mpatches.Rectangle(
            (0, 0), bed_w, bed_h,
            linewidth=1.4, edgecolor='#66aaff',
            facecolor='none', linestyle='--', zorder=1,
        )
        ax.add_patch(rect)

    # Legend
    handles = [
        Line2D([0], [0], color='#888888', linewidth=1.0, linestyle='--',
               label='Travel (G0)'),
        Line2D([0], [0], color='#ff8844', linewidth=2.0,
               label='Print (G1/G2/G3)'),
    ]
    if bed_w is not None and bed_h is not None:
        handles.append(
            Line2D([0], [0], color='#66aaff', linewidth=1.4, linestyle='--',
                   label=f'Bed ({bed_w}×{bed_h} {unit_label})')
        )
    ax.legend(handles=handles, loc='upper right',
              facecolor='#2a2a3e', edgecolor='#666688',
              labelcolor='#cccccc', fontsize=8)

    # Axis styling
    ax.grid(True, color='#444466', linewidth=0.4, linestyle=':', alpha=0.7)
    ax.tick_params(colors='#cccccc')
    for spine in ax.spines.values():
        spine.set_edgecolor('#666688')
    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=10)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=10)
    ax.set_aspect('equal', adjustable='datalim')


# ── 3-D draw (single layer) ───────────────────────────────────────────────────

def _draw_3d(ax, layer: PrintLayer, bed_w, bed_h, unit_label, layer_idx):
    ax.set_facecolor('#1e1e2e')
    ax.set_title(
        f"Layer {layer_idx}  –  Z = {layer.z:.4f} {unit_label}  [3D Interactive]",
        color='#eeeeff', fontsize=12, fontweight='bold', pad=8,
    )

    z_val = layer.z

    # Travel segments
    for seg in layer.travel_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        zs     = [z_val] * len(xs)
        ax.plot(xs, ys, zs, color='#888888', linewidth=0.9,
                linestyle='--', alpha=0.55)

    # Print segments
    for seg in layer.print_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        zs     = [z_val] * len(xs)
        ax.plot(xs, ys, zs, color='#ff8844', linewidth=1.6,
                solid_capstyle='round')

    # Bed outline at Z = 0
    if bed_w is not None and bed_h is not None:
        bx = [0, bed_w, bed_w,    0, 0]
        by = [0,     0, bed_h, bed_h, 0]
        bz = [0,     0,     0,     0, 0]
        ax.plot(bx, by, bz, color='#66aaff', linewidth=1.4, linestyle='--')

    # Viewpoint
    ax.view_init(elev=25, azim=-60)

    # Axis styling
    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_zlabel(f"Z ({unit_label})", color='#cccccc', fontsize=9)
    ax.tick_params(colors='#cccccc', labelsize=7)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor('#444466')
    ax.yaxis.pane.set_edgecolor('#444466')
    ax.zaxis.pane.set_edgecolor('#444466')
    ax.grid(True, color='#444466', linewidth=0.3, linestyle=':')


# ── 3-D draw (all layers stacked) ────────────────────────────────────────────
def _draw_3d_all_layers(ax, bed_w, bed_h, unit_label):
    global _LATEST_LAYERS

    n_layers = len(_LATEST_LAYERS)
    if n_layers == 0:
        return

    # ── Colormap (compatible with modern matplotlib) ──────────────────────
    cmap = plt.get_cmap('plasma')          # instead of cm.get_cmap()
    norm = mcolors.Normalize(vmin=0, vmax=max(n_layers - 1, 1))
    layer_rgba = [cmap(norm(i)) for i in range(n_layers)]

    # ── Collect all points to compute bounding box ────────────────────────
    all_x, all_y, all_z = [], [], []

    for i, layer in enumerate(_LATEST_LAYERS):
        z_val = layer.z
        color = layer_rgba[i]

        # Travel segments
        for seg in layer.travel_segments:
            if len(seg) < 2:
                continue
            xs, ys = zip(*seg)
            zs = [z_val] * len(xs)
            all_x.extend(xs)
            all_y.extend(ys)
            all_z.extend(zs)
            ax.plot(xs, ys, zs,
                    color='#888888', linewidth=0.7,
                    linestyle='--', alpha=0.40)

        # Print segments
        for seg in layer.print_segments:
            if len(seg) < 2:
                continue
            xs, ys = zip(*seg)
            zs = [z_val] * len(xs)
            all_x.extend(xs)
            all_y.extend(ys)
            all_z.extend(zs)
            ax.plot(xs, ys, zs,
                    color=color, linewidth=1.4,
                    solid_capstyle='round', alpha=0.85)

    # ── Bed outline at Z=0 ────────────────────────────────────────────────
    if bed_w is not None and bed_h is not None:
        bx = [0, bed_w, bed_w,    0, 0]
        by = [0,     0, bed_h, bed_h, 0]
        bz = [0,     0,     0,     0, 0]
        ax.plot(bx, by, bz, color='#66aaff', linewidth=1.4, linestyle='--')
        all_x.extend([0, bed_w])
        all_y.extend([0, bed_h])
        all_z.extend([0])

    # ── Set axis limits from collected data ───────────────────────────────
    if all_x:
        x_min, x_max = min(all_x), max(all_x)
        y_min, y_max = min(all_y), max(all_y)
        z_min, z_max = min(all_z), max(all_z)

        x_pad = max(0.05 * (x_max - x_min), 0.5)
        y_pad = max(0.05 * (y_max - y_min), 0.5)
        z_pad = max(0.05 * (z_max - z_min), 0.5)

        ax.set_xlim(x_min - x_pad, x_max + x_pad)
        ax.set_ylim(y_min - y_pad, y_max + y_pad)
        ax.set_zlim(z_min - z_pad, z_max + z_pad)

    # ── Title ─────────────────────────────────────────────────────────────
    ax.set_title(
        f"All Layers – 3D Stacked View  [{n_layers} layer(s)]  ({unit_label})",
        color='#eeeeff', fontsize=12, fontweight='bold', pad=8,
    )

    # ── Legend (unchanged) ────────────────────────────────────────────────
    first_color = layer_rgba[0]
    last_color  = layer_rgba[-1]

    handles = [
        Line2D([0], [0], color='#888888', linewidth=1.0, linestyle='--',
               alpha=0.70, label='Travel (G0)'),
        Line2D([0], [0], color=first_color, linewidth=2.0,
               label=f'Print – layer 0  (G1/G2/G3)'),
        Line2D([0], [0], color=last_color,  linewidth=2.0,
               label=f'Print – layer {n_layers - 1}  (G1/G2/G3)'),
        Line2D([0], [0], color='none',
               label='↑ Colors vary by layer (plasma)'),
    ]
    if bed_w is not None and bed_h is not None:
        handles.append(
            Line2D([0], [0], color='#66aaff', linewidth=1.4, linestyle='--',
                   label=f'Bed ({bed_w}×{bed_h} {unit_label})')
        )

    ax.legend(
        handles=handles,
        loc='upper right',
        facecolor='#2a2a3e',
        edgecolor='#666688',
        labelcolor='#cccccc',
        fontsize=7,
    )

    # ── Viewpoint and styling ─────────────────────────────────────────────
    ax.view_init(elev=25, azim=-60)

    ax.set_facecolor('#1e1e2e')
    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_zlabel(f"Z ({unit_label})", color='#cccccc', fontsize=9)
    ax.tick_params(colors='#cccccc', labelsize=7)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor('#444466')
    ax.yaxis.pane.set_edgecolor('#444466')
    ax.zaxis.pane.set_edgecolor('#444466')
    ax.grid(True, color='#444466', linewidth=0.3, linestyle=':')

# ══════════════════════════════════════════════════════════════════════════════
#  SNAPSHOT
# ══════════════════════════════════════════════════════════════════════════════

def _save_snapshot(fig: Figure, output_var, status_label) -> None:
    initial_dir = output_var.get() or os.path.expanduser("~")
    path = filedialog.asksaveasfilename(
        title="Save Snapshot",
        initialdir=initial_dir,
        defaultextension=".png",
        filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        fig.savefig(path, dpi=300, bbox_inches='tight',
                    facecolor=fig.get_facecolor())
        _set_status(status_label, f"Snapshot saved: {path}", "#44dd88")
    except Exception as exc:
        _set_status(status_label, f"Save failed: {exc}", "red")


# ══════════════════════════════════════════════════════════════════════════════
#  GUI CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════

def build_gui() -> ttk.Window:

    root = ttk.Window(
        title="G-Code Converter & 3D Preview",
        themename="darkly",
        size=(1000, 800),
        resizable=(True, True),
    )
    if DND_AVAILABLE:
        TkinterDnD.require(root)

    # ── StringVars ─────────────────────────────────────────────────────────────
    input_var     = tk.StringVar()
    output_var    = tk.StringVar()
    bed_w_var     = tk.StringVar()
    bed_h_var     = tk.StringVar()
    view_mode_var = tk.StringVar(value="2D Top")

    # ── Mutable single-element lists used as mutable cells ────────────────────
    # (so lambdas defined before the widget exists can still reference it)
    _btn_cell    = [None]   # convert button
    _snap_cell   = [None]   # snapshot button
    _slider_cell = [None]   # layer slider
    _fig_cell    = [None]   # Figure
    _canvas_cell = [None]   # FigureCanvasTkAgg
    _label_cell  = [None]   # layer-index label beside slider
    _status_cell = [None]   # status label (needed by slider callback)
    _bedw_cell   = [bed_w_var]
    _bedh_cell   = [bed_h_var]

    # ── Outer frame (grid layout for resizability) ────────────────────────────
    outer = ttk.Frame(root, padding=(20, 14, 20, 14))
    outer.pack(fill=BOTH, expand=YES)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(10, weight=1)   # canvas row expands

    # ── Header ─────────────────────────────────────────────────────────────────
    ttk.Label(
        outer,
        text="G-Code Converter & Interactive Preview",
        font=("Segoe UI", 17, "bold"),
        anchor=CENTER,
    ).grid(row=0, column=0, sticky=EW, pady=(0, 4))
    ttk.Separator(outer, orient=HORIZONTAL).grid(
        row=1, column=0, sticky=EW, pady=(0, 10))

    # ── Row helper ─────────────────────────────────────────────────────────────
    def make_row(parent, label_text, row_num, label_width=16):
        frame = ttk.Frame(parent)
        frame.grid(row=row_num, column=0, sticky=EW, pady=(0, 6))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=label_text,
                  width=label_width, anchor=W).grid(row=0, column=0, sticky=W)
        return frame

    # ── 1. Input file ──────────────────────────────────────────────────────────
    row1        = make_row(outer, "G-Code File:", row_num=2)
    input_entry = ttk.Entry(row1, textvariable=input_var,
                            state="readonly", style="secondary.TEntry")
    input_entry.grid(row=0, column=1, sticky=EW, padx=(4, 6))
    ttk.Button(
        row1, text="Browse", bootstyle="primary-outline",
        command=lambda: browse_input(
            input_var, output_var, input_entry, output_entry, _btn_cell[0]),
    ).grid(row=0, column=2)

    # Placeholder text
    _PH = "Drop G-code file here…"
    def _show_ph():
        if not input_var.get():
            input_entry.config(state="normal")
            input_entry.delete(0, tk.END)
            input_entry.insert(0, _PH)
            input_entry.config(state="readonly", foreground="#888888")
    root.after(50, _show_ph)

    # ── 2. Output folder ───────────────────────────────────────────────────────
    row2         = make_row(outer, "Output Folder:", row_num=3)
    output_entry = ttk.Entry(row2, textvariable=output_var,
                             state="readonly", style="secondary.TEntry")
    output_entry.grid(row=0, column=1, sticky=EW, padx=(4, 6))
    ttk.Button(
        row2, text="Browse", bootstyle="primary-outline",
        command=lambda: browse_output(
            input_var, output_var, output_entry, _btn_cell[0]),
    ).grid(row=0, column=2)

    # ── 3. Bed size ────────────────────────────────────────────────────────────
    row3 = make_row(outer, "Bed Size (W × H):", row_num=4)
    ttk.Entry(row3, textvariable=bed_w_var, width=10).grid(
        row=0, column=1, sticky=W, padx=(4, 4))
    ttk.Label(row3, text="×", foreground="#aaaaaa").grid(
        row=0, column=2, padx=(0, 4))
    ttk.Entry(row3, textvariable=bed_h_var, width=10).grid(
        row=0, column=3, sticky=W, padx=(0, 6))
    ttk.Label(row3, text="mm  (optional)", foreground="#888888",
              font=("Segoe UI", 9)).grid(row=0, column=4, sticky=W)

    # ── Separator ──────────────────────────────────────────────────────────────
    ttk.Separator(outer, orient=HORIZONTAL).grid(
        row=5, column=0, sticky=EW, pady=(6, 10))

    # ── View-mode radio buttons ────────────────────────────────────────────────
    radio_frame = ttk.Frame(outer)
    radio_frame.grid(row=6, column=0, sticky=W, pady=(0, 6))
    ttk.Label(radio_frame, text="Preview mode:",
              foreground="#cccccc", font=("Segoe UI", 10)).pack(
        side=LEFT, padx=(0, 10))

    def _on_mode_change():
        """Redraw whenever the user switches view mode."""
        if not _LATEST_LAYERS:
            return

        mode = view_mode_var.get()

        # ── Disable/enable the layer slider based on mode ─────────────────────
        # "3D All Layers" renders everything at once; the per-layer slider is
        # meaningless in that context, so we disable it to avoid confusion.
        if mode == "3D All Layers":
            _slider_cell[0].config(state="disabled")
        else:
            _slider_cell[0].config(state="normal")

        try:
            bw = float(bed_w_var.get()) if bed_w_var.get().strip() else None
            bh = float(bed_h_var.get()) if bed_h_var.get().strip() else None
        except ValueError:
            bw = bh = None

        _redraw_preview(
            layer_idx    = int(float(_slider_cell[0].get())),
            fig          = _fig_cell[0],
            canvas       = _canvas_cell[0],
            view_mode_var= view_mode_var,
            layer_slider = _slider_cell[0],
            bed_w        = bw,
            bed_h        = bh,
        )

    # Three radio buttons: "2D Top", "3D Interactive", "3D All Layers"
    for mode_text in ("2D Top", "3D Interactive", "3D All Layers"):
        ttk.Radiobutton(
            radio_frame,
            text=mode_text,
            variable=view_mode_var,
            value=mode_text,
            bootstyle="info-toolbutton",
            command=_on_mode_change,
        ).pack(side=LEFT, padx=(0, 6))

    # ── Layer slider ───────────────────────────────────────────────────────────
    slider_frame = ttk.Frame(outer)
    slider_frame.grid(row=7, column=0, sticky=EW, pady=(0, 6))
    slider_frame.columnconfigure(1, weight=1)

    ttk.Label(slider_frame, text="Layer:", foreground="#cccccc",
              font=("Segoe UI", 10), width=7).grid(row=0, column=0, sticky=W)

    layer_index_label = ttk.Label(slider_frame, text="–",
                                  foreground="#aaaaaa", width=8, anchor=W)

    def _on_slider_change(val):
        idx = int(float(val))
        if _LATEST_LAYERS:
            layer_index_label.config(
                text=f"{idx} / {max(len(_LATEST_LAYERS) - 1, 0)}"
            )
        if not _LATEST_LAYERS or _fig_cell[0] is None:
            return
        # Guard: do not respond to slider drags while in "3D All Layers" mode.
        # The slider is disabled in that mode but the callback can still fire
        # programmatically (e.g. layer_slider.set(0) in _on_parsing_done).
        if view_mode_var.get() == "3D All Layers":
            return
        try:
            bw = float(bed_w_var.get()) if bed_w_var.get().strip() else None
            bh = float(bed_h_var.get()) if bed_h_var.get().strip() else None
        except ValueError:
            bw = bh = None
        _redraw_preview(
            layer_idx    = idx,
            fig          = _fig_cell[0],
            canvas       = _canvas_cell[0],
            view_mode_var= view_mode_var,
            layer_slider = _slider_cell[0],
            bed_w        = bw,
            bed_h        = bh,
        )

    layer_slider = ttk.Scale(
        slider_frame,
        from_=0, to=0,
        orient=HORIZONTAL,
        state="disabled",
        bootstyle="info",
        command=_on_slider_change,
    )
    layer_slider.grid(row=0, column=1, sticky=EW, padx=(6, 6))
    layer_index_label.grid(row=0, column=2, sticky=W)
    _slider_cell[0] = layer_slider

    # ── Convert button (row 8) ─────────────────────────────────────────────────
    # The button is created here; its command is a lambda that closes over
    # widgets created both above and below this point via the cell pattern.
    convert_btn = ttk.Button(
        outer,
        text="Convert to PNG  +  Load Preview",
        bootstyle="success",
        state="disabled",
        padding=(16, 8),
    )
    convert_btn.grid(row=8, column=0, pady=(0, 6))
    _btn_cell[0] = convert_btn

    # Wire up command now that _btn_cell[0] is set (the lambda reads cells
    # at call time, not at definition time, so forward references are fine)
    def _convert_cmd():
        run_conversion(
            input_var, output_var,
            bed_w_var, bed_h_var,
            _btn_cell[0], progress_bar,
            _status_cell[0], root,
            parse_and_preview_cb=lambda: _start_parse_and_preview(
                input_var, bed_w_var, bed_h_var,
                _btn_cell[0], _status_cell[0],
                _slider_cell[0], _snap_cell[0],
                _fig_cell[0], _canvas_cell[0],
                view_mode_var, root,
            ),
        )
    convert_btn.config(command=_convert_cmd)

    # ── Progress bar (row 9) ───────────────────────────────────────────────────
    progress_bar = ttk.Progressbar(
        outer, bootstyle="info-striped", mode="indeterminate")
    progress_bar.grid(row=9, column=0, sticky=EW, pady=(0, 4))

    # ── Matplotlib canvas frame (row 10, expands) ──────────────────────────────
    canvas_frame = ttk.Frame(outer, relief="sunken", borderwidth=1)
    canvas_frame.grid(row=10, column=0, sticky=NSEW, pady=(0, 6))

    # Initial placeholder figure
    fig = Figure(figsize=(9, 5), facecolor='#1e1e2e')
    _ax0 = fig.add_subplot(111)
    _ax0.set_facecolor('#1e1e2e')
    _ax0.set_title("Load a G-code file to see the preview",
                   color='#555577', fontsize=11)
    _ax0.tick_params(colors='#333355')
    for sp in _ax0.spines.values():
        sp.set_edgecolor('#333355')
    _fig_cell[0] = fig

    # Embed canvas
    canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=BOTH, expand=True)
    _canvas_cell[0] = canvas

    # Navigation toolbar
    toolbar_frame = ttk.Frame(canvas_frame)
    toolbar_frame.pack(fill=X, side=BOTTOM)
    NavigationToolbar2Tk(canvas, toolbar_frame).update()

    # ── Bottom button row (row 11) ─────────────────────────────────────────────
    btn_row = ttk.Frame(outer)
    btn_row.grid(row=11, column=0, sticky=EW, pady=(0, 4))

    snapshot_btn = ttk.Button(
        btn_row,
        text="💾  Save Snapshot",
        bootstyle="secondary",
        state="disabled",
        command=lambda: _save_snapshot(
            _fig_cell[0], output_var, _status_cell[0]),
    )
    snapshot_btn.pack(side=LEFT, padx=(0, 10))
    _snap_cell[0] = snapshot_btn

    ttk.Button(
        btn_row,
        text="📂  Open Output Folder",
        bootstyle="secondary",
        command=lambda: _open_folder(output_var.get()),
    ).pack(side=LEFT)

    # ── Status label (row 12) ─────────────────────────────────────────────────
    status_label = ttk.Label(
        outer,
        text="Ready",
        foreground="#888888",
        font=("Segoe UI", 10),
        anchor=CENTER,
    )
    status_label.grid(row=12, column=0, sticky=EW, pady=(0, 2))
    _status_cell[0] = status_label

    # ── Reactive convert-button enable/disable ────────────────────────────────
    input_var.trace_add("write",
        lambda *_: _update_convert_btn(input_var, output_var, convert_btn))
    output_var.trace_add("write",
        lambda *_: _update_convert_btn(input_var, output_var, convert_btn))

    # ── Drag-and-drop (wired after all widgets exist) ─────────────────────────
    if DND_AVAILABLE:
        input_entry.drop_target_register(DND_FILES)
        input_entry.dnd_bind(
            "<<Drop>>",
            lambda e: on_file_drop(
                e, input_var, output_var,
                input_entry, output_entry, convert_btn,
                trigger_parse_cb=lambda: _start_parse_and_preview(
                    input_var, bed_w_var, bed_h_var,
                    _btn_cell[0], _status_cell[0],
                    _slider_cell[0], _snap_cell[0],
                    _fig_cell[0], _canvas_cell[0],
                    view_mode_var, root,
                ),
            ),
        )

    return root


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    build_gui().mainloop()


if __name__ == "__main__":
    main()
