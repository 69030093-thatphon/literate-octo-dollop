@echo off
chcp 65001 >nul
title Fisch Macro - Build EXE
cd /d "%~dp0"
echo ===================================================
echo  Build EXE (PyInstaller) - Windows only
echo ===================================================

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo ยังไม่มี .venv กำลังรัน setup.bat ...
    call setup.bat nopause
    if errorlevel 1 goto fail
)

"%VPY%" -m pip install --upgrade pyinstaller
if errorlevel 1 goto fail

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [1/3] fisch_backend.exe
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --name fisch_backend ^
  --collect-submodules uvicorn ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  main.py
if errorlevel 1 goto fail

echo.
echo [2/3] fisch_macro.exe
"%VPY%" -m PyInstaller --noconfirm --onefile --windowed --name fisch_macro fisch_macro.py
if errorlevel 1 goto fail

echo.
echo [3/3] view_database.exe
"%VPY%" -m PyInstaller --noconfirm --onefile --windowed --name view_database view_database.py
if errorlevel 1 goto fail

copy /y settings.example.json dist\settings.example.json >nul

echo.
echo ===================================================
echo  เสร็จแล้ว ไฟล์อยู่ในโฟลเดอร์ dist\
echo    fisch_backend.exe  - เปิดก่อน
echo    fisch_macro.exe    - แอปหลัก
echo    view_database.exe  - ดูฐานข้อมูล
echo ===================================================
if /i not "%~1"=="nopause" pause
exit /b 0

:fail
echo.
echo [X] Build ล้มเหลว
if /i not "%~1"=="nopause" pause
exit /b 1
