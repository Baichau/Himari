# Security & Privacy

- Chat inference uses the configured local Ollama endpoint (`127.0.0.1` by default); history, memories, and tool logs are stored locally in `%USERPROFILE%\.himari\himari.db`.
- Only an explicit “remember that …” request can create an automatic memory suggestion; suggestions remain unapproved until reviewed in the Memory tab. Heuristic filters are not a substitute for keeping passwords, tokens, and other secrets out of memory.
- Himari does not send telemetry or upload data. Explicit requests to open a website or Spotify search launch the browser/app and can leave the device.
- Screen capture and vision are opt-in. Vision uses a local Ollama model selected by the user.
- Screen capture is controlled in Settings and asks for per-capture confirmation. A capture becomes a chat attachment, stays in memory, is sent only to the local Ollama vision model when you press Send, and is never written to disk. When vision is unavailable, in-memory Windows OCR text is attached instead.
- Active-window detection is disabled by default and is a single foreground-title lookup when enabled and requested; it is not continuous monitoring.
- File reads and writes are restricted to configured allowed folders. Paths are resolved before access to prevent traversal and symlink escapes.
- File reads, file writes, and shell commands require an in-app confirmation. Confirmation-required tools fail closed when no confirmation handler is available.
- Shell execution and file writes are disabled by default. Opening apps/websites and volume control have separate Settings permissions.
- Windows media controls have a separate Settings permission. They send media keys to the active Windows media session and cannot guarantee which application receives them or verify playback state.
- Tool calls are bounded to five execution rounds per model turn and logged locally. Ollama requests have a configured timeout.
- Screen control is off by default and has its own Settings permission. It reads a window's UI Automation tree and acts on a named control or confirmed point only. Every click, typed string, key combination, and scroll asks for confirmation; key combinations always ask again even after a session approval. The Windows key is refused so the agent cannot reach system-level shortcuts, password fields are never filled, and duplicate control names are reported instead of guessed. Himari never launches, closes, or kills processes through this path and never captures continuously.
- There is no image-generation, drawing, or image-editing capability. Himari cannot call a local or remote image model, and the previous local Stable Diffusion engine is no longer installed or shipped.
- faster-whisper only loads models from local storage; Himari does not download speech models during normal use.
- Microphone input is used for local speech recognition and is not uploaded.

## Centralized security layer

`himari.security` is the single decision point for tool execution. Both the chat tool loop and the agent orchestrate through `SecurityLayer.authorize()`.

- Every tool is assigned a risk level (READ, LOW, MEDIUM, HIGH) in `himari/security/policies.py`.
- Unknown tools are denied by default. The model cannot grant itself permissions by passing arguments such as `{"allow": true}`; permissions come only from Settings plus in-session user approval.
- Settings permissions (open app, open URL, web research, read/write file, screen capture, screen control, vision, active window, media control, browser automation) are checked before any risk-based decision.
- HIGH-risk actions require explicit confirmation. Denials and approvals are audited.
- Audit records are written to the local SQLite database with secret-looking keys and values redacted (`[redacted]`); passwords, tokens, and bearer keys are never logged.
- Paths are validated for traversal, blocked system directories, and sensitive names/suffixes (`.env`, private keys, credential stores). Commands are validated against an allowlist of executables and must be argv lists, never raw shell strings.
- Browser automation is off by default. It opens a separate visible Chrome window with an isolated profile and never touches tabs in the user's own Chrome. It refuses payments, CAPTCHA bypass, authentication bypass, and password entry, and requires confirmation before any submit-like click. Page interaction uses a fixed internal script; the model cannot inject JavaScript. Tab actions are scoped to the Himari window and report real page state.
- Development tools only access configured workspaces, refuse sensitive files, and require approval before applying edits or running tests.

