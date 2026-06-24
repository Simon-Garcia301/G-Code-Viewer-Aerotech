#!/usr/bin/env python3
"""
main.py
━━━━━━━
Command-line entry point for the Aerotech G-Code Nozzle Path Viewer.

Usage
-----
  python main.py my_program.gcode        # convert a file
  python main.py                         # interactive prompt / built-in example

This file contains only CLI wiring. All G-code logic lives in gcode_engine.py.
"""

import sys
import os
import textwrap

# ── The only project import: the engine module. ──────────────────────────────
# PyInstaller sees this import statement at build time and automatically
# bundles gcode_engine.py into the frozen executable.
from gcode_engine import preprocess, parse_gcode, visualise


# ══════════════════════════════════════════════════════════════════════════════
#  BUILT-IN EXAMPLE  (used when no file is provided)
# ══════════════════════════════════════════════════════════════════════════════

_EXAMPLE_GCODE = textwrap.dedent("""\
    // Aerotech Automation1 – Simple rectangle test
    G71       // mm units
    G76       // feedrate in mm/sec
    G90       // absolute positioning
    F10       // feedrate = 10 mm/s
    var $Zprint = 0.4
    G0 X0 Y0 Z5
    G0 X0 Y0 Z$Zprint
    G1 X55 Y0
    G1 X55 Y45
    G1 X0  Y45
    G1 X0  Y0
    G0 X0  Y0 Z5
""")


# ══════════════════════════════════════════════════════════════════════════════
#  INPUT HANDLING
# ══════════════════════════════════════════════════════════════════════════════

def get_gcode_text() -> tuple:
    """
    Obtain G-code source text and a human-readable source label.

    Priority:
      1. sys.argv[1]  — file path passed on the command line / drag-and-drop
      2. Interactive  — user is prompted to enter a file path
      3. Built-in     — fall back to the rectangle example
    """
    if len(sys.argv) > 1:
        path = sys.argv[1].strip().strip('"').strip("'")
        if not os.path.isfile(path):
            print(f"[ERROR] File not found: {path!r}")
            sys.exit(1)
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read(), os.path.basename(path)

    print("═" * 60)
    print("  Aerotech G-code Nozzle Path Viewer")
    print("═" * 60)
    print("  Enter a file path, or press [Enter] for the built-in example.\n")

    user_input = input("  File path (or Enter for example): ").strip().strip('"').strip("'")

    if user_input:
        if not os.path.isfile(user_input):
            print(f"[ERROR] File not found: {user_input!r}")
            sys.exit(1)
        with open(user_input, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read(), os.path.basename(user_input)

    print("\n  No file provided — using built-in rectangle example.\n")
    return _EXAMPLE_GCODE, "Built-in rectangle example"


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("━" * 60)
    print("  Aerotech Automation1 G-Code Nozzle Path Viewer")
    print("━" * 60)

    gcode_text, source_label = get_gcode_text()
    print(f"\n  Source : {source_label}")

    lines = preprocess(gcode_text)
    print(f"  Lines after preprocessing: {len(lines)}\n")

    print("  Parsing G-code …")
    try:
        travel_segs, print_segs, z_anns, state = parse_gcode(lines)
    except ValueError as exc:
        print(f"\n[FATAL] {exc}")
        sys.exit(1)

    unit = "mm" if state.unit_mm else "in"
    print(f"\n  ✓ Parsing complete.")
    print(f"    Travel segments : {len(travel_segs)}")
    print(f"    Print  segments : {len(print_segs)}")
    print(f"    Z annotations   : {len(z_anns)}")
    print(f"    Final position  : X={state.x:.4f}  Y={state.y:.4f}  "
          f"Z={state.z:.4f}  ({unit})")
    print(f"    Variables       : {state.variables}")

    output_path = os.path.join(os.getcwd(), "gcode_nozzle_path.png")
    print(f"\n  Saving PNG → {output_path}")
    visualise(
        travel_segs, print_segs, z_anns,
        title=f"Aerotech Nozzle Path – {source_label}",
        unit_label=unit,
        output_path=output_path,
    )
    print("  Done.")


if __name__ == '__main__':
    main()
