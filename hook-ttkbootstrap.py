# hook-ttkbootstrap.py
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all non‑Python files (icons, fonts, theme files, etc.)
datas = collect_data_files('ttkbootstrap')

# Ensure all submodules are imported (avoids missing imports)
hiddenimports = collect_submodules('ttkbootstrap')