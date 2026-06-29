#!/usr/bin/env python3
"""
gcode_converter_gui.py
━━━━━━━━━━━━━━━━━━━━━━
Desktop GUI front-end for the Aerotech G-Code → PNG converter.
"""

import os
import threading
import subprocess

import tkinter as tk
from tkinter import filedialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

from gcode_engine import convert_gcode_to_png


# ══════════════════════════════════════════════════════════════════════════════
#  APPLICATION STATE
# ══════════════════════════════════════════════════════════════════════════════

_output_manually_set: bool = False
_last_browse_dir: str = os.path.expanduser("~")


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _set_entry(widget: ttk.Entry, text: str) -> None:
    widget.config(state="normal")
    widget.delete(0, tk.END)
    widget.insert(0, text)
    widget.config(state="readonly")


def _set_status(label: ttk.Label, text: str, colour: str) -> None:
    label.config(text=text, foreground=colour)


def _open_folder(path: str) -> None:
    subprocess.Popen(f'explorer "{path}"')


def _update_convert_btn(input_var, output_var, btn):
    btn.config(state="normal" if input_var.get() and output_var.get() else "disabled")


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
    _last_browse_dir = folder
    _output_manually_set = True
    _set_entry(output_entry, folder)
    output_var.set(folder)
    _update_convert_btn(input_var, output_var, btn)


# ══════════════════════════════════════════════════════════════════════════════
#  DRAG-AND-DROP
# ══════════════════════════════════════════════════════════════════════════════

def on_file_drop(event, input_var, output_var, input_entry, output_entry, btn):
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


# ══════════════════════════════════════════════════════════════════════════════
#  CONVERSION
# ══════════════════════════════════════════════════════════════════════════════

def run_conversion(
    input_var, output_var,
    bed_w_var, bed_h_var,
    convert_btn, progress_bar,
    status_label, open_folder_btn, root,
):
    gcode_path    = input_var.get().strip()
    output_folder = output_var.get().strip()

    if not gcode_path:
        _set_status(status_label, "Error: No input file selected.", "red"); return
    if not os.path.isfile(gcode_path):
        _set_status(status_label, "Error: File not found.", "red"); return
    if not output_folder:
        _set_status(status_label, "Error: No output folder selected.", "red"); return

    # Parse optional bed dimensions
    try:
        bed_w = float(bed_w_var.get()) if bed_w_var.get().strip() else None
        bed_h = float(bed_h_var.get()) if bed_h_var.get().strip() else None
    except ValueError:
        _set_status(status_label, "Error: Bed dimensions must be numbers.", "red"); return

    convert_btn.config(state="disabled")
    open_folder_btn.pack_forget()
    _set_status(status_label, "Converting…", "#f0c040")
    progress_bar.start(12)

    threading.Thread(
        target=_worker,
        args=(gcode_path, output_folder, bed_w, bed_h,
              convert_btn, progress_bar, status_label, open_folder_btn, root),
        daemon=True,
    ).start()


def _worker(gcode_path, output_folder, bed_w, bed_h,
            convert_btn, progress_bar, status_label, open_folder_btn, root):
    result = convert_gcode_to_png(gcode_path, output_folder,
                                   bed_w=bed_w, bed_h=bed_h)
    root.after(0, _done, result, output_folder,
               convert_btn, progress_bar, status_label, open_folder_btn)


def _done(result, output_folder, convert_btn, progress_bar, status_label, open_folder_btn):
    progress_bar.stop()
    progress_bar["value"] = 0
    if result == "SUCCESS":
        _set_status(status_label, f"Done!  PNG saved to:  {output_folder}", "#44dd88")
        open_folder_btn.pack(pady=(6, 0))
        convert_btn.config(state="normal")
    else:
        _set_status(status_label, result, "red")
        convert_btn.config(state="normal")


# ══════════════════════════════════════════════════════════════════════════════
#  GUI CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════

