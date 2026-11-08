@echo off
chcp 65001 >nul
title SQLite Database Viewer
cd /d "%~dp0"
echo ===================================================
echo  Starting SQLite Database Viewer (app.db)
echo ===================================================
if exist "%LOCALAPPDATA%\Programs\Thonny\python.exe" (
    "%LOCALAPPDATA%\Programs\Thonny\python.exe" view_database.py
) else (
    python view_database.py
)
pause
