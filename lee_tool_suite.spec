# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('st thomas logo.png', '.'),
        ('assets/*', 'assets'),
    ],
    hiddenimports=[
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'matplotlib',
        'matplotlib.backends.backend_tkagg',
        'mpl_toolkits.mplot3d',
        'cv2',
        'numpy',
        'ttkbootstrap',
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# PyInstaller startup splash screen using University of St. Thomas Logo
splash = Splash(
    'assets/st_thomas_logo.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    text_color='white',
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LeeToolSuite_v4.0.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
    version='version_info.txt',
)
