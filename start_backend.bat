@echo off
chcp 65001 >nul
title Fisch Macro Backend
cd /d "%~dp0"
echo ===================================================
echo  Starting Fisch Macro Backend (FastAPI)
echo  API Documentation: http://127.0.0.1:8000/docs
echo ===================================================
if exist "%LOCALAPPDATA%\Programs\Thonny\python.exe" (
    "%LOCALAPPDATA%\Programs\Thonny\python.exe" main.py
) else (
    python main.py
)
pause
