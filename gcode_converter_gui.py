#!/usr/bin/env python3
"""
gcode_converter_gui.py
━━━━━━━━━━━━━━━━━━━━━━
Desktop GUI front-end for the Aerotech G-Code → PNG converter.

Dependencies (install with pip before running or building):
    pip install ttkbootstrap tkinterdnd2 pillow numpy matplotlib

To build a standalone .exe for Windows see BUILD INSTRUCTIONS at the
bottom of this file.
"""

import os
import sys
import threading
import subprocess

import tkinter as tk
from tkinter import filedialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# ── tkinterdnd2 drag-and-drop support ────────────────────────────────────────
# We import this gracefully so that the app still works (without DnD) even if
# the user forgets to install the library.
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

# ── Import the conversion function from our existing script ──────────────────
# main.py must live in the same directory as this file.
try:
    from main import convert_gcode_to_png
except ImportError as _e:
    # Give a clear message if the sibling file is missing
    import tkinter.messagebox as _mb
    _root = tk.Tk()
    _root.withdraw()
    _mb.showerror(
        "Import Error",
        f"Could not import 'main.py'.\n\n"
        f"Make sure main.py is in the same folder as this script.\n\n"
        f"Details: {_e}"
    )
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  APPLICATION STATE  (plain module-level variables — no classes needed)
# ══════════════════════════════════════════════════════════════════════════════

# Tracks whether the user manually chose an output folder.
# If False, the output folder auto-follows the input file's directory.
_output_manually_set: bool = False

# Remembers the last folder the user browsed to, so subsequent dialogs
# open in the same place.
_last_browse_dir: str = os.path.expanduser("~")


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _set_entry(entry_widget: ttk.Entry, text: str) -> None:
    """Replace the full content of a read-only Entry widget."""
    entry_widget.config(state="normal")
    entry_widget.delete(0, tk.END)
    entry_widget.insert(0, text)
    entry_widget.config(state="readonly")


def _set_status(label: ttk.Label, text: str, colour: str) -> None:
    """Update the status label text and foreground colour."""
    label.config(text=text, foreground=colour)


def _open_folder_in_explorer(path: str) -> None:
    """Open *path* in Windows File Explorer."""
    subprocess.Popen(f'explorer "{path}"')


def _update_convert_button(
    input_var: tk.StringVar,
    output_var: tk.StringVar,
    convert_btn: ttk.Button
) -> None:
    """
    Enable the Convert button only when both fields are populated.
    Called whenever either StringVar changes.
    """
    if input_var.get() and output_var.get():
        convert_btn.config(state="normal")
    else:
        convert_btn.config(state="disabled")


def _clean_dnd_path(raw: str) -> str:
    """
    tkinterdnd2 delivers the dropped path wrapped in curly braces when the
    path contains spaces, e.g. '{C:/My Files/part.gcode}'.
    Strip the braces and any surrounding whitespace.
    """
    path = raw.strip()
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]
    return path


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSE CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

def browse_input(
    input_var: tk.StringVar,
    output_var: tk.StringVar,
    input_entry: ttk.Entry,
    output_entry: ttk.Entry,
    convert_btn: ttk.Button
) -> None:
    """Open a file dialog and populate the input (and optionally output) fields."""
    global _last_browse_dir, _output_manually_set

    path = filedialog.askopenfilename(
        title="Select G-Code File",
        initialdir=_last_browse_dir,
        filetypes=[
            ("G-Code files", "*.gcode *.nc *.gco *.cnc"),
            ("All files",    "*.*"),
        ]
    )

    if not path:
        return  # User cancelled

    # Normalise to OS path style
    path = os.path.normpath(path)
    _last_browse_dir = os.path.dirname(path)

    # Populate input field
    _set_entry(input_entry, path)
    input_var.set(path)

    # Auto-fill output folder if the user hasn't manually set one
    if not _output_manually_set:
        folder = os.path.dirname(path)
        _set_entry(output_entry, folder)
        output_var.set(folder)

    _update_convert_button(input_var, output_var, convert_btn)


