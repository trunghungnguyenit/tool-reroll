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

echo Dang cai thu vien build (PyInstaller da ghim phien ban)...
"%PYTHON%" -m pip install -r requirements-build.txt -q
if errorlevel 1 (
    echo Cai thu vien that bai.
    pause
    exit /b 1
)

echo Dang chay test truoc khi dong goi...
"%PYTHON%" -m pytest -q -p no:cacheprovider
if errorlevel 1 (
    echo Test that bai - KHONG dong goi de tranh tao exe loi.
    pause
    exit /b 1
)

echo Dang dong goi TFT Auto Buy...
"%PYTHON%" -m PyInstaller --noconfirm --clean TFT_Auto_Buy.spec
if errorlevel 1 (
    echo Build that bai.
    pause
    exit /b 1
)

echo Dang kiem tra exe vua tao (--selftest)...
start /wait "" "dist\TFT_Auto_Buy.exe" --selftest
set "SELFTEST_CODE=%errorlevel%"
if exist "%TEMP%\TFT_Auto_Buy_selftest.txt" type "%TEMP%\TFT_Auto_Buy_selftest.txt"
if not "%SELFTEST_CODE%"=="0" (
    echo Exe vua tao tu kiem tra LOI - xem ket qua o tren.
    pause
    exit /b 1
)

echo.
echo Xong! File exe: dist\TFT_Auto_Buy.exe
echo Copy dist\TFT_Auto_Buy.exe ra cho nguoi dung - lan dau chay se tu tao thu muc data\
echo Nen chay exe bang quyen Administrator de dung phim F8 va click vao game.
echo Mo app len, dong "Phien ban:" trong Nhat ky cho biet ngay gio build.
pause
