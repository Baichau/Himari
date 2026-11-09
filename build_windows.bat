@echo off
setlocal
cd /d %~dp0

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_portable.ps1"
if errorlevel 1 exit /b 1

set "ISCC="
for /f "delims=" %%I in ('where.exe ISCC.exe 2^>nul') do set "ISCC=%%I"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" "%~dp0HimariSetup.iss"
    if errorlevel 1 exit /b 1
    echo Installer built: installer\HimariSetup.exe
) else (
    echo Inno Setup was not found. The portable app is in release\Himari.
)
