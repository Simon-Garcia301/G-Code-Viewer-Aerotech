#!/usr/bin/env python3
"""
main.py
━━━━━━━
Launcher menu for the Lee Research Group Tool Suite v4.0.0.
Refactored to consume ui_common header, buttons, icon loader, and about dialog.
"""

import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

import gcode_converter_gui
import image_analysis_gui
import surface_roughness_gui
from ui_common import (
    __version__,
    make_app_header,
    make_app_footer,
    make_action_button,
    load_app_icon,
    show_about_dialog,
    attach_tooltip,
)

menu_root = None

def _launch_and_return(build_func, tool_name: str) -> None:
    """Close the menu window, execute the selected tool, and re-open menu upon return."""
    global menu_root
    if menu_root:
        menu_root.withdraw()  # Hide instead of destroy

    try:
        app_root = build_func()
        app_root.protocol("WM_DELETE_WINDOW", lambda: _on_tool_close(app_root))
        app_root.mainloop()
    except Exception as err:
        messagebox.showerror(
            "Tool Launch Error",
            f"Could not launch {tool_name}.\n\nError details:\n{err}",
        )
        if menu_root:
            menu_root.deiconify()  # Show menu again if error occurred

def _on_tool_close(tool_window):
    """Handle tool window closure by quitting it and showing menu again."""
    global menu_root
    tool_window.quit()
    tool_window.destroy()
    if menu_root:
        menu_root.deiconify()

def _start_menu():
    global menu_root

    menu_root = ttk.Window(
        title="Lee Research Group — Tool Suite",
        themename="darkly",
        size=(620, 480),
        resizable=(False, False),
    )

    load_app_icon(menu_root)

    # Top Suite Header
    make_app_header(
        menu_root,
        title="Lee Research Group Tool Suite",
        subtitle="University of St. Thomas",
        on_about=lambda: show_about_dialog(menu_root),
    )

    # Persistent Footer
    make_app_footer(menu_root)

    # Center Container
    center_frame = ttk.Frame(menu_root, padding=(30, 15, 30, 15))
    center_frame.pack(fill=BOTH, expand=YES)

    ttk.Label(
        center_frame,
        text="Select a laboratory module to launch:",
        font=("Segoe UI", 11),
        foreground="#cccccc",
        anchor=CENTER,
    ).pack(fill=X, pady=(0, 20))

    # Module Buttons
    btn_gcode = make_action_button(
        center_frame,
        text="⚙   G-Code Converter & Visualizer",
        bootstyle="primary",
        command=lambda: _launch_and_return(gcode_converter_gui.build_gui, "G-Code Converter"),
        padding=(16, 12),
    )
    attach_tooltip(btn_gcode, "Convert Aerotech G-Code files into high-res PNGs & inspect 2D/3D nozzle paths")

    btn_img = make_action_button(
        center_frame,
        text="🔬   Line Width Image Analysis",
        bootstyle="info",
        command=lambda: _launch_and_return(image_analysis_gui.build_image_analysis_gui, "Image Analysis"),
        padding=(16, 12),
    )
    attach_tooltip(btn_img, "Measure line width, edge profile, and CV% across microscopic image scans")

    btn_surf = make_action_button(
        center_frame,
        text="📊   Surface Roughness Analysis",
        bootstyle="success",
        command=lambda: _launch_and_return(surface_roughness_gui.build_surface_roughness_gui, "Surface Roughness"),
        padding=(16, 12),
    )
    attach_tooltip(btn_surf, "Reflectance surface roughness analysis with 5x coaxial flat-field correction")

    menu_root.mainloop()

if __name__ == "__main__":
    _start_menu()
