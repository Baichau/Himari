@echo off
setlocal
cd /d %~dp0
if not exist ".venv\Scripts\python.exe" (
    echo Please run setup_windows.bat first.
    exit /b 1
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --windowed --onedir --name Himari ^
    --collect-all piper ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-all onnxruntime ^
    --collect-all av ^
    --collect-data _sounddevice_data ^
    --add-data "config.example.json;." ^
    --hidden-import PySide6.QtSvg ^
    --hidden-import keyboard ^
    himari_launcher.py
if errorlevel 1 exit /b 1
echo Application built: dist\Himari\Himari.exe
set "ISCC="
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC=%%I"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" HimariSetup.iss
    if errorlevel 1 exit /b 1
    echo Installer built: installer\HimariSetup.exe
) else (
    echo Inno Setup was not found. Install Inno Setup 6 and rerun this script to create HimariSetup.exe.
)
