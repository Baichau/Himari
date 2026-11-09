# Himari 3.0 development (ひまり) — Local AI Desktop Companion

Himari is a Windows desktop companion built with PySide6. Chat and inference use a locally running Ollama service; conversation history and memories are stored in a local SQLite database. It does not use hosted AI APIs or telemetry. Optional, user-requested web research sends focused search terms to DuckDuckGo; it does not send chat history.

## Current capabilities

- Streaming Ollama chat with Qwen3 and bounded native tool calling.
- Quiet, source-linked background web research for news and current questions; no browser window is opened.
- Push-to-talk recording, local faster-whisper transcription, and interruptible English Piper / Windows Russian speech output.
- Selectable input microphone, F9 push-to-talk, multilingual speech recognition, chat, editable memories, and local history.
- One-shot, user-confirmed primary-screen capture with a global F10 hotkey and Windows OCR; screenshot images are discarded from memory after text extraction.
- Permission-gated app/browser launches, Spotify search, Steam game launch, system volume, and confirmed file access.
- Optional Windows media-key controls. They target the active media session and cannot confirm which app handled a command or whether playback changed.
- Optional draggable floating avatar window with support for original transparent PNG expression and animation sprites.
- File tools are restricted to the folders listed under **Settings**. File writes and shell use are disabled by default.
- PyInstaller Windows build and Inno Setup installer scripts.

## Requirements and setup

1. Use 64-bit Windows 10/11 and install Python 3.10+ and Ollama. Windows OCR uses the system's installed OCR languages.
2. Run `setup_windows.bat` to install Python dependencies. Speech model and Piper voice downloads are separately prompted; they are optional and never happen during application startup.
3. Prepare the local chat model yourself with `ollama pull qwen3:8b` while online. Himari does not download Ollama models. Start Ollama before launching.
4. Run `run_himari.bat`. If speech assets are unavailable, their features report an error rather than downloading a model on first use.
5. To build the portable Windows release, prepare the build environment and run the PowerShell command below. It creates an onedir app in `release\Himari`; no model is downloaded during the build.

```powershell
.\build_portable.ps1 -RequireOllama
```

## Running the portable Windows application

Copy the entire `release\Himari` folder to a writable or read-only install location and run `Himari.exe`. Keep the adjacent `_internal` folder intact. Python is not needed. Ollama is installed separately and its local models are not bundled. If Ollama is unavailable or the selected model is missing, the UI and log explain how to connect/install it; Himari never downloads an Ollama model.

Speech recognition uses only model files already bundled with Himari or present in the local Hugging Face cache. The build script copies a complete local model into the distribution when one is available; it does not access the network to fetch weights. The currently tested distribution includes `base.en`, which is English-only and does not reliably recognize Russian. To build with multilingual recognition, prepare a complete multilingual model such as `large-v3-turbo` locally before building. Piper voices are bundled when prepared locally; additional local voices may be placed in `%USERPROFILE%\.himari\voices`. Russian replies use an installed Russian Windows speech voice if no Russian Piper voice is available. Voice assets are optional for chat-only operation. The application stores settings, database, temporary audio, and rotating logs in `%USERPROFILE%\.himari` (or the directory specified by `HIMARI_HOME`), never beside the installed executable. Windows OCR reads languages installed in Windows. Screen capture is explicit and one-shot: the user must enable it in Settings, confirm the prompt, and then extracted text (not the image) is sent to the local chat model.

The portable release includes a `--self-test` mode. To validate dependencies and models and open/close the packaged UI once, run:

```powershell
.\release\Himari\Himari.exe --self-test --gui
```

Add `--require-ollama` to require a running local Ollama service and the configured model. The same test is run automatically by `build_portable.ps1`.

When you ask for news or current research, Himari can quietly query DuckDuckGo over HTTPS and return a short summary with source links. It searches only when relevant or explicitly requested, does not open Chrome, and does not download pages or add browser automation. Search terms are sent to DuckDuckGo; background research can be disabled in **Settings**. If the search service cannot be reached, Himari reports that it could not verify current information instead of guessing. Normal chat remains local to Ollama.

## Offline preparation

On an internet-connected Windows machine with the same Python version and architecture, download compatible wheels into a `wheelhouse` folder:

```powershell
python -m pip download -r requirements.txt -d wheelhouse
```