def browse_output(
    input_var: tk.StringVar,
    output_var: tk.StringVar,
    output_entry: ttk.Entry,
    convert_btn: ttk.Button
) -> None:
    """Open a folder dialog and populate the output folder field."""
    global _last_browse_dir, _output_manually_set

    folder = filedialog.askdirectory(
        title="Select Output Folder",
        initialdir=_last_browse_dir if not output_var.get() else output_var.get()
    )

    if not folder:
        return  # User cancelled

    folder = os.path.normpath(folder)
    _last_browse_dir = folder
    _output_manually_set = True  # User explicitly chose — stop auto-following

    _set_entry(output_entry, folder)
    output_var.set(folder)

    _update_convert_button(input_var, output_var, convert_btn)


# ══════════════════════════════════════════════════════════════════════════════
#  DRAG-AND-DROP HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def on_file_drop(
    event,
    input_var: tk.StringVar,
    output_var: tk.StringVar,
    input_entry: ttk.Entry,
    output_entry: ttk.Entry,
    convert_btn: ttk.Button
) -> None:
    """
    Called when a file is dragged onto the input entry field.
    Accepts .gcode, .nc, .gco, and .cnc files; ignores others.
    """
    global _output_manually_set

    raw_path = event.data
    path = _clean_dnd_path(raw_path)

    # Validate extension
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".gcode", ".nc", ".gco", ".cnc"):
        # Silently ignore non-G-code drops
        return

    path = os.path.normpath(path)

    # Populate input field
    _set_entry(input_entry, path)
    input_var.set(path)

    # Auto-fill output folder if not manually overridden
    if not _output_manually_set:
        folder = os.path.dirname(path)
        _set_entry(output_entry, folder)
        output_var.set(folder)

    _update_convert_button(input_var, output_var, convert_btn)


# ══════════════════════════════════════════════════════════════════════════════
#  CONVERSION (runs on a background thread so the GUI doesn't freeze)
# ══════════════════════════════════════════════════════════════════════════════

def run_conversion(
    input_var: tk.StringVar,
    output_var: tk.StringVar,
    convert_btn: ttk.Button,
    progress_bar: ttk.Progressbar,
    status_label: ttk.Label,
    open_folder_btn: ttk.Button,
    root: ttk.Window
) -> None:
    """
    Entry point called by the Convert button.
    Validates inputs, then spawns a daemon thread to do the heavy work.
    """
    gcode_path    = input_var.get().strip()
    output_folder = output_var.get().strip()

    # ── Basic validation before we even start a thread ───────────────────
    if not gcode_path:
        _set_status(status_label, "Error: No input file selected.", "red")
        return

    if not os.path.isfile(gcode_path):
        _set_status(status_label, "Error: File not found.", "red")
        return

    if not output_folder:
        _set_status(status_label, "Error: No output folder selected.", "red")
        return

    # ── UI: lock controls, start progress bar ────────────────────────────
    convert_btn.config(state="disabled")
    open_folder_btn.pack_forget()           # hide any previous success button
    _set_status(status_label, "Converting…", "#f0c040")  # yellow
    progress_bar.start(12)                  # pulse every 12 ms

    # ── Launch background thread ──────────────────────────────────────────
    thread = threading.Thread(
        target=_conversion_worker,
        args=(
            gcode_path,
            output_folder,
            convert_btn,
            progress_bar,
            status_label,
            open_folder_btn,
            root,
        ),
        daemon=True,   # thread dies automatically if the window is closed
    )
    thread.start()


def _conversion_worker(
    gcode_path: str,
    output_folder: str,
    convert_btn: ttk.Button,
    progress_bar: ttk.Progressbar,
    status_label: ttk.Label,
    open_folder_btn: ttk.Button,
    root: ttk.Window
) -> None:
    """
    Runs on a background thread.
    Calls the converter and schedules GUI updates back on the main thread
    using root.after() — the only safe way to touch tkinter from a thread.
    """
    result = convert_gcode_to_png(gcode_path, output_folder)

    # Schedule the UI update on the main thread
    root.after(0, _on_conversion_done,
               result, output_folder,
               convert_btn, progress_bar,
               status_label, open_folder_btn)


def _on_conversion_done(
    result: str,
    output_folder: str,
    convert_btn: ttk.Button,
    progress_bar: ttk.Progressbar,
    status_label: ttk.Label,
    open_folder_btn: ttk.Button
) -> None:
    """
    Runs on the main thread after the worker finishes.
    Updates the UI to reflect success or failure.
    """
    # Stop the progress bar animation
    progress_bar.stop()
    progress_bar["value"] = 0

    if result == "SUCCESS":
        _set_status(
            status_label,
            f"Done!  PNG saved to:  {output_folder}",
            "#44dd88"   # green
        )
        # Show the "Open Output Folder" button
        open_folder_btn.pack(pady=(6, 0))

        # Re-enable the convert button (user may want to convert another file)
        convert_btn.config(state="normal")

    else:
        # result contains the error message from convert_gcode_to_png()
        _set_status(status_label, result, "red")
        convert_btn.config(state="normal")   # let user try again


