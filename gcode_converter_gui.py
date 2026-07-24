#!/usr/bin/env python3
"""
gcode_converter_gui.py
━━━━━━━━━━━━━━━━━━━━━━
Desktop GUI front-end for the Aerotech G-Code → PNG converter.
Refactored to consume ui_common shared components, styling, header, and footer.
"""

import os
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog

import matplotlib
matplotlib.use('TkAgg')

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import mpl_toolkits.mplot3d  # noqa: F401

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
from ui_common import (
    make_app_header,
    make_app_footer,
    make_scrollable_left_panel,
    make_titled_panel,
    section_label,
    small_label,
    make_status_label,
    set_status,
    make_progress_bar,
    make_action_button,
    attach_tooltip,
    load_app_icon,
    show_about_dialog,
)

_output_manually_set: bool = False
_last_browse_dir: str = os.path.expanduser("~")
_LATEST_LAYERS: list = []
_layer_buttons: list = []
_active_layer_idx: int = 0

def _set_entry(widget: ttk.Entry, text: str) -> None:
    widget.config(state="normal")
    widget.delete(0, tk.END)
    widget.insert(0, text)
    widget.config(state="readonly")

def _open_folder(path: str) -> None:
    if os.path.isdir(path):
        subprocess.Popen(f'explorer "{os.path.normpath(path)}"')

def _update_convert_btn(input_var, output_var, btn) -> None:
    btn.config(state="normal" if (input_var.get() and output_var.get()) else "disabled")

def _clean_dnd_path(raw: str) -> str:
    path = raw.strip()
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]
    return path

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
    _last_browse_dir = folder
    _output_manually_set = True
    _set_entry(output_entry, folder)
    output_var.set(folder)
    _update_convert_btn(input_var, output_var, btn)

def on_file_drop(event, input_var, output_var, input_entry, output_entry, btn, trigger_parse_cb):
    global _output_manually_set
    path = _clean_dnd_path(event.data)
    ext = os.path.splitext(path)[1].lower()
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

def run_conversion(
    input_var, output_var,
    bed_w_var, bed_h_var,
    convert_btn, progress_bar,
    status_label, root,
    parse_and_preview_cb,
):
    gcode_path = input_var.get().strip()
    output_folder = output_var.get().strip()

    if not gcode_path or not os.path.isfile(gcode_path):
        set_status(status_label, "Error: Valid G-code file required.", "error")
        return
    if not output_folder:
        set_status(status_label, "Error: Select an output folder.", "error")
        return

    try:
        bed_w = float(bed_w_var.get()) if bed_w_var.get().strip() else None
        bed_h = float(bed_h_var.get()) if bed_h_var.get().strip() else None
    except ValueError:
        set_status(status_label, "Error: Bed dimensions must be numeric.", "error")
        return

    convert_btn.config(state="disabled")
    set_status(status_label, "Converting G-code to PNG...", "warning")
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
    result = convert_gcode_to_png(gcode_path, output_folder, bed_w=bed_w, bed_h=bed_h)
    root.after(0, _png_done, result, output_folder,
               convert_btn, progress_bar, status_label, parse_and_preview_cb)

def _png_done(result, output_folder, convert_btn, progress_bar,
              status_label, parse_and_preview_cb):
    progress_bar.stop()
    progress_bar["value"] = 0
    if result == "SUCCESS":
        set_status(status_label, f"PNG saved to: {output_folder} — loading layer preview...", "success")
        parse_and_preview_cb()
    else:
        set_status(status_label, result, "error")
        convert_btn.config(state="normal")

def _start_parse_and_preview(
    input_var, bed_w_var, bed_h_var,
    convert_btn, status_label,
    layer_grid_frame, snapshot_btn,
    fig, canvas, view_mode_var,
    root,
):
    gcode_path = input_var.get().strip()
    if not gcode_path or not os.path.isfile(gcode_path):
        set_status(status_label, "Error: Valid G-code file required.", "error")
        return

    try:
        bed_w = float(bed_w_var.get()) if bed_w_var.get().strip() else None
        bed_h = float(bed_h_var.get()) if bed_h_var.get().strip() else None
    except ValueError:
        bed_w = bed_h = None

    convert_btn.config(state="disabled")
    set_status(status_label, "Parsing G-code layers...", "warning")

    threading.Thread(
        target=_parse_worker,
        args=(gcode_path, bed_w, bed_h,
              convert_btn, status_label,
              layer_grid_frame, snapshot_btn,
              fig, canvas, view_mode_var, root),
        daemon=True,
    ).start()

