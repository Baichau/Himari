@echo off
setlocal
cd /d %~dp0
if not exist ".venv\Scripts\python.exe" (
    echo Please run setup_windows.bat first.
    exit /b 1
)
if not exist "models\large-v3-turbo\model.bin" (
    echo The bundled multilingual speech model is missing.
    echo Run setup_windows.bat and choose Yes to prepare it, then rebuild.
    exit /b 1
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean Himari.spec
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
