@echo off
setlocal
cd /d %~dp0
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1
if exist "wheelhouse" (
    python -m pip install --no-index --find-links "wheelhouse" -r requirements.txt
) else (
    python -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    python -m pip install -r requirements.txt
)
if errorlevel 1 exit /b 1
choice /c YN /m "Download a local multilingual faster-whisper model (large-v3) now"
if errorlevel 2 goto skip_stt
python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8', local_files_only=False)"
if errorlevel 1 echo Speech model download failed. Speech recognition will be unavailable until you prepare a multilingual local model.
:skip_stt
choice /c YN /m "Download the optional Piper en_US-lessac-medium voice now"
if errorlevel 2 goto skip_tts
python -m piper.download_voices --download-dir "%USERPROFILE%\.himari\voices" en_US-lessac-medium
if errorlevel 1 echo Voice download failed. Speech output will be unavailable until you prepare the voice files.
:skip_tts
where.exe ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama was not found. Install Ollama and prepare qwen3:8b before launching Himari.
) else (
    echo Ollama is installed. If needed, prepare the chat model separately with: ollama pull qwen3:8b
)
where.exe tesseract >nul 2>nul
if errorlevel 1 echo Tesseract was not found. Install Tesseract OCR to use OCR-based screen analysis.
echo Setup complete. Run run_himari.bat.
pause
