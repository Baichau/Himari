# Changelog

## Himari 4.0 development

- Desktop polish and personal shortcuts (2026-11-12):
  - Added `himari/ui_effects.py`: window fade, tab-page fade, message pulse and animated
    collapsible Settings cards. Chat messages now fade/slide in with a stagger, the welcome screen
    animates and offers clickable prompt chips, scrolling is smooth for settled updates, and the
    reduced-motion preference is honored.
  - Rebuilt Settings as collapsible sections in `himari/ui_settings.py` (voice, screen and privacy
    open by default; permissions, advanced and window/data folded). Removed the non-functional
    run-command toggle and clarified labels that were misleading.
  - New `KeyCaptureButton` (`himari/ui_widgets.py`): push-to-talk and screen-capture shortcuts are
    recorded by pressing them, validated, saved immediately, and rebound without restarting.
    Duplicate shortcuts are refused.
  - New `himari/region_select.py`: drag a custom screen-capture region once; it is stored as
    `screen.region`, validated by the Settings schema, and honored by the capture key, the Screen
    button and `capture_screen()`.
  - The waiting indicator now explains that the first reply after launch can be slower while the
    local model wakes, and preload reports warming/ready states.
  - Deleted `AVATAR_GUIDE.md`; its sprite guidance moved into the README avatar section.
  - Offscreen window smoke test passed; full suite: **623 passed, 1 skipped**.

- One request, one page (2026-11-12):
  - `browser_open_result` now reuses the current tab by default, replacing the search page instead
    of leaving a results tab plus a destination tab; `new_tab=true` is opt-in. Repeated searches
    replace an existing search tab, and Himari's browser refuses to exceed five tabs.
  - New silent `find_video` tool reads YouTube results in the background and returns titles,
    channels, durations, and watch URLs; it opens no browser. A live check resolved a fireplace
    request to three real watch URLs, and a stubbed model run then opened exactly one page.
  - The persona now opens a browser only when the user asks, resolves finding tasks through
    `research_web`/`find_video`, and forbids opening several candidates for one request.
  - `list_windows` accepts a `name_filter` (and the `window` alias the model had tried), fixing
    failed window-inspection calls. Full suite: **606 passed, 1 skipped**. Rebuilt the onefile at
    610 MB; the packaged smoke test passed.

- Screen control replaces image generation (2026-11-12):
  - Removed image generation end-to-end: the A1111/ComfyUI/sd-server facade, the Images tab,
    Settings fields, the `generate_image` tool, `IMAGE_PATH:` transport, the embedded payload,
    local model assets, and the associated tests and documentation. Himari can no longer draw,
    paint, or edit pictures, and the release carries no image-model weights.
  - Added opt-in semantic screen control through Windows UI Automation (`pywinauto`):
    `list_controls`, `click_control`, `set_control_text`, `type_text`, `press_keys`, `click_at`,
    and `scroll_screen`. Control names come from the real window tree; duplicate names are
    reported instead of guessed.
  - Added the `allow_screen_control` permission (off by default) in Settings. Every input action
    is HIGH risk and confirmed; `press_keys` always re-asks even after a session approval; the
    Windows key and password fields are refused. Low-level input is bounded to one action per
    call and uses Unicode key events.
  - Diagnostics now report UI Automation availability instead of an image server. Build,
    dependencies, persona rules, README, SECURITY, and architecture docs updated.
    Full suite: **586 passed, 1 skipped**.
  - Removed the local image assets under `%USERPROFILE%\.himari\imagegen` (5.9 GB) and rebuilt
    the onefile at 610 MB (down from 2.52 GB); the packaged smoke test passed. The screen-control
    layer was also exercised live against Windows Calculator: semantic clicks computed 1 + 2 = 3,
    and `type_text`/`press_keys` computed 12 + 7 = 19.
  - Deep-control pass: `open_app` now focuses an existing window instead of opening a duplicate,
    prefers process matches over title lookalikes, and accepts a new process as launch evidence
    within an 8 s window. Screen-control tools accept `window="active"` for duplicate titles.
    Deep reasoning now covers app and screen actions when enabled, and the persona playbook
    separates a launch result from a denied control step. Full suite: **591 passed, 1 skipped**.

