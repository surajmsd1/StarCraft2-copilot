@echo off
rem Double-click me. First run installs everything (about a minute), after that it just opens.
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python is not installed.
    echo Get it from https://www.python.org/downloads/  - and tick "Add Python to PATH" in the installer.
    echo Then double-click this file again.
    pause
    exit /b 1
)

if not exist .venv (
    echo First-time setup, this takes a minute...
    py -3 -m venv .venv || goto :fail
    .venv\Scripts\pip install -e .[tts] || goto :fail
)

start "" .venv\Scripts\pythonw.exe -m sc2copilot.gui.app
exit /b 0

:fail
echo Setup failed - scroll up for the error, or ask for help with a screenshot of it.
pause
exit /b 1