def _parse_worker(
    gcode_path, bed_w, bed_h,
    convert_btn, status_label,
    layer_grid_frame, snapshot_btn,
    fig, canvas, view_mode_var, root,
):
    try:
        with open(gcode_path, 'r', encoding='utf-8', errors='replace') as fh:
            raw = fh.read()
        lines = preprocess(raw)
        layers, state = parse_gcode_to_layers(lines)
        root.after(
            0, _on_parsing_done,
            layers, bed_w, bed_h, state,
            convert_btn, status_label,
            layer_grid_frame, snapshot_btn,
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
    layer_grid_frame, snapshot_btn,
    fig, canvas, view_mode_var,
):
    global _LATEST_LAYERS, _active_layer_idx
    _LATEST_LAYERS = layers
    _active_layer_idx = 0

    if not layers:
        _on_parsing_error("Warning: No motion data found in file.", convert_btn, status_label)
        return

    view_mode_var.set("2D Top")
    _rebuild_layer_buttons(layer_grid_frame, fig, canvas, view_mode_var, bed_w, bed_h, state)

    try:
        bw = float(bed_w) if bed_w is not None else None
        bh = float(bed_h) if bed_h is not None else None
    except (TypeError, ValueError):
        bw = bh = None

    _redraw_preview(
        layer_idx=0,
        fig=fig,
        canvas=canvas,
        view_mode_var=view_mode_var,
        bed_w=bw,
        bed_h=bh,
        unit_label="mm" if state.unit_mm else "in",
    )

    snapshot_btn.config(state="normal")
    convert_btn.config(state="normal")
    set_status(status_label, f"Ready — {len(layers)} layer(s) loaded. Interactive preview active.", "success")

def _on_parsing_error(message, convert_btn, status_label):
    set_status(status_label, message, "error")
    convert_btn.config(state="normal")

def _rebuild_layer_buttons(parent_frame, fig, canvas, view_mode_var, bed_w, bed_h, state):
    global _layer_buttons, _LATEST_LAYERS, _active_layer_idx

    for btn in _layer_buttons:
        btn.destroy()
    _layer_buttons.clear()

    for child in parent_frame.winfo_children():
        child.destroy()

    n_layers = len(_LATEST_LAYERS)
    if n_layers == 0:
        small_label(parent_frame, "No layer data")
        return

    cols = 5
    grid_inner = ttk.Frame(parent_frame)
    grid_inner.pack(fill=BOTH, expand=True)

    for i in range(n_layers):
        row = i // cols
        col = i % cols

        def make_cmd(idx):
            return lambda: _on_layer_button_click(idx, fig, canvas, view_mode_var, bed_w, bed_h, state)

        btn = ttk.Button(
            grid_inner,
            text=str(i + 1),
            bootstyle="secondary-outline",
            width=5,
            command=make_cmd(i),
        )
        btn.grid(row=row, column=col, padx=2, pady=2, sticky="ew")
        _layer_buttons.append(btn)

    for c in range(cols):
        grid_inner.columnconfigure(c, weight=1)

    _highlight_layer_button(_active_layer_idx)

    z_min = min(l.z for l in _LATEST_LAYERS)
    z_max = max(l.z for l in _LATEST_LAYERS)
    small_label(parent_frame, f"Z Range: {z_min:.2f} – {z_max:.2f} {('mm' if state.unit_mm else 'in')}")

def _highlight_layer_button(layer_idx):
    global _layer_buttons, _active_layer_idx
    _active_layer_idx = layer_idx
    for i, btn in enumerate(_layer_buttons):
        if i == layer_idx:
            btn.configure(bootstyle="primary")
        else:
            btn.configure(bootstyle="secondary-outline")

