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
    echo Khong tim thay Python.
    pause
    exit /b 1
)

echo Dang cai PyInstaller...
"%PYTHON%" -m pip install -r requirements.txt pyinstaller -q

echo Dang dong goi TFT Auto Buy...
"%PYTHON%" -m PyInstaller --noconfirm --clean TFT_Auto_Buy.spec

if errorlevel 1 (
    echo Build that bai.
    pause
    exit /b 1
)

echo.
echo Xong! File exe: dist\TFT_Auto_Buy.exe
echo Copy dist\TFT_Auto_Buy.exe ra cho nguoi dung — lan dau chay se tu tao thu muc data\
echo Nen chay exe bang quyen Administrator de dung phim F8 va click vao game.
pause
