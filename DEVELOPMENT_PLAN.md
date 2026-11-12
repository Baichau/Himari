# Himari development plan

## Current architecture

- `himari/ui.py` owns the PySide6 application window, chat shell (recent-chat
  sidebar, rich transcript, streaming and stop control, voice-reply switch,
  attachment composer), settings, activity list, Dashboard and Diagnostics
  tabs, agent task controls, tray behavior, microphone controls, and
  worker-thread orchestration.
- `himari/theme.py` defines the dark/light palettes and QSS, and
  `himari/chat_format.py` renders the classic, dependency-free Markdown
  transcript. `himari/chat_web.py` renders the default chat in an embedded
  QtWebEngine page with sanitized markdown-it output, stashed LaTeX (KaTeX),
  and Mermaid diagram blocks; all assets under `himari/web_assets` are bundled
  and the page is locked down with a strict Content-Security-Policy.
- `himari/llm.py` streams local Ollama chat and executes a bounded set of
  dedicated tools. `himari/vision.py` sends explicitly attached images to a
  local vision-language model, and `himari/attachments.py` reads images, PDF,
  DOCX, XLSX, and text files into bounded in-memory context.
- `himari/imagegen.py` calls an A1111-compatible local `/sdapi/v1/txt2img`
  server (`sd-server` or Automatic1111/Forge) and saves results under the
  user's Himari folder; it is permission-gated by `allow_image_generation`.
  When no server answers, it can launch the managed install under
  `%USERPROFILE%\.himari\imagegen` on demand and waits for the API, using fixed
  paths rather than model-generated commands. The portable build embeds those
  assets in the executable as an appended ZIP (`himari/imagegen_payload.py`)
  and unpacks them once on first use. Before rendering, it asks local Ollama to
  unload the chat and vision models so Stable Diffusion has the GPU to itself.
- `himari/agent/` is a separate bounded agent loop (`planner`, `executor`,
  `tool_registry`, `orchestrator`, `state`). It reuses `himari.tools.TOOLS`,
  queries the same local Ollama model, and sends every call through
  `himari.security`.
- `himari/security/` centralizes risk levels, permission mapping, confirmation,
  path/command validation, and redacted audit records. Unknown tools are denied.
- `himari/windows/` provides Windows-native app/process/window discovery and
  graceful close requests. `himari/perception/` wraps one-shot capture, Windows
  OCR, active-window context, and a structured scene.
- `himari/browser/` uses local Playwright with installed browser channels and a
  dedicated session thread, so its visible window keeps tabs between messages;
  `himari/integrations/` reports and drives Chrome, Spotify, Steam, VS Code, and
  Discord capabilities; `himari/development/` provides workspace-confined file,
  search, edit, and test tools.
- `himari/memory/` extends the existing SQLite memories with categories,
  dedupe, bounded retrieval, and summaries. `himari/personality/` adds persona
  settings, technical mode, and avatar expression definitions.
- `himari/control/` contains Qt-free dashboard, settings, permission, memory,
  activity, and diagnostics backends used by the UI.
- `himari/tools.py` contains local Windows integrations, path validation,
  permission checks, confirmation metadata, and activity logging.
- `himari/voice.py` provides local Faster-Whisper recognition, microphone
  capture, and Piper/Windows speech output.
- `himari/screen.py` captures a requested screen once. Screenshots are attached
  to the message in memory and analyzed by the local vision model on Send;
  Windows OCR is kept as a fallback. No screenshot is written to disk.
- `himari/db.py` stores local history, summaries, memories, and action records
  in the existing SQLite database.
- `himari/avatar.py` is the renderer boundary for optional original PNG sprites
  and a floating companion window.

## Implementation decisions

1. Keep Ollama, SQLite, Faster-Whisper, Piper, and PySide6; do not introduce a
   cloud service or automatic model downloads.
2. Keep F9 as the primary push-to-talk control and retain one-shot confirmation
   for screen capture.
3. Use explicit settings gates for screen capture and Windows media controls.
   Shell execution stays disabled; app closing uses a normal close request.
4. Keep avatar artwork user-supplied. The renderer supports transparent sprites
   and clearly identifies the missing-art fallback instead of depicting simple
   shapes as finished character art.
5. Add features behind tested local interfaces and preserve existing database
   records and configuration through default-value merging.
