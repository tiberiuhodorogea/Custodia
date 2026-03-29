@echo off
echo ============================================
echo   Backup Service - Install
echo ============================================
echo.

:: Check for admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click and select "Run as administrator".
    pause
    exit /b 1
)

:: Install and start
python "%~dp0service.py" install
python "%~dp0service.py" start

echo.
echo Service installed and started.
echo Dashboard: http://localhost:8550
echo.
pause
