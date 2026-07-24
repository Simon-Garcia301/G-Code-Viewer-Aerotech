@echo off
REM Clean previous builds
rd /s /q build 2>nul
rd /s /q dist 2>nul

REM Install dependencies
pip install --upgrade pyinstaller ttkbootstrap matplotlib numpy pillow scikit-image

REM Run PyInstaller
pyinstaller LeeResearchLabTools.spec --clean --onefile --windowed

REM Copy assets to dist folder
xcopy /y /s assets dist\assets

echo Build complete! Check dist folder for the executable.
pause
