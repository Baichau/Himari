@echo off
setlocal
cd /d %~dp0
if not exist ".venv\Scripts\python.exe" (
    echo Please run setup_windows.bat first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1
python -m himari.main
pause
