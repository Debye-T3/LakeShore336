@echo off
setlocal enabledelayedexpansion
echo ========================================
echo  Lake Shore 336 - Build Portable Package
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH. Install Python 3 first.
    pause
    exit /b 1
)

:: Install dependencies
echo [1/4] Installing dependencies...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

:: Build with PyInstaller
echo [2/4] Building portable executable...
python -m PyInstaller ^
    --onedir ^
    --name "LakeShore336" ^
    --add-data "web;web" ^
    --add-data "logs;logs" ^
    --hidden-import serial ^
    --hidden-import serial.tools.list_ports ^
    --hidden-import tzdata ^
    --clean ^
    --noconfirm ^
    scripts/ls336_web_dashboard.py

if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

:: Copy launcher
echo [3/4] Creating launcher...
copy /Y scripts\run_portable.bat dist\LakeShore336\START.bat >nul

:: Package into zip
echo [4/4] Creating ZIP archive...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\LakeShore336\*' -DestinationPath 'dist\LakeShore336_portable.zip' -Force"

echo.
echo ========================================
echo  Build complete!
echo.
echo  Portable package: dist\LakeShore336_portable.zip
echo.
echo  To test locally:
echo    dist\LakeShore336\START.bat
echo.
echo  To deploy: copy the ZIP to the target PC, unzip, run START.bat
echo ========================================
pause
