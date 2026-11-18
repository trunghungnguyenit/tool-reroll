@echo off
cd /d "%~dp0"

set "PYTHON="

if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PYTHON=%LOCALAPPDATA%\Python\bin\python.exe"
)

if not defined PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%i in ('where python ^| findstr /i /v "WindowsApps"') do (
            if not defined PYTHON set "PYTHON=%%i"
        )
    )
)

if not defined PYTHON (
    echo Python chua duoc cai hoac chua add PATH.
    echo.
    echo Cach 1: Cai Python tu https://www.python.org/downloads/ ^(tick Add Python to PATH^)
    echo Cach 2: Tat alias gia trong Settings ^> Apps ^> Advanced app settings ^> App execution aliases
    echo          ^(tat python.exe va python3.exe cua Microsoft Store^)
    pause
    exit /b 1
)

echo Dang dung: %PYTHON%
"%PYTHON%" -m pip install -r requirements.txt -q
"%PYTHON%" main.py
pause