- Local-intelligence and reliability upgrade (2026-11-12):
  - Chat correctness: `num_ctx` and bounded prompt blocks, rolling summaries, per-request
    thinking decisions, a Mermaid directive for drawn schemas, and a prompt that plans,
    resolves pronouns, adapts after failure, and claims only tool-confirmed actions.
  - Tool execution: Ollama capability detection, JSON-schema validation before any handler,
    one bounded daemon-backed invocation for chat and agent, a shared result classifier in the
    audit trail and transcript, honest “completed (some steps unverified)” agent labels, and
    confirmation waits that Stop/cancel/close release instead of hanging.
  - Empty-reply retries keep the current request, assistant/tool observations (bounded), and
    system rules instead of dropping the conversation after the user turn.
  - Research: two intent-aware queries, readable text from up to three pages on distinct
    domains, publication dates, numbered sources, optional self-hosted SearXNG, progress
    events, and cancellation.
  - Images: one provider interface for A1111/sd-server and ComfyUI, txt2img, img2img,
    inpainting, upscaling, presets, seeds/batch, a 200-entry history, and an Images tab that
    restores the last generation for follow-up edits.
  - Screen and apps: configured-monitor and active-window capture, verified window focus and
    launches, registered discovery tools, and find-or-create VS Code workspaces.
  - Memory and voice: scored retrieval with “why retrieved” metadata, near-duplicate memory
    merging, optional local-embedding semantic retrieval with cached vectors, summary pruning plus
    overlapping-summary merging, report-only contradiction checks,
    safe settings autosave, VAD-gated wake-word phrase capture, selectable microphone and
    speaker, and push-to-talk/wake-word speech interruption.
  - UI and operations: incremental transcript rendering, local syntax highlighting with copy
    buttons, a single-instance guard, crash/Qt logging, an in-app log viewer, and a README/docs
    refresh.
  - Images (checkpoints): deterministic model choice through `imagegen.managed_model`. The managed
    server launches the configured `.gguf` when present and logs a warning before falling back to
    an installed checkpoint, so a larger locally installed model is not silently ignored. The
    packaged payload still carries the small SD 1.5 checkpoint as the fallback even when a larger
    model is installed. Full suite: **631 passed, 1 skipped**.

- Wired browser automation into the chat tools. Himari can now search and open
  pages in its own visible Chrome window, open the first or Nth search result,
  read the active page, and list, focus, close, or close-other tabs in that
  window. Tabs survive between messages because the Playwright session lives on
  a dedicated thread. The window uses an isolated profile without saved logins,
  and these tools never touch the user's everyday Chrome tabs. The new
  `open_first_result` tool resolves a search and opens the chosen result in the
  user's default browser instead of another results page. Persona and tool text
  now require reporting only confirmed outcomes, so Himari no longer claims a
  site is open when only a search page opened, and no longer implies that
  `play_music` starts a requested Spotify track.
- Added tests for the managed browser session thread, tab actions, numbered
  result opening, permission mapping, and a practical headless Chrome tab test.
  Full suite: 426 passed, 1 skipped.
- Added local image understanding. Screenshots and attached images are sent to
  a local Ollama vision-language model (`qwen2.5vl:3b` by default) only when
  the user presses Send. The model identifies the app and layout, transcribes
  visible text, reads values exactly, and answers the user's question about the
  image. A configured text-only model is detected and replaced, and Windows OCR
  remains a fallback when the vision model is missing or times out.
- Reworked screen capture into an attachment flow: one-shot capture adds the
  screenshot to the composer as a chip with a thumbnail, pre-fills a sensible
  question, and lets the user edit it before sending. No automatic screenshot
  is saved, and the previous auto-send/OCR-only path is gone.
- Added attachments for images, PDF, Word, Excel, CSV, and text/code files via
  the Attach button or drag-and-drop. Reading is bounded (20 MB per file, 8
  files, capped text, PDF pages, sheet rows/columns) and happens in memory for
  that message only. Attachments are labelled as untrusted reference data in
  the prompt.
- Added rich chat rendering in an embedded QtWebEngine view using fully offline
  KaTeX and Mermaid assets: Markdown bold/lists/tables/code, LaTeX formulas,
  and Mermaid flowcharts, mind maps, sequence, class, and state diagrams. The
  page runs under a strict Content-Security-Policy, blocks raw model HTML and
  scripts, reduces model images to alt text, and opens links in the default
  browser. Attachment chips, generated-image cards, tool cards, and a streaming
  cursor are rendered natively; a classic plain-text view remains selectable in
  Settings and is used automatically if QtWebEngine cannot start.
