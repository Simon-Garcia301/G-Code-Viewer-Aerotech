# ============================================================
# main.py
# ============================================================
#!/usr/bin/env python3
"""
main.py
━━━━━━━
Launcher menu for the Lee Research Lab tool suite.
Presents two buttons:
  • G-Code Converter   → opens the existing GCode Visualizer GUI
  • Image Analysis     → opens the new Line Width Analysis GUI
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *


def _launch_gcode():
    """Destroy the menu and open the G-Code Converter window."""
    menu_root.destroy()
    from gcode_converter_gui import build_gui
    root = build_gui()
    root.mainloop()


def _launch_image_analysis():
    """Destroy the menu and open the Image Analysis window."""
    menu_root.destroy()
    from image_analysis_gui import build_image_analysis_gui
    root = build_image_analysis_gui()
    root.mainloop()


# ── Build the small launcher menu ────────────────────────────────────────────
menu_root = ttk.Window(
    title="Lee Research Lab — Tool Launcher",
    themename="darkly",
    size=(420, 280),
    resizable=(False, False),
)

# Center content vertically
menu_root.columnconfigure(0, weight=1)
for row in range(6):
    menu_root.rowconfigure(row, weight=1)

ttk.Label(
    menu_root,
    text="Lee Research Lab",
    font=("Segoe UI", 18, "bold"),
    foreground="#eeeeff",
    anchor=CENTER,
).grid(row=0, column=0, pady=(28, 2), sticky="ew")

ttk.Label(
    menu_root,
    text="Select a tool to launch",
    font=("Segoe UI", 10),
    foreground="#888888",
    anchor=CENTER,
).grid(row=1, column=0, pady=(0, 18), sticky="ew")

ttk.Button(
    menu_root,
    text="⚙   G-Code Converter",
    bootstyle="primary",
    padding=(16, 12),
    command=_launch_gcode,
).grid(row=2, column=0, padx=60, pady=(0, 10), sticky="ew")

ttk.Button(
    menu_root,
    text="🔬   Image Analysis",
    bootstyle="info",
    padding=(16, 12),
    command=_launch_image_analysis,
).grid(row=3, column=0, padx=60, pady=(0, 10), sticky="ew")

ttk.Label(
    menu_root,
    text="© Lee Research Lab",
    font=("Segoe UI", 8),
    foreground="#444466",
    anchor=CENTER,
).grid(row=5, column=0, pady=(0, 10), sticky="ew")

if __name__ == "__main__":
    menu_root.mainloop()