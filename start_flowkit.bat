@echo off
title FlowKit Agent Bridge (Port 8100 + WS 9222)
cd /d "%~dp0flowkit"
echo ===============================================================
echo Starting FlowKit Bridge for Google Flow ^& Chrome Extension...
echo REST API: http://127.0.0.1:8100
echo WebSocket: ws://127.0.0.1:9222
echo ===============================================================
python -m agent.main
pause
