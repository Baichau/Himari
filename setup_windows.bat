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
choice /c YN /m "Download and bundle the multilingual faster-whisper large-v3-turbo model (1.62 GB) now"
if errorlevel 2 goto skip_stt
python prepare_speech_model.py
if errorlevel 1 echo Speech model download failed. Rerun setup_windows.bat and choose Yes before building the standalone app.
:skip_stt
choice /c YN /m "Download and bundle the English feminine Piper en_US-amy-medium voice now"
if errorlevel 2 goto skip_tts
python -m piper.download_voices --download-dir "models\piper-voices" en_US-amy-medium
if errorlevel 1 echo Voice download failed. Run setup_windows.bat again and choose Yes before building.
:skip_tts
where.exe ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama was not found. Install Ollama and prepare qwen3:8b before launching Himari.
) else (
    echo Ollama is installed. If needed, prepare the chat model separately with: ollama pull qwen3:8b
)
echo Setup complete. Run run_himari.bat.
pause
