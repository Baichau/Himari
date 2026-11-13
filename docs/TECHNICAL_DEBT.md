# Himari 4 — Technical Debt Register

Baseline recorded on 2026-11-12 from the current working tree:

- `python -m compileall -q himari` — OK
- `python -m pip check` — no broken requirements
- `python -m pytest -q` — **623 passed, 1 skipped** (2026-11-12, after removing image generation,
  adding gated screen control, action-aware deep reasoning, single-page browser behavior, and the
  UI polish/custom-shortcut/capture-region stage)
- No in-tree integration tests run against live Ollama/Playwright by default; tests mock both.

Severity: **S1** can hang, lose data, or take an unsafe action · **S2** wrong/unsafe behaviour in
common flows · **S3** quality, performance, or maintainability.

## S1 — correctness and safety

### 1. Chat tool calls bypass argument validation — resolved
`llm.py` now validates every tool call against the tool schema (`himari/tool_schema.py`) before
authorization or execution; malformed arguments become an “Invalid arguments” observation the model
can correct. Tests: `tests/test_llm.py`, `tests/test_tool_schema.py`.

### 2. Confirmation can block forever — resolved
Both confirmation paths use `security.wait_for_decision()`: it waits at most 120 s and treats a
timeout as denial. Outstanding decisions register in `security.confirmation`; Stop, cancel-agent,
and window close call `release_pending_confirmations`, which denies every waiter and rejects an open
dialog, so shutdown never leaves a tool waiting. The daemon worker in `tool_exec` also stops a
timed-out tool from keeping the interpreter alive at exit.

### 3. Cancel cannot interrupt the model or a running tool
`llm.py:196-204` checks cancellation only per streamed chunk. During model load/first token the UI shows
“Stop” but nothing happens (`llm.py:197`). Tool handlers now run through the shared `tool_exec` helper
on a daemon worker with a per-tool timeout, so the caller returns and the process can exit, but a
handler already running cannot be killed and its side effects may continue after a timeout.
**Fix direction:** cooperative cancel tokens for long tools; document the limitation honestly in the UI.

### 4. Security duplication can drift
Two stacks exist: the UI `SecurityLayer` (`ui.py:79`) and the agent’s own layer
(`orchestrator.py:37`). `SecurityLayer.wrap_tools()` sets `confirm = False` and authorizes only the
kwargs it receives (`security/__init__.py:53-73`). The no-security LLM branch logs raw arguments, while
the audited path redacts (`llm.py:279-280` vs `audit.py:12-32`). A new tool must be added to
`tools.TOOLS` **and** `security/policies.py`, or it is silently denied/unaudited.
**Fix direction:** one execution service for chat and agent; fail-closed registration.

### 5. Research is outside the security/audit layer
The pre-model research call (`ui.py:1308-1310`) runs before the LLM and is not audited, unlike the
`research_web` tool. It respects `allow_web_research` but leaves no record.
**Fix direction:** route through the tool/audit layer or add an explicit audit event.

## S2 — common-flow correctness

### 6. Agent registry and policies are out of sync — mostly resolved
The safe read-only discovery tools (`installed_apps`, `list_windows`, `find_app`) and
`open_project` are now registered with real handlers. `capture_screen` and the `memory_*` policy
entries still have no `tools.TOOLS` registration, so the agent cannot call them; their UI paths are
separate. `development/` is reachable through `open_project`/test tools.
**Fix direction:** register or remove the remaining policy-only entries.

### 7. Completion does not require verification — resolved (honest reporting)
`AgentState.verified` is now included in every status event and the final state. A completed task with
denied/invalid/failed steps is labeled “completed (some steps unverified)” in the agent pane and a
warning is appended. `COMPLETED` is retained for tasks that produced a genuine final answer; the status
is not used as a claim that every step succeeded.

### 8. Success classification is prefix-based — resolved (shared classifier)
`himari/tool_results.py` now classifies results for the chat path, the agent, the security audit
(`{"ok": …, "error": …}` on every recorded result), and the transcript’s tool cards. Prefixes
include the forms the tools actually emit (`Failed…`, `Could not…`, `Unable to…`, `Cannot …`) plus
denied/invalid/timeout forms. Handlers still return plain strings rather than one `ToolResult`
envelope, so classification remains heuristic; a structured envelope is future work.

### 9. Empty-reply retry discards tool context — resolved
`_short_retry_messages` keeps the system rules, the current request, and the assistant/tool messages
that followed it (bounded to 12 messages, tool outputs capped at 1,200 characters). A retry after
tool work now still sees the observations.

