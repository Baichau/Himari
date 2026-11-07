# Himari 2.0 (ひまり) — Local AI Desktop Companion

Himari is a Windows desktop companion built with PySide6. Chat and inference use a locally running Ollama service; conversation history and memories are stored in a local SQLite database. No hosted AI service or telemetry is used.

## Current capabilities

- Streaming Ollama chat with Qwen3 and bounded native tool calling.
- Push-to-talk recording, local faster-whisper transcription, and interruptible Piper speech output.
- Selectable input microphone, F9 push-to-talk, multilingual speech recognition, chat, editable memories, and local history.
- Opt-in screen capture, Tesseract OCR, and optional vision through a separately installed local Ollama model.
- Permission-gated app/browser launches, Spotify search, Steam game launch, system volume, and confirmed file access.
- File tools are restricted to the folders listed under **Settings**. File writes and shell use are disabled by default.
- PyInstaller Windows build and Inno Setup installer scripts.

## Requirements and setup

1. Use 64-bit Windows 10/11 and install Python 3.10+, Ollama, and (for OCR) Tesseract.
2. Run `setup_windows.bat`. It installs Python dependencies. Answer **Yes** when prompted to download the multilingual faster-whisper `large-v3-turbo` model. The model is about 1.62 GB and is bundled into the standalone Windows build. Himari uses it for automatic language detection and better app-name recognition. The script separately asks before downloading a Piper voice.
3. Prepare the local chat model yourself with `ollama pull qwen3:8b` while online. Himari does not download Ollama models. Start Ollama before launching.
4. Run `run_himari.bat`. If the speech model or Piper voice is not prepared, their features report an error rather than downloading a model on first use.
5. To build the Windows application, run `build_windows.bat`. It produces `dist\Himari\Himari.exe`; with Inno Setup 6 installed it also produces `installer\HimariSetup.exe`.

Speech recognition runs locally. Himari prefers its bundled multilingual `large-v3-turbo` model and otherwise uses a compatible model already cached on the machine. The bundled model is under 3 GB and is included in `dist\Himari` when prepared before building. Model weights are not committed to GitHub. If no multilingual model is available, Automatic may fall back to an English-only model, which will not reliably recognize other languages. The optional Piper files belong in `%USERPROFILE%\.himari\voices`; choose an installed English or Russian voice in Settings when available. A local vision-capable Ollama model must be installed and selected separately; the default Qwen chat model is not a vision model. Tesseract is an external install and is not bundled.

## Offline preparation

On an internet-connected Windows machine with the same Python version and architecture, download compatible wheels into a `wheelhouse` folder:

```powershell
python -m pip download -r requirements.txt -d wheelhouse
```

Copy the project and `wheelhouse` to the offline machine, then run `setup_windows.bat`; it uses `pip --no-index`. To prepare a standalone speech-enabled build offline, first run setup on an internet-connected machine and copy the ignored `models\large-v3-turbo` folder with the project. Separately install Ollama and prepare its `qwen3:8b` model, prepare a Piper voice, and install Tesseract if OCR is needed. Ollama model files are not included in the installer. Explicit website/Spotify actions still open external services and require a network.

## Use and privacy

Press F9 (or the microphone button) once to start recording and press it again to stop; Himari then transcribes locally and sends the recognized text to the assistant. No wake word is required. Push-to-talk recording stays active through pauses so a short break in speech will not cut off a sentence. In Settings, choose Automatic for multilingual language detection, or select English or Russian when you want to constrain recognition. Recognition uses the local faster-whisper model, app-name hotwords, beam search, audio level normalization, and voice-activity detection. Clear commands to open Minecraft Launcher are normalized when transcription slightly misspells its name. The bundled `large-v3-turbo` model supports broad multilingual recognition without a separate model download after installation. Optional wake-word listening can instead monitor for the exact phrase "Himari" using local faster-whisper transcription, with an opt-in toggle and visual indicator. Spotify opens a search and does not claim playback; Himari does not currently control Spotify playback. Steam games are matched by exact installed library title. File operations need per-action confirmation and must remain inside a folder explicitly allowed in Settings.

Screen capture is off by default. Shell commands and file writes are off by default and require confirmation when enabled. Website and app launch permissions can be changed in Settings. Tool activity is logged locally in `%USERPROFILE%\.himari\himari.db`.

Run tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
