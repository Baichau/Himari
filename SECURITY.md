# Security & Privacy

- Chat inference uses the configured local Ollama endpoint (`127.0.0.1` by default); history, memories, and tool logs are stored locally in `%USERPROFILE%\.himari\himari.db`.
- Only an explicit “remember that …” request can create an automatic memory suggestion; suggestions remain unapproved until reviewed in the Memory tab. Heuristic filters are not a substitute for keeping passwords, tokens, and other secrets out of memory.
- Himari does not send telemetry or upload data. Explicit requests to open a website or Spotify search launch the browser/app and can leave the device.
- Screen capture and vision are opt-in. Vision uses a local Ollama model selected by the user.
- Screen capture is controlled in Settings and asks for per-capture confirmation. OCR-only captures are local; the image is discarded after text extraction.
- Active-window detection is disabled by default and is a single foreground-title lookup when enabled and requested; it is not continuous monitoring.
- File reads and writes are restricted to configured allowed folders. Paths are resolved before access to prevent traversal and symlink escapes.
- File reads, file writes, and shell commands require an in-app confirmation. Confirmation-required tools fail closed when no confirmation handler is available.
- Shell execution and file writes are disabled by default. Opening apps/websites and volume control have separate Settings permissions.
- Windows media controls have a separate Settings permission. They send media keys to the active Windows media session and cannot guarantee which application receives them or verify playback state.
- Tool calls are bounded to five execution rounds per model turn and logged locally. Ollama requests have a configured timeout.
- faster-whisper only loads models from local storage; Himari does not download speech models during normal use.
- Microphone input is used for local speech recognition and is not uploaded.