6. Keep one authorization path: chat tools, wrapped tools, and the agent all go
   through `himari.security`. The model cannot grant permissions or bypass
   confirmations, submit-like browser actions always ask again, and unknown
   tools are denied.
7. Run long UI work (dashboard, diagnostics, Ollama checks, agent tasks) in
   worker threads and update widgets through Qt signals.

## Completed in the 4.0 development pass

- Bounded agent loop with planning, per-step permission checks, observation,
  verification, cancellation, five-round limit, and no automatic retries of
  denied or failed high-risk actions.
- Centralized security with risk classification, Settings permission mapping,
  path and command validation, confirmation for consequential actions, and
  audit redaction.
- Windows discovery, screen perception, browser automation, integrations,
  workspace-confined development tools, categorized memory, personality
  settings, and Control Center backends, each with mocked tests.
- Dashboard, Diagnostics, and agent task controls added to the existing window
  without replacing chat, voice, tray, or avatar behavior.
- Chat shell rebuilt around local session history: recent-chat sidebar, restored
  last session, safe Markdown transcript with code/lists/links, per-message
  timestamps, streaming cursor, cancel/stop for in-flight replies
  (`LLMCancelled` keeps partial output), and a persistent voice-reply toggle.
- Chat management and memory capture: confirmed per-chat deletion, clear-all
  history that keeps memories, a visible Ollama wait timer with a configurable
  long reply limit and keep-alive, and a Save memory action for selected text.
- Ollama resilience: two cancel-aware delayed retries when a stream cannot
  start, a Retry action that resends the last prompt without duplicating it,
  partial-reply preservation on mid-stream failure, and a background startup
  preload of the chat model. The current message is sent as a real final user
  turn, and an empty model reply is retried once with a trimmed context.
- Automatic factual research and deeper reasoning: detection of questions about
  real people, games, films, products, places, events, and news; a quiet
  DuckDuckGo check injected as untrusted, source-linked reference data with a
  10-minute cache; and optional step-by-step thinking (`ollama.deep_reasoning`,
  on by default) for researched answers. Disambiguation, source comparison,
  synthesis, and honest uncertainty are part of the core prompt.
- Prompt capabilities now come from the real tool registry, so the model cannot
  claim tools that do not exist (no camera, no continuous listening).
- Local vision and attachments: one-shot screenshots and attached images join
  the message as chips with editable prompts; PDF, DOCX, XLSX, and text files
  are read into bounded, clearly untrusted context; a text-only vision model is
  replaced with `qwen2.5vl:3b`, and OCR remains a fallback.
- Rich non-text answers: the chat transcript moved to a bundled QtWebEngine
  view rendering Markdown tables, KaTeX formulas, and Mermaid schemas, mind
  maps, and diagrams offline, with script-locked HTML and a classic fallback.
- Local image generation through an A1111-compatible server, permission-gated,
  with generated files saved under `%USERPROFILE%\.himari\generated`, bundled
  `sd-server` assets unpacked on first use, and Ollama VRAM released before
  rendering.
- Settings and Diagnostics cover the vision model, image server, and rich-chat
  assets; the documented deployment profile is about 10.9 GB decimal with
  `qwen3:8b`, `qwen2.5vl:3b`, and the packaged app carrying `sd-server` and a
  Q8 SD 1.5 checkpoint.
- The release script produces a single-file `release\Himari.exe` carrying the
  staged local speech assets, the offline chat-rendering assets, and the local
  image engine.
- Additive SQLite migration for memory categories/projects/normalized text and
  backward-compatible explicit-column inserts.
- Full suite: 426 passed, 1 skipped (headless-browser practical test skipped on
  a machine without the required browser channel).

## Remaining milestones and limitations

- Embeddings/semantic memory are not installed; retrieval remains lexical.
- Browser automation drives installed browsers only and does not manage logins,
  payments, CAPTCHA, downloads, or tabs in the user's own Chrome. Its tab tools
  are limited to Himari's separate browser window.
- Agent verification checks tool observations and empty answers; it cannot
  semantically prove every natural-language claim from a local model.
- A tool that ignores its timeout runs in a worker thread that cannot be killed;
  the agent reports the timeout and never retries automatically.
- Vision analysis of screenshots remains optional and user-requested; screen
  capture is one-shot only.
- Windows hardware paths (microphone, media sessions, OCR, tray, packaged
  executable) still need validation on each target machine with its devices and
  models present.

