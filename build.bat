@echo off
SETLOCAL

:: Clean previous builds
echo Cleaning previous builds...
rd /s /q build 2>nul
rd /s /q dist 2>nul

:: Install/upgrade required packages
echo Installing dependencies...
pip install --upgrade pip
pip install --upgrade pyinstaller==6.21.0
pip install --upgrade ttkbootstrap==2.0.1
pip install --upgrade matplotlib numpy pillow scikit-image opencv-python

:: Build executable
echo Building executable...
pyinstaller LeeResearchLabTools.spec --clean

:: Copy assets
echo Copying assets...
if not exist "dist\assets" mkdir "dist\assets"
xcopy /y /s /q assets\*.* dist\assets\ >nul

:: Verify build
if exist "dist\LeeResearchLabTools.exe" (
    echo Build successful! Executable created in dist folder.
    echo Size: %~z0 dist\LeeResearchLabTools.exe bytes
) else (
    echo Build failed! Check for errors above.
)

pause