Copy the project and `wheelhouse` to the offline machine, then run `setup_windows.bat`; it uses `pip --no-index`. To prepare a standalone speech-enabled build offline, first run setup on an internet-connected machine and copy the ignored `models\large-v3-turbo` and `models\piper-voices` folders with the project. Separately install Ollama and prepare its `qwen3:8b` model, and add Russian Windows speech/OCR languages if needed. Ollama model files are not included in the installer. Background web research and explicit website/Spotify actions require an internet connection.

## Use and privacy

Press F9 (or the microphone button) once to start recording and press it again to stop; Himari then transcribes locally and sends the recognized text to the assistant. No wake word is required. Push-to-talk recording stays active through pauses so a short break in speech will not cut off a sentence. In Settings, choose Automatic for multilingual language detection, or select English or Russian when you want to constrain recognition. Recognition uses the locally bundled faster-whisper model, app-name hotwords, beam search, audio level normalization, and voice-activity detection. Clear commands to open Minecraft Launcher are normalized when transcription slightly misspells its name. The included model depends on the assets prepared before building; this tested release contains the English-only `base.en` model. Optional wake-word listening can instead monitor for the exact phrase "Himari" using local faster-whisper transcription, with an opt-in toggle and visual indicator. Spotify opens a search and does not claim playback; Himari does not currently control Spotify playback. Steam games are matched by exact installed library title. File operations need per-action confirmation and must remain inside a folder explicitly allowed in Settings.

Screen capture happens only after it is enabled in **Settings** and the user presses the global capture key, clicks its one-shot button, or explicitly requests screen reading and confirms the prompt; no live capture is available. The capture key is configurable in **Settings**. Himari must still be running in the system tray; the shortcut is not available after choosing **Quit**. The screenshot is passed through in-memory OCR, then closed and discarded. OCR extracts visible text and is not complete visual understanding. Active-window detection is off by default and only checks the foreground window when requested and enabled. Windows media controls are separately permission-gated and send media keys to the active Windows media session; they may affect an app other than Spotify and do not confirm playback state. Shell commands are off by default. General file writes remain scoped to allowed folders and require confirmation; the dedicated Desktop text-file action is limited to `.txt` files on the Desktop and also requires confirmation. Website, app, screen, active-window, and media permissions can be changed in **Settings**. Tool activity is logged locally in `%USERPROFILE%\.himari\himari.db`.

## Avatar customization

The sprite renderer accepts original transparent PNG assets. Add them to `%USERPROFILE%\.himari\avatar_assets` to keep them across updates, or to `himari\avatar_assets` while developing. Use `idle.png`, `listening.png`, `thinking.png`, `speaking_01.png` / `speaking_02.png`, and optional expression files such as `happy.png`, `confused.png`, `sad.png`, and `error.png`. Without artwork, Himari displays a clear placeholder rather than a geometric character mockup. See [AVATAR_GUIDE.md](./AVATAR_GUIDE.md) for sizing, animation names, and the optional future Live2D integration boundary.

Memory suggestions are created only when you explicitly say “remember that …”, and appear as unapproved items in **Memory**. Review, approve, or reject them there. Obvious credential phrases and short-lived facts are filtered; do not use memory for secrets. Search in the Memory tab currently uses local lexical matching, not embeddings or semantic search.

## Development

See [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) for architecture, implementation decisions, and remaining milestones. Changes are tracked in [CHANGELOG.md](./CHANGELOG.md). The current memory search is local lexical matching (including Cyrillic); embeddings are not installed or described as semantic search.

Run tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### Reproducible portable build

Use 64-bit Windows Python 3.10–3.13, install dependencies, and pin the release packager to the version in `requirements-build.txt`:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
.\build_portable.ps1
```

The build requires a clean `release\Himari` destination and refuses to overwrite an existing release. It runs syntax checks and the test suite, stages only already-local Faster-Whisper/Piper assets, builds the onedir distribution, and runs its packaged self-test. If models/voices are not staged, setup can be rerun to prepare them explicitly; `-AllowMissingSpeechAssets` allows a chat-only build with clear startup warnings. To require Ollama and the selected local model in the smoke test, use `.\build_portable.ps1 -RequireOllama`. The build script does not invoke `ollama pull` or download speech models.

`build_windows.bat` delegates to the same portable build and optionally creates an Inno Setup installer from the onedir output.
