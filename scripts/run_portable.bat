@echo off
title Lake Shore 336 Temperature Controller
cd /d "%~dp0"

echo ========================================
echo  Lake Shore 336 Temperature Controller
echo ========================================
echo.
echo Starting web dashboard...
echo.
echo Open your browser to: http://127.0.0.1:8765
echo.
echo Press Ctrl+C in this window to stop.
echo ========================================
echo.

:: Auto-open browser after a short delay
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8765"

:: Run the dashboard
LakeShore336.exe

pause
