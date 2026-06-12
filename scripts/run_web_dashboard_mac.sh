#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo
echo "================================================"
echo "  Lake Shore 336 ARPES Temperature Dashboard"
echo "================================================"
echo

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=python
else
    echo "Python was not found."
    echo
    echo "Please install Python 3 from https://www.python.org/downloads/"
    echo "or install it with Homebrew:"
    echo "  brew install python"
    echo
    read -r -p "Press Enter to close this window..."
    exit 1
fi

echo "Checking Python..."
"${PYTHON_CMD}" --version

echo
echo "Installing required serial driver package if needed..."
"${PYTHON_CMD}" -m pip install -r requirements.txt

echo
echo "Starting the local dashboard..."
echo "A browser window should open at:"
echo "  http://127.0.0.1:8765"
echo
echo "Keep this window open while using the dashboard."
echo "Press Ctrl+C here when you are finished."
echo

"${PYTHON_CMD}" scripts/ls336_web_dashboard.py

echo
echo "Dashboard stopped."
read -r -p "Press Enter to close this window..."
