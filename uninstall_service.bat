@echo off
echo ============================================
echo   Custodia - Uninstall
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

:: Stop and remove
python "%~dp0service.py" stop
python "%~dp0service.py" remove

echo.
echo Service stopped and removed.
echo.
pause
