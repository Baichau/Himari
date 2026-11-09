# Dependencies and local models

Python dependencies are listed in `requirements.txt`. They run locally; Himari does not use cloud AI APIs.

- **PySide6** — Windows desktop interface.
- **ollama** — client for the local Ollama service. Qwen3:8B is the default chat model.
- **faster-whisper** — local speech recognition. The portable build includes a complete model found in the repository's ignored `models` directory or local Hugging Face cache. Runtime model downloads are disabled.
- **huggingface-hub** — optional setup-time download of the speech model.
- **piper-tts** — local English speech synthesis. Locally prepared Piper `.onnx` models and metadata are bundled; additional voices can be kept under `%USERPROFILE%\.himari\voices`. Voice attributions are in `THIRD_PARTY_NOTICES.txt`. Russian speech can use a Russian voice installed in Windows.
- **emoji** — converts emoji to spoken names for TTS only; chat text remains unchanged.
- **sounddevice**, **numpy**, and **av** — microphone/audio processing.
- **mss** and **Pillow** — one-shot screen capture and in-memory image handling.
- **WinRT Windows OCR bindings** — use the Windows-provided OCR engine; no separate OCR application or downloaded OCR model is required.
- **pygetwindow**, **pyautogui**, **psutil**, and **keyboard** — Windows integration and hotkey support.
- **PyInstaller 6.22.3** — pinned portable onedir application packaging.

Ollama and its model files are separate from Python dependencies. The portable build script copies already-local speech assets and runs a packaged self-test; it never downloads models. If assets are missing, build explicitly with `-AllowMissingSpeechAssets` for chat-only mode. Russian speech and screen OCR use Windows-provided language features. Screen text recognition uses the Windows OCR engine and discards the captured image after recognition. Background web research uses Python's standard-library HTTP client; it sends focused search terms to DuckDuckGo, returns result snippets and links, and does not open a browser or fetch result pages. Ollama and its model files always remain external and must be prepared by the user.

For offline dependency installation, place compatible wheels from `pip download -r requirements.txt -d wheelhouse` in a `wheelhouse` directory beside `setup_windows.bat`. The setup script then installs with `--no-index`. Model and voice downloads are separately prompted; decline to keep setup offline. To build an offline speech-enabled app, prepare the ignored `models\large-v3-turbo` and `models\piper-voices` directories online first and bring them with the source.