def build_gui() -> ttk.Window:

    root = ttk.Window(
        title="G-Code to PNG Converter",
        themename="darkly",
        size=(640, 460),
        resizable=(False, False),
    )
    if DND_AVAILABLE:
        TkinterDnD.require(root)

    input_var  = tk.StringVar()
    output_var = tk.StringVar()
    bed_w_var  = tk.StringVar()
    bed_h_var  = tk.StringVar()

    outer = ttk.Frame(root, padding=(24, 18, 24, 18))
    outer.pack(fill=BOTH, expand=YES)

    # ── Header ────────────────────────────────────────────────────────────────
    ttk.Label(
        outer, text="G-Code to PNG Converter",
        font=("Segoe UI", 18, "bold"), anchor=CENTER,
    ).pack(fill=X, pady=(0, 4))
    ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(0, 14))

    # Mutable cells so early-defined callbacks can reference late-created widgets
    _btn_cell = [None]

    # ── Row helper ────────────────────────────────────────────────────────────
    def make_row(label_text, label_width=16):
        frame = ttk.Frame(outer)
        frame.pack(fill=X, pady=(0, 8))
        ttk.Label(frame, text=label_text, width=label_width, anchor=W).pack(side=LEFT)
        return frame

    # ── 1. Input file ─────────────────────────────────────────────────────────
    row1 = make_row("G-Code File:")
    input_entry = ttk.Entry(row1, textvariable=input_var,
                            state="readonly", style="secondary.TEntry")
    input_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 6))

    ttk.Button(
        row1, text="Browse", bootstyle="primary-outline",
        command=lambda: browse_input(
            input_var, output_var, input_entry, output_entry, _btn_cell[0]),
    ).pack(side=LEFT)

    # Placeholder
    _PH = "Drop G-code file here…"
    def _show_ph():
        if not input_var.get():
            input_entry.config(state="normal")
            input_entry.delete(0, tk.END)
            input_entry.insert(0, _PH)
            input_entry.config(state="readonly", foreground="#888888")
    root.after(50, _show_ph)

    # Drag-and-drop (wired after output_entry exists — see end of function)

    # ── 2. Output folder ──────────────────────────────────────────────────────
    row2 = make_row("Output Folder:")
    output_entry = ttk.Entry(row2, textvariable=output_var,
                             state="readonly", style="secondary.TEntry")
    output_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 6))

    ttk.Button(
        row2, text="Browse", bootstyle="primary-outline",
        command=lambda: browse_output(
            input_var, output_var, output_entry, _btn_cell[0]),
    ).pack(side=LEFT)

    # ── 3. Bed size ───────────────────────────────────────────────────────────
    row3 = make_row("Bed Size (W × H):")
    bed_w_entry = ttk.Entry(row3, textvariable=bed_w_var, width=10)
    bed_w_entry.pack(side=LEFT, padx=(4, 4))
    ttk.Label(row3, text="×", foreground="#aaaaaa").pack(side=LEFT, padx=(0, 4))
    bed_h_entry = ttk.Entry(row3, textvariable=bed_h_var, width=10)
    bed_h_entry.pack(side=LEFT, padx=(0, 6))
    ttk.Label(row3, text="mm  (optional)", foreground="#888888",
              font=("Segoe UI", 9)).pack(side=LEFT)

    # ── Separator ─────────────────────────────────────────────────────────────
    ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(4, 14))

    # ── Status label ──────────────────────────────────────────────────────────
    status_label = ttk.Label(
        outer, text="Ready", foreground="#888888",
        font=("Segoe UI", 10), anchor=CENTER,
    )

    # ── Progress bar ──────────────────────────────────────────────────────────
    progress_bar = ttk.Progressbar(
        outer, bootstyle="info-striped",
        mode="indeterminate", length=400,
    )
    progress_bar.pack(fill=X, pady=(0, 6))
    status_label.pack(fill=X, pady=(0, 6))

    # ── Open-folder button (hidden until success) ─────────────────────────────
    open_folder_btn = ttk.Button(
        outer, text="📂  Open Output Folder", bootstyle="secondary",
        command=lambda: _open_folder(output_var.get()),
    )

    # ── Convert button ────────────────────────────────────────────────────────
    convert_btn = ttk.Button(
        outer, text="Convert to PNG", bootstyle="success",
        state="disabled", padding=(20, 10),
        command=lambda: run_conversion(
            input_var, output_var,
            bed_w_var, bed_h_var,
            convert_btn, progress_bar,
            status_label, open_folder_btn, root,
        ),
    )
    convert_btn.pack(pady=(0, 10), before=progress_bar)
    _btn_cell[0] = convert_btn

    # Reactive enable/disable
    input_var.trace_add("write",
        lambda *_: _update_convert_btn(input_var, output_var, convert_btn))
    output_var.trace_add("write",
        lambda *_: _update_convert_btn(input_var, output_var, convert_btn))

    # ── Wire up drag-and-drop now that output_entry exists ────────────────────
    if DND_AVAILABLE:
        input_entry.drop_target_register(DND_FILES)
        input_entry.dnd_bind(
            "<<Drop>>",
            lambda e: on_file_drop(
                e, input_var, output_var,
                input_entry, output_entry, convert_btn),
        )

    return root


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    build_gui().mainloop()

if __name__ == "__main__":
    main()
