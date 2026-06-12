@echo off
setlocal

cd /d "%~dp0\.."
title Lake Shore 336 ARPES Dashboard

echo.
echo ================================================
echo   Lake Shore 336 ARPES Temperature Dashboard
echo ================================================
echo.

set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python was not found.
        echo.
        echo Please install Python 3 from https://www.python.org/downloads/
        echo During installation, check "Add python.exe to PATH".
        echo.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=py -3"
)

echo Checking Python...
%PYTHON_CMD% --version
if errorlevel 1 (
    echo.
    echo Python is installed but could not run correctly.
    pause
    exit /b 1
)

echo.
echo Installing required serial driver package if needed...
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Could not install the required package.
    echo Try running this manually:
    echo   %PYTHON_CMD% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo Starting the local dashboard...
echo A browser window should open at:
echo   http://127.0.0.1:8765
echo.
echo Keep this window open while using the dashboard.
echo Press Ctrl+C here when you are finished.
echo.

%PYTHON_CMD% scripts\ls336_web_dashboard.py

echo.
echo Dashboard stopped.
pause
