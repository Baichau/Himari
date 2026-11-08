# Himari 2.0 (ひまり) — Local AI Desktop Companion

Himari is a Windows desktop companion built with PySide6. Chat and inference use a locally running Ollama service; conversation history and memories are stored in a local SQLite database. It does not use hosted AI APIs or telemetry. Optional, user-requested web research sends focused search terms to DuckDuckGo; it does not send chat history.

## Current capabilities

- Streaming Ollama chat with Qwen3 and bounded native tool calling.
- Quiet, source-linked background web research for news and current questions; no browser window is opened.
- Push-to-talk recording, local faster-whisper transcription, and interruptible English Piper / Windows Russian speech output.
- Selectable input microphone, F9 push-to-talk, multilingual speech recognition, chat, editable memories, and local history.
- One-shot, user-confirmed primary-screen capture with a global F10 hotkey and Windows OCR; screenshot images are discarded from memory after text extraction.
- Permission-gated app/browser launches, Spotify search, Steam game launch, system volume, and confirmed file access.
- File tools are restricted to the folders listed under **Settings**. File writes and shell use are disabled by default.
- PyInstaller Windows build and Inno Setup installer scripts.

## Requirements and setup

1. Use 64-bit Windows 10/11 and install Python 3.10+ and Ollama. Windows OCR uses the system's installed OCR languages.
2. Run `setup_windows.bat`. It installs Python dependencies. Answer **Yes** when prompted to download the multilingual faster-whisper `large-v3-turbo` model and the feminine English Piper Amy voice. Both are bundled into the standalone Windows build. Himari uses the speech model for automatic language detection and app-name recognition.
3. Prepare the local chat model yourself with `ollama pull qwen3:8b` while online. Himari does not download Ollama models. Start Ollama before launching.
4. Run `run_himari.bat`. If speech assets are unavailable, their features report an error rather than downloading a model on first use.
5. To build the Windows application, run `build_windows.bat`. It produces the single-file `dist\Himari.exe`; with Inno Setup 6 installed it also produces `installer\HimariSetup.exe`.

## Running the standalone Windows application

Install Ollama and prepare its chat model with `ollama pull qwen3:8b`, then run `Himari.exe`. Python and the Himari source folder are not needed. The single EXE contains Himari's application and bundled speech assets; it extracts them to a temporary directory while running, so leave enough free disk space and expect the first launch to take longer. Ollama and its chat model remain separate.

Speech recognition runs locally. Himari prefers its bundled multilingual `large-v3-turbo` model and otherwise uses a compatible model already cached on the machine. The bundled model is under 3 GB and is included in the single-file `dist\Himari.exe` when prepared before building. Model weights are not committed to GitHub. The single EXE is large (the speech model alone is about 1.6 GB); on launch, it extracts its bundled files into a temporary directory, so the first launch can take a while and Windows needs additional free disk space. Keep the EXE intact and do not remove its temporary files while Himari is running. Ollama is still installed separately, and its chat model is not included. If no multilingual model is available, Automatic may fall back to an English-only model, which will not reliably recognize other languages. The standalone build includes the feminine Amy English voice. Russian replies use the installed Russian Windows speech voice (for example, Microsoft Irina); add a Russian speech voice in Windows Settings if one is unavailable. Emoji are expanded into spoken names without changing the displayed conversation. Himari synthesizes each full reply in one clip per language so it does not skip between sentences, and starts speaking only once the final response text is present in the chat. Windows OCR reads English or other OCR languages installed in Windows. Screen capture is explicit and one-shot: click **Capture Screen** or press the configurable global screen-capture key (F10 by default), confirm the capture, and Himari sends extracted text (not the image) to the local chat model. Himari can capture while its window is hidden in the system tray, then brings the window forward to show the result. Closing the window keeps Himari running in the tray when **Minimize to tray** is enabled; choose **Quit** from the tray menu to disable the hotkeys and exit. The screenshot stays in memory only and is discarded immediately after OCR.

When you ask for news or current research, Himari can quietly query DuckDuckGo over HTTPS and return a short summary with source links. It searches only when relevant or explicitly requested, does not open Chrome, and does not download pages or add browser automation. Search terms are sent to DuckDuckGo; background research can be disabled in **Settings**. If the search service cannot be reached, Himari reports that it could not verify current information instead of guessing. Normal chat remains local to Ollama.

## Offline preparation

On an internet-connected Windows machine with the same Python version and architecture, download compatible wheels into a `wheelhouse` folder:

```powershell
python -m pip download -r requirements.txt -d wheelhouse
```

Copy the project and `wheelhouse` to the offline machine, then run `setup_windows.bat`; it uses `pip --no-index`. To prepare a standalone speech-enabled build offline, first run setup on an internet-connected machine and copy the ignored `models\large-v3-turbo` and `models\piper-voices` folders with the project. Separately install Ollama and prepare its `qwen3:8b` model, and add Russian Windows speech/OCR languages if needed. Ollama model files are not included in the installer. Background web research and explicit website/Spotify actions require an internet connection.

## Use and privacy

Press F9 (or the microphone button) once to start recording and press it again to stop; Himari then transcribes locally and sends the recognized text to the assistant. No wake word is required. Push-to-talk recording stays active through pauses so a short break in speech will not cut off a sentence. In Settings, choose Automatic for multilingual language detection, or select English or Russian when you want to constrain recognition. Recognition uses the local faster-whisper model, app-name hotwords, beam search, audio level normalization, and voice-activity detection. Clear commands to open Minecraft Launcher are normalized when transcription slightly misspells its name. The bundled `large-v3-turbo` model supports broad multilingual recognition without a separate model download after installation. Optional wake-word listening can instead monitor for the exact phrase "Himari" using local faster-whisper transcription, with an opt-in toggle and visual indicator. Spotify opens a search and does not claim playback; Himari does not currently control Spotify playback. Steam games are matched by exact installed library title. File operations need per-action confirmation and must remain inside a folder explicitly allowed in Settings.

Screen capture happens only after the user presses the global capture key, clicks its one-shot button, or explicitly requests screen reading, and confirms the prompt; no live capture is available. The capture key is configurable in **Settings**. Himari must still be running in the system tray; the shortcut is not available after choosing **Quit**. The screenshot is passed through in-memory OCR, then closed and discarded. Shell commands are off by default. General file writes remain scoped to allowed folders and require confirmation; the dedicated Desktop text-file action is limited to `.txt` files on the Desktop and also requires confirmation. Website and app launch permissions can be changed in Settings. Tool activity is logged locally in `%USERPROFILE%\.himari\himari.db`.

Run tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
