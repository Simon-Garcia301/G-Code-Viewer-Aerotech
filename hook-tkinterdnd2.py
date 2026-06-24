# hook-tkinterdnd2.py
# ─────────────────────────────────────────────────────────────────────────────
# PyInstaller hook for tkinterdnd2.
#
# Place this file in your project root (same directory as gcode_converter_gui.py
# and main.py), then pass --additional-hooks-dir=. to PyInstaller.
#
# Without this hook, PyInstaller will not bundle the compiled tkdnd binaries
# (.dll on Windows, .so on Linux, .dylib on macOS) and the .tcl script files
# that tkinterdnd2 needs at runtime, causing the error:
#   _tkinter.TclError: can't find package tkdnd
# ─────────────────────────────────────────────────────────────────────────────

from PyInstaller.utils.hooks import collect_data_files

# collect_data_files() finds every non-.py file inside the tkinterdnd2 package
# directory (the tkdnd/ sub-folder with platform binaries and .tcl files)
# and tells PyInstaller to include them verbatim in the bundle.
datas = collect_data_files('tkinterdnd2')
