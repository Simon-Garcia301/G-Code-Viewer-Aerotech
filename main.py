#!/usr/bin/env python3
"""
main.py
━━━━━━━
Launcher menu for the Lee Research Lab tool suite.
"""

import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *

# ─────────────────────────────────────────────────────────────────
#  Top‑level imports – PyInstaller needs them visible.
# ─────────────────────────────────────────────────────────────────
import gcode_converter_gui
import image_analysis_gui
import surface_roughness_gui


# ─────────────────────────────────────────────────────────────────
#  Launch helpers
# ─────────────────────────────────────────────────────────────────

def _launch_and_return(build_func, tool_name):
    """Destroy the menu, open the tool, and return when done."""
    menu_root.destroy()

    try:
        app_root = build_func()
        # Ensure the close button terminates the mainloop cleanly.
        app_root.protocol("WM_DELETE_WINDOW", app_root.quit)
        app_root.mainloop()
    except Exception as e:
        messagebox.showerror(
            "Launch Error",
            f"Could not start {tool_name}.\n\nError: {e}"
        )
    finally:
        _start_menu()


def _launch_gcode():
    _launch_and_return(gcode_converter_gui.build_gui, "G-Code Converter")


def _launch_image_analysis():
    _launch_and_return(image_analysis_gui.build_image_analysis_gui, "Image Analysis")


def _launch_surface_roughness():
    _launch_and_return(surface_roughness_gui.build_surface_roughness_gui,
                       "Surface Roughness")


# ─────────────────────────────────────────────────────────────────
#  Build the launcher window
# ─────────────────────────────────────────────────────────────────

def _start_menu():
    global menu_root

    menu_root = ttk.Window(
        title="Lee Research Lab — Tool Launcher",
        themename="darkly",
        size=(600, 460),                     # bigger window
        resizable=(False, False),
    )

    # Centre everything vertically
    for row in range(9):
        menu_root.rowconfigure(row, weight=1)
    menu_root.columnconfigure(0, weight=1)

    # Header
    ttk.Label(
        menu_root,
        text="Lee Research Lab",
        font=("Segoe UI", 24, "bold"),
        foreground="#eeeeff",
        anchor=CENTER,
    ).grid(row=0, column=0, pady=(35, 4), sticky="ew")

    ttk.Label(
        menu_root,
        text="Select a tool to launch",
        font=("Segoe UI", 12),
        foreground="#999999",
        anchor=CENTER,
    ).grid(row=1, column=0, pady=(0, 25), sticky="ew")

    # Buttons – larger and wider
    btn_style = {"padding": (22, 16), "width": 24}

    ttk.Button(
        menu_root,
        text="⚙   G‑Code Converter",
        bootstyle="primary",
        command=_launch_gcode,
        **btn_style
    ).grid(row=2, column=0, pady=(0, 14), sticky="ew", padx=100)

    ttk.Button(
        menu_root,
        text="🔬   Image Analysis",
        bootstyle="info",
        command=_launch_image_analysis,
        **btn_style
    ).grid(row=3, column=0, pady=(0, 14), sticky="ew", padx=100)

    ttk.Button(
        menu_root,
        text="📊   Surface Roughness",
        bootstyle="success",
        command=_launch_surface_roughness,
        **btn_style
    ).grid(row=4, column=0, pady=(0, 14), sticky="ew", padx=100)

    # Footer
    ttk.Label(
        menu_root,
        text="Close any tool window to return here.",
        font=("Segoe UI", 8),
        foreground="#555566",
    ).grid(row=6, column=0, pady=(20, 2), sticky="ew")

    ttk.Label(
        menu_root,
        text="© Lee Research Lab",
        font=("Segoe UI", 8),
        foreground="#444466",
    ).grid(row=7, column=0, pady=(0, 20), sticky="ew")

    menu_root.mainloop()


if __name__ == "__main__":
    _start_menu()
