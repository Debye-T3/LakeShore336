@echo off
setlocal
cd /d "%~dp0\.."

echo ========================================
echo  Lake Shore 336 - Offline Package Build
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found in PATH.
    exit /b 1
)

echo [1/5] Checking build dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Build dependencies could not be installed.
    exit /b 1
)

echo [2/5] Building the portable application...
python -m PyInstaller ^
    --onedir ^
    --name "LakeShore336" ^
    --add-data "web;web" ^
    --hidden-import serial ^
    --hidden-import serial.tools.list_ports ^
    --hidden-import tzdata ^
    --collect-data tzdata ^
    --clean ^
    --noconfirm ^
    scripts\ls336_web_dashboard.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)

echo [3/5] Adding launcher and offline guide...
copy /Y "scripts\run_portable.bat" "dist\LakeShore336\START.bat" >nul || exit /b 1
copy /Y "docs\offline_package_zh.md" "dist\LakeShore336\OFFLINE_GUIDE_ZH.md" >nul || exit /b 1
if not exist "dist\LakeShore336\logs" mkdir "dist\LakeShore336\logs"
if errorlevel 1 (
    echo ERROR: Package support files could not be created.
    exit /b 1
)

echo [4/5] Running packaged DEMO smoke test...
python scripts\smoke_test_portable.py ^
    --executable "dist\LakeShore336\LakeShore336.exe" ^
    --port 8877 ^
    --timeout 20 ^
    --cleanup-logs
if errorlevel 1 (
    echo ERROR: Packaged application smoke test failed.
    exit /b 1
)

echo [5/5] Creating ZIP archive...
python scripts\create_portable_zip.py ^
    --source "dist\LakeShore336" ^
    --output "dist\LakeShore336_portable.zip"
if errorlevel 1 (
    echo ERROR: ZIP archive creation failed.
    exit /b 1
)

echo.
echo Build complete:
echo   dist\LakeShore336_portable.zip
echo.
echo The target Windows PC does not need Python, WSL, or internet access.
exit /b 0
