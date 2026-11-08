@echo off
chcp 65001 >nul
title Fisch Macro App
cd /d "%~dp0"
echo ===================================================
echo  Starting Fisch Macro Desktop App
echo ===================================================
if exist "%LOCALAPPDATA%\Programs\Thonny\python.exe" (
    "%LOCALAPPDATA%\Programs\Thonny\python.exe" fisch_macro.py
) else (
    python fisch_macro.py
)
pause
