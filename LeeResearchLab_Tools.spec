# LeeResearchLab_Tools.spec
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Collect ttkbootstrap assets ──────────────────────────────────────
ttkbootstrap_datas = collect_data_files('ttkbootstrap')
ttkbootstrap_imports = collect_submodules('ttkbootstrap')

# ── Collect tkinterdnd2 assets (if installed) ─────────────────────────
try:
    tkdnd_datas = collect_data_files('tkinterdnd2')
except Exception:
    tkdnd_datas = []

# ── Collect OpenCV assets and ALL submodules ─────────────────────────
try:
    cv2_datas = collect_data_files('cv2')
    cv2_imports = collect_submodules('cv2')     # ← ADD THIS
except Exception:
    cv2_datas = []
    cv2_imports = []

# Combine all data files
all_datas = ttkbootstrap_datas + tkdnd_datas + cv2_datas

# Combine all hidden imports – this is the key fix
hidden_imports = (
    ttkbootstrap_imports
    + cv2_imports                              # ← all cv2 submodules
    + [
        'numpy',
        'numpy.core._methods',
        'numpy.lib.format',
        'matplotlib',
        'matplotlib.backends.backend_tkagg',
        'PIL',
        'PIL.Image',
        'tkinterdnd2',
    ]
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LeeResearchLab_Tools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)