def _on_layer_button_click(layer_idx, fig, canvas, view_mode_var, bed_w, bed_h, state):
    global _LATEST_LAYERS, _active_layer_idx
    if not _LATEST_LAYERS or layer_idx >= len(_LATEST_LAYERS):
        return

    _active_layer_idx = layer_idx
    if view_mode_var.get() == "3D All Layers":
        view_mode_var.set("2D Top")

    try:
        bw = float(bed_w) if bed_w is not None else None
        bh = float(bed_h) if bed_h is not None else None
    except (TypeError, ValueError):
        bw = bh = None

    _redraw_preview(
        layer_idx=layer_idx,
        fig=fig,
        canvas=canvas,
        view_mode_var=view_mode_var,
        bed_w=bw,
        bed_h=bh,
        unit_label="mm" if state.unit_mm else "in",
    )
    _highlight_layer_button(layer_idx)

def _redraw_preview(
    layer_idx=None,
    fig=None,
    canvas=None,
    view_mode_var=None,
    bed_w=None,
    bed_h=None,
    unit_label="mm",
):
    if not _LATEST_LAYERS:
        return

    mode = view_mode_var.get() if view_mode_var is not None else "2D Top"
    fig.clear()
    fig.patch.set_facecolor('#1e1e2e')

    if mode == "3D All Layers":
        ax = fig.add_subplot(111, projection='3d')
        _draw_3d_all_layers(ax, bed_w, bed_h, unit_label)
    else:
        if layer_idx is None:
            layer_idx = 0
        layer_idx = max(0, min(layer_idx, len(_LATEST_LAYERS) - 1))
        layer = _LATEST_LAYERS[layer_idx]

        if mode == "3D Interactive":
            ax = fig.add_subplot(111, projection='3d')
            _draw_3d(ax, layer, bed_w, bed_h, unit_label, layer_idx)
        else:
            ax = fig.add_subplot(111)
            _draw_2d(ax, layer, bed_w, bed_h, unit_label, layer_idx)

    fig.tight_layout()
    canvas.draw()

def _draw_2d(ax, layer: PrintLayer, bed_w, bed_h, unit_label, layer_idx):
    ax.set_facecolor('#1e1e2e')
    ax.set_title(
        f"Layer {layer_idx + 1}  –  Z = {layer.z:.4f} {unit_label}  [2D Top View]",
        color='#eeeeff', fontsize=12, fontweight='bold', pad=8,
    )

    for seg in layer.travel_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        ax.plot(xs, ys, color='#888888', linewidth=0.9, linestyle='--', alpha=0.55, zorder=2)

    for seg in layer.print_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        ax.plot(xs, ys, color='#ff8844', linewidth=1.6, solid_capstyle='round', zorder=3)

    if bed_w is not None and bed_h is not None:
        import matplotlib.patches as mpatches
        rect = mpatches.Rectangle(
            (0, 0), bed_w, bed_h,
            linewidth=1.4, edgecolor='#66aaff',
            facecolor='none', linestyle='--', zorder=1,
        )
        ax.add_patch(rect)

    handles = [
        Line2D([0], [0], color='#888888', linewidth=1.0, linestyle='--', label='Travel (G0)'),
        Line2D([0], [0], color='#ff8844', linewidth=2.0, label='Print (G1/G2/G3)'),
    ]
    if bed_w is not None and bed_h is not None:
        handles.append(
            Line2D([0], [0], color='#66aaff', linewidth=1.4, linestyle='--', label=f'Bed ({bed_w}×{bed_h} {unit_label})')
        )
    ax.legend(handles=handles, loc='upper right', facecolor='#2a2a3e', edgecolor='#666688', labelcolor='#cccccc', fontsize=8)

    ax.grid(True, color='#444466', linewidth=0.4, linestyle=':', alpha=0.7)
    ax.tick_params(colors='#cccccc')
    for spine in ax.spines.values():
        spine.set_edgecolor('#666688')
    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=10)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=10)
    ax.set_aspect('equal', adjustable='datalim')