### 10. Settings apply only at exit — resolved
Settings now save through the validated `control/settings.py` service. Safe widget values persist
after a 600 ms debounce through `_settings_updates(text_fields=False)`; URLs, model ids, embedding
model and wake word commit on `editingFinished`; shortcuts commit as soon as they are recorded and
rebind the hotkeys without a restart. Autosave failures log a warning and show one status
message; the close-time “Settings not saved” dialog remains. `allow_run_command` is still forced off
on every save. A single-instance guard prevents two windows from overwriting each other.

### 11. Agent timeout conflicts with real tools — resolved
Tool entries may declare `timeout_seconds`; the shared `tool_exec` helper enforces it for both chat
and agent (default 30 s, `research_web`/`browser_*` 90 s, screen-control tools 25 s).

### 12. Duplicate app-close implementations
`windows/launch.py:81-126` and `tools.py:240-285` both match windows and close them, with different
matching rules and return types. Only the former has the browser-window guard.
**Fix direction:** keep `windows.launch.close_app`, delete the tool-local copy.

## S3 — quality, performance, maintainability

### 13. `ui.py` is still a large window class
Chat, sessions, attachments, voice, tray, hotkeys, agent pane, DB access and rendering are one
class (2,161 lines; the Settings tab builder now lives in `ui_settings.py`, and motion helpers,
key capture and region picking are separate modules). One `busy` flag couples chat and agent.
**Fix direction:** extract a ConversationController and a SettingsController; keep Qt widgets thin.

### 14. Blocking work on the Qt thread
PortAudio enumeration and voice globbing (`ui.py:367-378`), mic start (`1463`), wake-word model load
(`1492`), memory queries on every keystroke (`296,1701-1708`), and SQLite session reads in slots.
Transcript updates now render only the streaming last card instead of rebuilding the full HTML on
every token, and safe settings save on a 600 ms debounce instead of only at close.
**Fix direction:** debounce input, move DB/model work to workers, keep shrinking the render payload.

### 15. Research quality — resolved (stage 3)
The research tool now runs up to two intent-aware queries, extracts readable text (with boilerplate
removal and duplicate-line collapse) from up to three pages on distinct domains, extracts publication
dates, and returns numbered citation blocks with `Source:` URLs plus an untrusted-data warning. It
refuses non-public URLs and re-checks redirects. Page reads still use static HTML: JavaScript-rendered
pages fall back to search snippets, and there is no research progress/cancel stream yet.

### 16. Memory
Retrieval is keyword-based by default with optional local Ollama embeddings
(`memory.embedding_model`); semantic blending is covered by fake-client tests but was not run
against a live embedding model in this environment. Contradiction checks are a conservative lexical
heuristic (`memory/conflicts.py`): shared tokens plus opposite terms or reversed polarity, surfaced
on demand from the Memory tab. It misses paraphrased conflicts, and it never changes memories.
`memory/extraction.py` is used only by tests; summary regeneration runs inside the UI process and
shares Ollama with chat. Summaries are pruned to the newest 10 per session, and a new summary whose
Unicode-aware token overlap with the newest one is at least 0.6 now updates that row with
sentence-level deduplication instead of adding a near-copy; distinct-topic summaries stay separate.
**Fix direction:** optional local embeddings, semantic contradiction checks.

### 17. Image generation — removed (2026-11-12)
The image-generation feature was deleted end-to-end at the user's request: `imagegen.py`,
`imagegen_backends.py`, `imagegen_payload.py`, the embed script, the Images tab, Settings fields, the
`generate_image` tool, `IMAGE_PATH:` transport, local model assets, tests, and docs. Himari has no
drawing, painting, or image-editing capability. Restoring it would require a new approved stage; the
old code is available in git history only.

### 18. Perception and desktop control
Screen capture honors `screen.monitor` — primary, all screens, active window (with its own opt-in
permission), or a saved `screen.region` — and the region picker maps drag coordinates to physical
pixels so display scaling cannot shift a saved box. The picker only supports the primary monitor;
region selection on secondary monitors is not implemented. Focus and app launches are verified
against the foreground/new window.
A UI Automation adapter now exists in `windows/uia.py` with deliberately narrow guarantees: it reads
a window's real control tree, matches exact then substring names, and refuses ambiguity. It cannot
verify that the app reacted to a click, cannot drive elevated windows that Windows protects, and
browsers expose only limited accessibility metadata. `perception.scene` is still dead code.
**Fix direction:** optional post-action verification, multi-monitor region picking, and scene cleanup.

