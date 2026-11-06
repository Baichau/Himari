# Security & Privacy

- Chat inference uses the configured local Ollama endpoint (`127.0.0.1` by default); history, memories, and tool logs are stored locally in `%USERPROFILE%\.himari\himari.db`.
- Himari does not send telemetry or upload data. Explicit requests to open a website or Spotify search launch the browser/app and can leave the device.
- Screen capture and vision are opt-in. Vision uses a local Ollama model selected by the user.
- File reads and writes are restricted to configured allowed folders. Paths are resolved before access to prevent traversal and symlink escapes.
- File reads, file writes, and shell commands require an in-app confirmation. Confirmation-required tools fail closed when no confirmation handler is available.
- Shell execution and file writes are disabled by default. Opening apps/websites and volume control have separate Settings permissions.
- Tool calls are bounded to five execution rounds per model turn and logged locally. Ollama requests have a configured timeout.
- faster-whisper only loads models from local storage; Himari does not download speech models during normal use.
- Microphone input is used for local speech recognition and is not uploaded.
