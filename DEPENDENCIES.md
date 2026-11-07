# Dependencies and local models

Python dependencies are listed in `requirements.txt`. They run locally; Himari does not use cloud AI APIs.

- **PySide6** — Windows desktop interface.
- **ollama** — client for the local Ollama service. Qwen3:8B is the default chat model.
- **faster-whisper** — local speech recognition. The multilingual `large-v3-turbo` model can be downloaded during setup and bundled into the standalone app; runtime model downloads are disabled.
- **huggingface-hub** — optional setup-time download of the speech model.
- **piper-tts** — local speech synthesis. Voice model files are downloaded separately and are not bundled.
- **sounddevice**, **numpy**, and **av** — microphone/audio processing.
- **mss**, **Pillow**, and **pytesseract** — local screen capture and OCR. Tesseract OCR itself must be installed separately.
- **pygetwindow**, **pyautogui**, **psutil**, and **keyboard** — Windows integration and hotkey support.
- **PyInstaller** — application packaging.

Ollama and its model files are separate from Python dependencies. A vision model is optional and is never fetched by Himari. The multilingual speech model is optional and is bundled only when downloaded before building.

For offline dependency installation, place compatible wheels from `pip download -r requirements.txt -d wheelhouse` in a `wheelhouse` directory beside `setup_windows.bat`. The setup script then installs with `--no-index`. Model and voice downloads are separately prompted; decline to keep setup offline. To build an offline speech-enabled app, prepare the ignored `models\large-v3-turbo` directory online first and bring it with the source.
