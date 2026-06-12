@echo off
setlocal
cd /d "%~dp0\.."
python -m pip install pyserial
python scripts\ls336_direct_dashboard.py