def _draw_3d(ax, layer: PrintLayer, bed_w, bed_h, unit_label, layer_idx):
    ax.set_facecolor('#1e1e2e')
    ax.set_title(
        f"Layer {layer_idx + 1}  –  Z = {layer.z:.4f} {unit_label}  [3D Interactive]",
        color='#eeeeff', fontsize=12, fontweight='bold', pad=8,
    )

    z_val = layer.z
    for seg in layer.travel_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        zs = [z_val] * len(xs)
        ax.plot(xs, ys, zs, color='#888888', linewidth=0.9, linestyle='--', alpha=0.55)

    for seg in layer.print_segments:
        if len(seg) < 2:
            continue
        xs, ys = zip(*seg)
        zs = [z_val] * len(xs)
        ax.plot(xs, ys, zs, color='#ff8844', linewidth=1.6, solid_capstyle='round')

    if bed_w is not None and bed_h is not None:
        bx = [0, bed_w, bed_w, 0, 0]
        by = [0, 0, bed_h, bed_h, 0]
        bz = [0, 0, 0, 0, 0]
        ax.plot(bx, by, bz, color='#66aaff', linewidth=1.4, linestyle='--')

    ax.view_init(elev=25, azim=-60)
    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_zlabel(f"Z ({unit_label})", color='#cccccc', fontsize=9)
    ax.tick_params(colors='#cccccc', labelsize=7)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.grid(True, color='#444466', linewidth=0.3, linestyle=':')