### 19. Voice
Wake word is full Whisper transcription on 0.25 s chunks (high CPU, weak accuracy). Mic and wake
monitor open separate streams on the same device. The microphone sensitivity slider is wired: the
value is stored as `voice.sensitivity` and used as the energy threshold for voice activity. Starting
push-to-talk or a wake-word command now stops speech before the microphone opens, so Himari no longer
transcribes its own TTS. Safe voice settings (volume, sensitivity, mic device, language, TTS voice)
autosave; the wake word and push-to-talk key persist immediately.
**Fix direction:** dedicated wake-word engine or VAD-gated push-to-talk.

### 20. Rendering — resolved
The embedded chat renders incrementally (only the streaming last card), highlights fenced code in
eleven languages with a built-in tokenizer, adds copy buttons for code and whole messages through a
Qt prompt bridge, and keeps Mermaid/KaTeX state across streaming updates. The classic view remains a
plain-text fallback without tables/math/diagrams by design.

### 21. Documentation drift and dead code — partly resolved
`control/settings.py` is now the single settings write path, and `dashboard`/`diagnostics` are wired.
README and the docs set were refreshed for the current feature set, and the redundant
`AVATAR_GUIDE.md` was removed in favor of the README avatar section. Remaining drift is prompt logic
split between `persona.py` and `personality/`, plus the unreferenced `perception.scene`.
**Fix direction:** consolidate prompt assembly; delete or document the dead scene helper.

### 22. Observability — resolved
`himari/crash.py` installs a `sys.excepthook`, worker-thread hook, and Qt message handler that write
to the rotating log. The in-app log viewer (`himari/log_viewer.py`) shows a bounded 200 KB tail with
a minimum-level filter, search, copy, refresh, and open-folder actions.

### 23. Test isolation
Tests mostly mock services; one test previously depended on the live user config
(`test_browser_open_reports_permission_denial`) and failed when the running app enabled browser
automation. Fixed by forcing the permission in the test.
**Fix direction:** never read `%USERPROFILE%\.himari` in unit tests; always use temp `HIMARI_HOME`.

### 24. ChatGPT-level scope items that remain open
- **Spotify:** `play_music` opens Spotify search and `media_control` sends OS media keys; Himari
  cannot choose a track, start a specific song, or confirm playback without a Spotify Web API
  client (free but requires a user-created app and OAuth) or fragile UI Automation of the desktop
  client. Do not claim track control until one of those is implemented and verified live.
- **Feedback learning:** explicit “remember that …” requests and the memory approval list are the
  only learning paths. Free-form corrections are not distilled into memories automatically.
- **Whole conversation history:** context is bounded (`num_ctx` 8192, a 60-message/9,000-character
  history window plus rolling summaries). Older turns survive only through summaries and memories.
- **Browser profile:** automation uses an isolated profile, so the user's Chrome logins are not
  available. The five-tab cap is per Himari window, and extra tabs require explicit `browser_tabs`
  cleanup rather than silent closing.
**Fix direction:** choose an explicit design per item and verify live; keep claims limited to what
is implemented.

### 25. First reply after launch is slower
Ollama loads the chat model into memory on first use, and an 8B model can take many seconds to
wake up on this hardware. Himari preloads the model 2.5 s after startup when `ollama.preload_model`
is enabled, keeps it alive for 30 minutes, and the waiting indicator now says "waking the local
model" with a reminder that the first reply can take longer. This is expected behavior, not a
regression; it is not hidden behind a fake instant reply.
**Fix direction:** none required; measure before changing warm-up timing.

## Interfaces that must remain compatible

- `tools.TOOLS` entry shape (`name`, `fn`, `spec`, optional `confirm`/`silent`/`confirm_message`/
  `timeout_seconds`).
- `LLM.stream_chat(messages, on_token, on_tool, confirm, cancel_event, on_status, think)`.
- `SecurityLayer.authorize/record_result`, optional `on_confirmation` hook, and `security.policies` maps.
- `Executor.execute(tool, arguments, token=None, on_start=None)`.
- `db` schema and existing rows (additive migrations only).
- Qt signals: `token`, `status`, `done`, `tool`, `failed`, `cancelled`, `*_ready`.
- Config keys are additive; defaults come from `config.example.json`.
