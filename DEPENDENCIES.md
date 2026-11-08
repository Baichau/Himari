# Dependencies and local models

Python dependencies are listed in `requirements.txt`. They run locally; Himari does not use cloud AI APIs.

- **PySide6** — Windows desktop interface.
- **ollama** — client for the local Ollama service. Qwen3:8B is the default chat model.
- **faster-whisper** — local speech recognition. The multilingual `large-v3-turbo` model can be downloaded during setup and bundled into the standalone app; runtime model downloads are disabled.
- **huggingface-hub** — optional setup-time download of the speech model.
- **piper-tts** — local English speech synthesis. The feminine Amy voice is bundled with the standalone build; its separate CC BY-SA attribution is in `THIRD_PARTY_NOTICES.txt`. Russian speech uses a Russian voice installed in Windows.
- **emoji** — converts emoji to spoken names for TTS only; chat text remains unchanged.
- **sounddevice**, **numpy**, and **av** — microphone/audio processing.
- **mss** and **Pillow** — one-shot screen capture and in-memory image handling.
- **WinRT Windows OCR bindings** — use the Windows-provided OCR engine; no separate OCR application or downloaded OCR model is required.
- **pygetwindow**, **pyautogui**, **psutil**, and **keyboard** — Windows integration and hotkey support.
- **PyInstaller** — application packaging.

Ollama and its model files are separate from Python dependencies. The standalone build includes the multilingual recognition model and English Piper voice when prepared before building. Russian speech and screen OCR use Windows-provided language features. Screen text recognition uses the Windows OCR engine and keeps the captured image in memory only; Himari closes and discards it immediately after recognition. Background web research uses Python's standard-library HTTP client; it sends the focused search terms to DuckDuckGo, returns result snippets and links, and does not open a browser or fetch result pages.

For offline dependency installation, place compatible wheels from `pip download -r requirements.txt -d wheelhouse` in a `wheelhouse` directory beside `setup_windows.bat`. The setup script then installs with `--no-index`. Model and voice downloads are separately prompted; decline to keep setup offline. To build an offline speech-enabled app, prepare the ignored `models\large-v3-turbo` and `models\piper-voices` directories online first and bring them with the source.