def _draw_3d_all_layers(ax, bed_w, bed_h, unit_label):
    global _LATEST_LAYERS
    n_layers = len(_LATEST_LAYERS)
    if n_layers == 0:
        return

    cmap = plt.get_cmap('plasma')
    norm = mcolors.Normalize(vmin=0, vmax=max(n_layers - 1, 1))
    layer_rgba = [cmap(norm(i)) for i in range(n_layers)]

    all_x, all_y, all_z = [], [], []

    for i, layer in enumerate(_LATEST_LAYERS):
        z_val = layer.z
        color = layer_rgba[i]

        for seg in layer.travel_segments:
            if len(seg) < 2:
                continue
            xs, ys = zip(*seg)
            zs = [z_val] * len(xs)
            all_x.extend(xs)
            all_y.extend(ys)
            all_z.extend(zs)
            ax.plot(xs, ys, zs, color='#888888', linewidth=0.7, linestyle='--', alpha=0.40)

        for seg in layer.print_segments:
            if len(seg) < 2:
                continue
            xs, ys = zip(*seg)
            zs = [z_val] * len(xs)
            all_x.extend(xs)
            all_y.extend(ys)
            all_z.extend(zs)
            ax.plot(xs, ys, zs, color=color, linewidth=1.4, solid_capstyle='round', alpha=0.85)

    if bed_w is not None and bed_h is not None:
        bx = [0, bed_w, bed_w, 0, 0]
        by = [0, 0, bed_h, bed_h, 0]
        bz = [0, 0, 0, 0, 0]
        ax.plot(bx, by, bz, color='#66aaff', linewidth=1.4, linestyle='--')
        all_x.extend([0, bed_w])
        all_y.extend([0, bed_h])
        all_z.extend([0])

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

    ax.set_title(f"All Layers – 3D Stacked View  [{n_layers} layer(s)]  ({unit_label})", color='#eeeeff', fontsize=12, fontweight='bold', pad=8)

    handles = [
        Line2D([0], [0], color='#888888', linewidth=1.0, linestyle='--', alpha=0.70, label='Travel (G0)'),
        Line2D([0], [0], color=layer_rgba[0], linewidth=2.0, label='Print – Layer 1 (G1/G2/G3)'),
        Line2D([0], [0], color=layer_rgba[-1], linewidth=2.0, label=f'Print – Layer {n_layers} (G1/G2/G3)'),
    ]
    if bed_w is not None and bed_h is not None:
        handles.append(Line2D([0], [0], color='#66aaff', linewidth=1.4, linestyle='--', label=f'Bed ({bed_w}×{bed_h} {unit_label})'))

    ax.legend(handles=handles, loc='upper right', facecolor='#2a2a3e', edgecolor='#666688', labelcolor='#cccccc', fontsize=7)

    ax.view_init(elev=25, azim=-60)
    ax.set_facecolor('#1e1e2e')
    ax.set_xlabel(f"X ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_ylabel(f"Y ({unit_label})", color='#cccccc', fontsize=9)
    ax.set_zlabel(f"Z ({unit_label})", color='#cccccc', fontsize=9)
    ax.tick_params(colors='#cccccc', labelsize=7)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.grid(True, color='#444466', linewidth=0.3, linestyle=':')

def _save_snapshot(fig: Figure, output_var, status_label) -> None:
    initial_dir = output_var.get() or os.path.expanduser("~")
    path = filedialog.asksaveasfilename(
        title="Save Path Preview Snapshot",
        initialdir=initial_dir,
        defaultextension=".png",
        filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        fig.savefig(path, dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
        set_status(status_label, f"Snapshot saved: {path}", "success")
    except Exception as exc:
        set_status(status_label, f"Save failed: {exc}", "error")

def build_gui(root: ttk.Window = None) -> ttk.Window:
    if root is None:
        root = ttk.Window(
            title="Lee Research Lab — G-Code Converter & Visualizer",
            themename="darkly",
            size=(1400, 900),
            resizable=(True, True),
        )

    load_app_icon(root)

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    bed_w_var = tk.StringVar()
    bed_h_var = tk.StringVar()
    view_mode_var = tk.StringVar(value="2D Top")

    _btn_cell = [None]
    _snap_cell = [None]
    _fig_cell = [None]
    _canvas_cell = [None]
    _status_cell = [None]
    _layer_grid_cell = [None]

    make_app_header(
        root,
        title="G-Code Converter & Visualizer",
        subtitle="Aerotech Toolpath & Layer Inspection",
        on_return=root.destroy,
        on_about=lambda: show_about_dialog(root),
    )
    make_app_footer(root)

    main_pane = ttk.Panedwindow(root, orient=HORIZONTAL)
    main_pane.pack(fill=BOTH, expand=YES)

    left_container = ttk.Frame(main_pane, padding=(10, 10, 5, 10))
    _, left_inner = make_scrollable_left_panel(left_container)

    right_frame = ttk.Frame(main_pane, padding=(5, 10, 10, 10))
    canvas_frame = ttk.Frame(right_frame, relief="solid", borderwidth=1)
    canvas_frame.pack(fill=BOTH, expand=YES)

    fig = Figure(figsize=(10, 7), facecolor='#1e1e2e')
    _ax0 = fig.add_subplot(111)
    _ax0.set_facecolor('#1e1e2e')
    _ax0.set_title("Load a G-code file to initialize preview", color='#888888', fontsize=12)
    _ax0.tick_params(colors='#444466')
    for sp in _ax0.spines.values():
        sp.set_edgecolor('#444466')
    _fig_cell[0] = fig

    canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill=BOTH, expand=True)
    _canvas_cell[0] = canvas

    toolbar_frame = ttk.Frame(canvas_frame)
    toolbar_frame.pack(fill=X, side=BOTTOM)
    NavigationToolbar2Tk(canvas, toolbar_frame).update()

    # --- Section 1: G-Code Input ---
    sec_input = make_titled_panel(left_inner, "📂 G-Code Input File")
    input_entry = ttk.Entry(sec_input, textvariable=input_var, state="readonly", style="secondary.TEntry")
    input_entry.pack(fill=X, pady=(0, 4))
    btn_in = ttk.Button(
        sec_input, text="📂 Browse G-Code", bootstyle="primary-outline",
        command=lambda: browse_input(input_var, output_var, input_entry, output_entry, _btn_cell[0]),
    )
    btn_in.pack(fill=X)
    attach_tooltip(btn_in, "Select G-Code file (.gcode, .nc, .txt, .ascript)")

    # --- Section 2: Output Directory ---
    sec_out = make_titled_panel(left_inner, "📁 Output Folder")
    output_entry = ttk.Entry(sec_out, textvariable=output_var, state="readonly", style="secondary.TEntry")
    output_entry.pack(fill=X, pady=(0, 4))
    btn_out = ttk.Button(
        sec_out, text="📁 Browse Output", bootstyle="primary-outline",
        command=lambda: browse_output(input_var, output_var, output_entry, _btn_cell[0]),
    )
    btn_out.pack(fill=X)
    attach_tooltip(btn_out, "Select destination folder for rendered PNG files")

    # --- Section 3: Bed Dimensions ---
    sec_bed = make_titled_panel(left_inner, "📐 Printer Bed Bounds")
    bed_row = ttk.Frame(sec_bed)
    bed_row.pack(fill=X)
    entry_w = ttk.Entry(bed_row, textvariable=bed_w_var, width=8)
    entry_w.pack(side=LEFT, padx=(0, 4))
    attach_tooltip(entry_w, "Printer bed width X in mm")

    small_label(bed_row, "×")
    entry_h = ttk.Entry(bed_row, textvariable=bed_h_var, width=8)
    entry_h.pack(side=LEFT, padx=(4, 6))
    attach_tooltip(entry_h, "Printer bed length Y in mm")
    small_label(bed_row, "(mm, optional)")

    # --- Section 4: Preview View Mode ---
    sec_view = make_titled_panel(left_inner, "👁 View Mode")

    def _on_mode_change():
        if not _LATEST_LAYERS:
            return
        try:
            bw = float(bed_w_var.get()) if bed_w_var.get().strip() else None
            bh = float(bed_h_var.get()) if bed_h_var.get().strip() else None
        except ValueError:
            bw = bh = None

        _redraw_preview(
            layer_idx=_active_layer_idx,
            fig=_fig_cell[0],
            canvas=_canvas_cell[0],
            view_mode_var=view_mode_var,
            bed_w=bw,
            bed_h=bh,
        )

    for mode_text, icon in [("2D Top", "⊞"), ("3D Interactive", "⟳"), ("3D All Layers", "⊡")]:
        ttk.Radiobutton(
            sec_view,
            text=f"{icon}  {mode_text}",
            variable=view_mode_var,
            value=mode_text,
            bootstyle="info.Toolbutton",
            command=_on_mode_change,
        ).pack(fill=X, pady=(0, 3))

    # --- Section 5: Layer Grid ---
    sec_layer = make_titled_panel(left_inner, "🥞 Layers")
    small_label(sec_layer, "Click layer to inspect:")
    layer_grid_frame = ttk.Frame(sec_layer)
    layer_grid_frame.pack(fill=X, pady=(4, 4))
    _layer_grid_cell[0] = layer_grid_frame

    # --- Section 6: Convert & Actions ---
    sec_act = make_titled_panel(left_inner, "⚡ Actions")
    convert_btn = make_action_button(sec_act, text="⚡ Convert to PNG + Load Preview", bootstyle="success", state="disabled")
    _btn_cell[0] = convert_btn
    attach_tooltip(convert_btn, "Render high-res PNG and load layer toolpath into preview")

    snapshot_btn = make_action_button(sec_act, text="💾 Save View Snapshot", bootstyle="secondary", state="disabled")
    _snap_cell[0] = snapshot_btn
    attach_tooltip(snapshot_btn, "Save current preview canvas image")

    btn_open = make_action_button(sec_act, text="📂 Open Output Folder", bootstyle="secondary", command=lambda: _open_folder(output_var.get()))
    attach_tooltip(btn_open, "Open destination directory in file explorer")

    progress_bar = make_progress_bar(left_inner)
    status_label = make_status_label(left_inner, "Ready — select G-Code file")
    _status_cell[0] = status_label

    def _convert_cmd():
        run_conversion(
            input_var, output_var,
            bed_w_var, bed_h_var,
            _btn_cell[0], progress_bar,
            _status_cell[0], root,
            parse_and_preview_cb=lambda: _start_parse_and_preview(
                input_var, bed_w_var, bed_h_var,
                _btn_cell[0], _status_cell[0],
                _layer_grid_cell[0], _snap_cell[0],
                _fig_cell[0], _canvas_cell[0],
                view_mode_var, root,
            ),
        )

    convert_btn.config(command=_convert_cmd)
    snapshot_btn.config(command=lambda: _save_snapshot(_fig_cell[0], output_var, _status_cell[0]))

    main_pane.add(left_container, weight=1)
    main_pane.add(right_frame, weight=4)

    input_var.trace_add("write", lambda *_: _update_convert_btn(input_var, output_var, convert_btn))
    output_var.trace_add("write", lambda *_: _update_convert_btn(input_var, output_var, convert_btn))

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
                    _layer_grid_cell[0], _snap_cell[0],
                    _fig_cell[0], _canvas_cell[0],
                    view_mode_var, root,
                ),
            ),
        )

    return root

def main():
    build_gui().mainloop()

if __name__ == "__main__":
    main()