- Added local Stable Diffusion image generation through the A1111-compatible
  `/sdapi/v1/txt2img` API (`stable-diffusion.cpp` `sd-server` or
  Automatic1111/Forge). Images are generated without network access, shown in
  the chat, and saved under `%USERPROFILE%\.himari\generated`. The
  `generate_image` tool is permission-gated by `allow_image_generation`, keeps
  prompts and dimensions bounded, and reports actionable help when no server is
  running.
- Added on-demand startup of `sd-server`. When image generation is requested
  and no server answers, Himari launches the fixed executable at
  `%USERPROFILE%\.himari\imagegen\server\sd-server.exe` with the first GGUF
  checkpoint in `%USERPROFILE%\.himari\imagegen\models`, waits for the API to
  come up, and then generates. The launch command is built entirely from
  managed paths, never from model output. Auto-start can be disabled with
  `imagegen.auto_start` and its output is logged to
  `%USERPROFILE%\.himari\logs\sd-server.log`. The server runs with VAE tiling
  so decoding a 768 px image cannot exhaust VRAM next to Ollama.
- Bundled the local image engine inside the portable executable. The build
  appends `sd-server`, its DLLs, and the SD 1.5 Q8 checkpoint to
  `Himari.exe`; on the first image request the app unpacks them once into
  `%USERPROFILE%\.himari\imagegen` and starts them. Launching Himari stays
  fast because the payload sits outside the PyInstaller archive. The build
  script verifies the embedded ZIP and CRC before the packaged smoke test, and
  `-AllowMissingImageAssets` still supports chat-only builds.
- Image generation now releases Ollama's GPU memory first. Before rendering,
  Himari asks Ollama to unload the configured chat and vision models, which
  removes the VRAM contention that previously pushed a 768 px request from
  seconds to over five minutes and made VAE decoding fail. The models reload
  on the next chat message; this can be disabled with
  `imagegen.free_ollama_vram`. The `generate_image` tool also accepts a
  `style` field and ignores unknown arguments instead of failing with a type
  error, and the persona and tool description now state plainly that picture
  requests must call the tool rather than declining.
- Added Settings controls for the vision model, image-server URL, vision and
  image-generation permissions, and rich versus classic chat rendering, plus
  Diagnostics checks for the vision model, image server, and bundled rich-chat
  assets. Documented the deployment profile (Q8 SD 1.5 checkpoint, `qwen3:8b`,
  `qwen2.5vl:3b`).
- Added tests for attachments, vision prompt/model selection, image generation,
  managed server startup and permissions, bundled-payload extraction, Ollama
  VRAM release, rich-chat HTML/math/diagram escaping, diagnostics, and the
  screenshot attachment flow. Full suite: 397 passed, 1 skipped.
- Added automatic factual web research: questions about real people, games,
  films, products, places, events, or news are detected without an explicit
  "search" command, checked against DuckDuckGo before the model answers, and
  injected as clearly untrusted, source-linked reference data. Results are
  cached for 10 minutes; failures are not cached and fall back to a clear
  "could not verify" answer instead of a guess.
- Added deep reasoning for researched answers (`ollama.deep_reasoning`, on by
  default, with a Settings checkbox). The local model now thinks step by step
  over the fetched sources before writing, which takes roughly 5–10 extra
  seconds and fixes confidently wrong answers such as misidentifying a Dota
  hero. Greetings, personal questions, and local actions skip both research and
  deep thinking so they stay fast. If the selected model cannot think, Himari
  continues without it instead of failing the reply.
- Strengthened the reasoning policy: answer the actual question first,
  disambiguate names from context (game, film, place) and say which meaning is
  meant, compare sources, synthesize instead of copying snippets, cite a source
  when a claim depends on it, and state uncertainty when verification failed.
- Added patient Ollama handling: a separate long reply limit
  (`ollama.stream_timeout_seconds`, 900 s by default and adjustable in
  Settings), a 30-minute `keep_alive`, and a visible elapsed-seconds status
  while the local model loads or writes. The Stop button still cancels
  immediately.
- Added automatic recovery for slow or briefly unresponsive Ollama: two
  delayed retries when a stream cannot start, a "Retry" button that resends
  the last prompt without duplicating it, and preservation of any partial
  reply when the model stops mid-answer. Timeout, missing-model, and
  connection failures now explain the cause and the next step.