# ══════════════════════════════════════════════════════════════════════════════
#  GUI CONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════

def build_gui() -> ttk.Window:
    """
    Build and return the fully-configured application window.
    All widgets are created here; callbacks are wired up with lambdas.
    """

    # ── Root window ───────────────────────────────────────────────────────
    # We need TkinterDnD.Tk as the base if DnD is available.
    # ttkbootstrap's Window wraps tkinter.Tk; we inject the DnD requirement
    # manually using TkinterDnD._require() after Window creation.
    root = ttk.Window(
        title="G-Code to PNG Converter",
        themename="darkly",
        size=(600, 400),
        resizable=(False, False),
    )

    # Inject drag-and-drop support into ttkbootstrap's window
    if DND_AVAILABLE:
        TkinterDnD.require(root)    # loads tkdnd into the shared Tcl interpreter

    # ── State variables ───────────────────────────────────────────────────
    input_var  = tk.StringVar()
    output_var = tk.StringVar()

    # ── Outer padding frame ───────────────────────────────────────────────
    outer = ttk.Frame(root, padding=(20, 16, 20, 16))
    outer.pack(fill=BOTH, expand=YES)

    # ─────────────────────────────────────────────────────────────────────
    #  1. Header
    # ─────────────────────────────────────────────────────────────────────
    header_label = ttk.Label(
        outer,
        text="G-Code to PNG Converter",
        font=("Segoe UI", 18, "bold"),
        anchor=CENTER,
    )
    header_label.pack(fill=X, pady=(0, 4))

    # Separator below header
    ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(0, 14))

    # ─────────────────────────────────────────────────────────────────────
    #  2. Input file row
    # ─────────────────────────────────────────────────────────────────────
    input_frame = ttk.Frame(outer)
    input_frame.pack(fill=X, pady=(0, 8))

    ttk.Label(input_frame, text="G-Code File:", width=14, anchor=W).pack(side=LEFT)

    # Read-only entry — user cannot type into it directly
    input_entry = ttk.Entry(
        input_frame,
        textvariable=input_var,
        state="readonly",
        style="secondary.TEntry",   # gives a slightly muted background
    )
    input_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 6))

    # Placeholder hint text — visible when field is empty
    _placeholder_text = "Drop G-code file here…"

    def _set_placeholder():
        """Show hint text when the field is empty."""
        if not input_var.get():
            input_entry.config(state="normal")
            input_entry.delete(0, tk.END)
            input_entry.insert(0, _placeholder_text)
            input_entry.config(state="readonly", foreground="#888888")

    def _clear_placeholder():
        """Remove hint text when a real value is being set."""
        current = input_entry.get()
        if current == _placeholder_text:
            input_entry.config(state="normal")
            input_entry.delete(0, tk.END)
            input_entry.config(state="readonly")

    # Forward-declare convert_btn and open_folder_btn so they can be
    # referenced inside callbacks defined before widget creation below.
    # We use a one-element list as a mutable cell (avoids nonlocal issues).
    _convert_btn_cell      = [None]
    _open_folder_btn_cell  = [None]

    # Browse button for input
    ttk.Button(
        input_frame,
        text="Browse",
        bootstyle="primary-outline",
        command=lambda: browse_input(
            input_var, output_var,
            input_entry, output_entry,
            _convert_btn_cell[0]
        ),
    ).pack(side=LEFT)

    # ── Drag-and-drop registration ────────────────────────────────────────
    if DND_AVAILABLE:
        input_entry.drop_target_register(DND_FILES)
        input_entry.dnd_bind(
            "<<Drop>>",
            lambda event: on_file_drop(
                event,
                input_var, output_var,
                input_entry, output_entry,
                _convert_btn_cell[0]
            )
        )

    # Initialise placeholder
    root.after(50, _set_placeholder)   # slight delay so the window is fully drawn

    # ─────────────────────────────────────────────────────────────────────
    #  3. Output folder row
    # ─────────────────────────────────────────────────────────────────────
    output_frame = ttk.Frame(outer)
    output_frame.pack(fill=X, pady=(0, 12))

    ttk.Label(output_frame, text="Output Folder:", width=14, anchor=W).pack(side=LEFT)

    output_entry = ttk.Entry(
        output_frame,
        textvariable=output_var,
        state="readonly",
        style="secondary.TEntry",
    )
    output_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 6))

    ttk.Button(
        output_frame,
        text="Browse",
        bootstyle="primary-outline",
        command=lambda: browse_output(
            input_var, output_var,
            output_entry,
            _convert_btn_cell[0]
        ),
    ).pack(side=LEFT)

    # ─────────────────────────────────────────────────────────────────────
    #  4. Separator
    # ─────────────────────────────────────────────────────────────────────
    ttk.Separator(outer, orient=HORIZONTAL).pack(fill=X, pady=(4, 14))

    # ─────────────────────────────────────────────────────────────────────
    #  5. Status label  (defined before progress bar so we can reference it)
    # ─────────────────────────────────────────────────────────────────────
    status_label = ttk.Label(
        outer,
        text="Ready",
        foreground="#888888",
        font=("Segoe UI", 10),
        anchor=CENTER,
    )

    # ─────────────────────────────────────────────────────────────────────
    #  6. Progress bar
    # ─────────────────────────────────────────────────────────────────────
    progress_bar = ttk.Progressbar(
        outer,
        bootstyle="info-striped",
        mode="indeterminate",
        length=400,
    )
    progress_bar.pack(fill=X, pady=(0, 6))

    # Pack status label below progress bar
    status_label.pack(fill=X, pady=(0, 6))

    # ─────────────────────────────────────────────────────────────────────
    #  7. "Open Output Folder" button  (hidden until first success)
    # ─────────────────────────────────────────────────────────────────────
    open_folder_btn = ttk.Button(
        outer,
        text="📂  Open Output Folder",
        bootstyle="secondary",
        command=lambda: _open_folder_in_explorer(output_var.get()),
    )
    # NOT packed here — appears only after a successful conversion

    _open_folder_btn_cell[0] = open_folder_btn   # wire into mutable cell

    # ─────────────────────────────────────────────────────────────────────
    #  8. Convert button  (disabled until both fields are filled)
    # ─────────────────────────────────────────────────────────────────────
    convert_btn = ttk.Button(
        outer,
        text="Convert to PNG",
        bootstyle="success",
        state="disabled",
        # Large button via padding rather than font (ttkbootstrap ignores font= on Button)
        padding=(20, 10),
        command=lambda: run_conversion(
            input_var, output_var,
            convert_btn,
            progress_bar,
            status_label,
            open_folder_btn,
            root,
        ),
    )
    # Insert convert button ABOVE progress bar for better visual flow
    convert_btn.pack(pady=(0, 10), before=progress_bar)

    # Store reference so callbacks can reach it
    _convert_btn_cell[0] = convert_btn

    # Watch StringVars — enable/disable convert button reactively
    input_var.trace_add(
        "write",
        lambda *_: _update_convert_button(input_var, output_var, convert_btn)
    )
    output_var.trace_add(
        "write",
        lambda *_: _update_convert_button(input_var, output_var, convert_btn)
    )

    return root


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    root = build_gui()
    root.mainloop()


if __name__ == "__main__":
    main()


# ══════════════════════════════════════════════════════════════════════════════
#  BUILD INSTRUCTIONS  (for reference — see README section below)
# ══════════════════════════════════════════════════════════════════════════════
#
#  See the full build guide in the project README or at the bottom of this
#  docstring.  Short version (run these in order from the project folder):
#
#  Step 1 — install deps:
#      pip install ttkbootstrap pyinstaller pillow numpy matplotlib tkinterdnd2
#
#  Step 2 — create the PyInstaller hook file (hook-tkinterdnd2.py):
#      [create the file manually — content shown in deliverable 3]
#
#  Step 3 — build:
#      pyinstaller --onefile --windowed --name "GCodeToPNG" ^
#          --collect-all ttkbootstrap ^
#          --collect-all tkinterdnd2 ^
#          --additional-hooks-dir=. ^
#          --add-data "main.py;." ^
#          gcode_converter_gui.py
#
#  Step 4 — test:
#      dist\GCodeToPNG.exe
