@echo off
title Fisch Macro - Setup
cd /d "%~dp0"
echo ===================================================
echo  Fisch Macro - one-time setup (Python + all libraries)
echo ===================================================

if not exist "main.py" goto badfolder
if not exist "requirements.txt" goto badfolder

rem -- reuse .venv only if it really works on THIS computer
if not exist ".venv\Scripts\python.exe" goto findpy
".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
if not errorlevel 1 goto install
echo Old .venv was copied from another computer. Removing it...
rmdir /s /q ".venv"

:findpy
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Thonny\python.exe" set PY="%LOCALAPPDATA%\Programs\Thonny\python.exe"
if defined PY goto havepy

echo Python not found. Installing Python 3.12 with winget...
where winget >nul 2>nul
if errorlevel 1 goto nopython
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto havepy

:nopython
echo.
echo [X] Could not install Python automatically.
echo     Download it from https://www.python.org/downloads/
echo     and TICK "Add python.exe to PATH" in the installer.
echo     Then double-click setup.bat again.
goto fail

:havepy
echo Using Python: %PY%
%PY% --version
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)"
if errorlevel 1 goto oldpy
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 goto notk
echo Creating .venv ...
%PY% -m venv .venv
if errorlevel 1 goto fail
goto install

:oldpy
echo [X] Python is too old. Need Python 3.9 or newer.
goto fail

:notk
echo [X] This Python has no tkinter (needed for the app window).
echo     Reinstall Python from python.org with the default options.
goto fail

:install
set "VPY=.venv\Scripts\python.exe"
echo Installing libraries (internet required)...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail
"%VPY%" -c "import fastapi, uvicorn, requests, numpy, PIL, pynput, mss, tkinter"
if errorlevel 1 goto fail
echo.
echo ===================================================
echo  Setup complete.
echo  Run start_backend.bat first, then start_app.bat
echo ===================================================
if /i not "%~1"=="nopause" pause
exit /b 0

:badfolder
echo [X] Put setup.bat in the project folder (next to main.py and requirements.txt).
goto fail

:fail
echo.
echo [X] Setup failed. Take a screenshot of this window and send it for help.
if /i not "%~1"=="nopause" pause
exit /b 1