- Fixed instant "did not return a reply" failures in long chats: the current
  message is now sent as a real final user turn instead of being embedded only
  in the system prompt, and an empty model reply is retried once with a short
  context before Himari reports an error.
- Added an optional startup preload (`ollama.preload_model`, on by default)
  that loads the chat model in the background so the first reply is faster
  and later replies stay warm while the window is open.
- Added chat management: delete the current chat from the toolbar or
  right-click any chat in the sidebar, and clear all chat history from
  Settings. Confirmed deletion removes messages and summaries but keeps saved
  memories, settings, activity records, and other chats.
- Added **Save memory** to the chat toolbar, which pre-fills selected
  transcript text and saves it as an approved local memory. Sensitive phrases
  and contact details are refused, and the Memory tab shows a pending-suggestion
  count badge.
- Expanded explicit memory triggers beyond "remember that" to "remember:",
  "keep in mind that", "don't forget that", "note that", and "запомни, что".
- Redesigned the chat experience: recent-chat sidebar with restored local
  history, rich Markdown rendering (code, lists, links, inline code), themed
  user/assistant/system/error bubbles, a live streaming cursor, per-message
  timestamps, and a native Tools toggle for tool activity.
- Added Stop control for in-flight replies. Cancellation keeps any partial
  reply, stops queued tokens, and records the session as usual.
- Added a persistent "Voice on/off" switch (`voice.speak_replies`) so replies
  can be silent without disabling transcription or manual speech controls.
- Added warm/dark theme styling and a larger header avatar; avatar expressions
  now include happy, confused, and sad feedback on success, cancellation, and
  errors, and clicking the main avatar toggles the floating companion.
- Grounded the prompt in the real tool registry (`AVAILABLE TOOLS`) and removed
  invented capabilities such as a camera or continuous listening.
- Added LLM cancellation support (`LLMCancelled` with partial output) and
  session/message database queries used by the sidebar and transcript.
- Added a bounded agent engine (`himari/agent`) that reuses existing tools,
  routes every call through the centralized security layer, verifies each
  observation, supports cancellation, and never auto-retries denied or failed
  dangerous actions.
- Added `himari/security`: risk levels, default-deny unknown tools, Settings
  permission gating, mandatory confirmation for consequential actions, path and
  command validation, and audit logging with secret redaction.
- Added `himari/windows` for Windows-native app/process/window discovery and
  graceful close requests without forced termination.
- Added `himari/perception` for permission-gated one-shot screen capture,
  Windows OCR, active-window context, and a structured scene.
- Added `himari/browser` Playwright automation with strict URL validation,
  ambiguity rejection, payment/CAPTCHA/auth refusal, and submit confirmation.
- Added `himari/integrations` for Chrome, Spotify, Steam, VS Code, and Discord
  capability reporting without pretending unsupported actions work.
- Added `himari/development` for workspace-restricted file reading, code search,
  diff-before-apply editing, and allowlisted test commands.
- Added `himari/memory` with categories, dedupe, bounded relevant retrieval,
  summarization, and approval workflow on the existing SQLite database.
- Added `himari/personality` with a configurable warm persona, technical mode,
  and validated avatar expressions that never override security rules.
- Added Dashboard, Diagnostics, and agent task controls to the existing PySide6
  window; long-running checks run in worker threads.
- Added `memory_enabled`, `allow_browser_automation`, `development.workspaces`,
  and `personality` settings. Existing configuration is preserved through
  default-value merging; database migrations are additive.
- Normalized bracketed IPv6 `NO_PROXY` entries (for example `[::1]`) at startup
  so Ollama client initialization works with common Windows proxy settings.

## Himari 3.0 development

- Repaired UI integration and retained the existing Qwen/Ollama, voice, and
  local-storage architecture.
- Added settings gates for one-time screen capture and Windows media controls.
- Added bounded Windows media-key actions that report the active session and
  playback state cannot be confirmed.
- Added a sprite-based avatar renderer, optional draggable floating window,
  asset guide, and an honest placeholder when no artwork is installed.
- Added Unicode-aware lexical memory retrieval, explicit “remember that”
  suggestions with approval/rejection, and saved-memory search.
- Kept arbitrary shell execution disabled and graceful application close
  requests confirmation-gated.
