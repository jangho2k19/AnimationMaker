@echo off
title FlowKit Agent Bridge (Port 8100 + WS 9222)
cd /d "%~dp0flowkit"

REM If user explicitly requested foreground console window with logs:
if "%~1"=="--console" goto console_mode
if "%~1"=="-c" goto console_mode

echo ===============================================================
echo Starting FlowKit Bridge in the BACKGROUND (No Console)...
echo REST API: http://127.0.0.1:8100
echo WebSocket: ws://127.0.0.1:9222
echo Logs saved to: flowkit\flowkit_agent.log
echo ===============================================================

if exist "..\.venv\Scripts\pythonw.exe" (
    start "" "..\.venv\Scripts\pythonw.exe" "%~dp0flowkit\run_background.py"
) else (
    start "" pythonw.exe "%~dp0flowkit\run_background.py"
)

echo.
echo [OK] FlowKit is running in the background!
echo To stop FlowKit anytime, double-click: stop_flowkit.bat
echo (To view live logs in console, run: start_flowkit.bat --console)
echo.
ping -n 3 127.0.0.1 >nul
exit

:console_mode
echo ===============================================================
echo Starting FlowKit Bridge with live console logs...
echo ===============================================================
if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" -m agent.main
) else if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -m agent.main
) else (
    python -m agent.main
)
pause
