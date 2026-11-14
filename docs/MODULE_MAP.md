# Himari 4 — Module Map

Generated from the current source tree (`himari/`, 125 Python modules, ~27.6k lines).
“Entry points” are the functions/classes other modules actually call.

## Application shell

| Module | Responsibility | Key entry points | Notes / dependencies |
|---|---|---|---|
| `main.py` | Process entry point | module execution | delegates to `bootstrap.main` |
| `bootstrap.py` | Proxy sanitising, logging, packaged-asset validation | `main()` | imports `startup`, `ui` |
| `single_instance.py` | One running instance per user; raises the existing window | `SingleInstance.acquire`, `activated` | `QLocalServer`/`QLocalSocket`, per-user hashed name |
| `crash.py` | Unhandled-exception, worker-thread, and Qt message logging; one-time error dialog | `install`, `_qt_handler` | installed by `ui.run` |
| `startup.py` | Self-test / smoke-test helpers | `run_self_test_checks` | used by packaged smoke test |
| `ui.py` (2,161 L) | `QMainWindow`: chat shell, sessions, attachments, voice controls, agent pane, tray, hotkeys, settings persistence | `UI`, `run()` | imports almost every package; Settings widgets are built by `ui_settings.py`; autosave through `control/settings.py` |
| `ui_effects.py` | Reusable Qt motion helpers | `fade_in`, `pulse`, `fade_window`, `AnimatedTabWidget`, `CollapsibleSection` | skips fades on `QWebEngineView` pages |
| `ui_settings.py` | Settings tab builder with collapsible sections | `build_settings_page` | sets the attribute names `ui.py` persists |
| `ui_widgets.py` | Shortcut recorder and chord conversion | `KeyCaptureButton`, `chord_from_key`, `validate_chord` | feeds `keyboard.add_hotkey` |
| `region_select.py` | Custom screen-capture region picker | `RegionSelector`, `select_region`, `map_selection` | primary monitor; maps to physical pixels |
| `theme.py` | Palettes and Qt stylesheet | `palette`, `stylesheet` | UI only |
| `avatar.py` | Avatar painting, expressions, floating window | `AvatarWidget`, `FloatingAvatarWindow` | Qt |
| `config.py` | Config load/save with defaults merge | `load`, `save`, `get`, `set_value` | every subsystem; `config.example.json` is authoritative defaults |
| `paths.py` | User-data and resource directories | `user_data_dir`, `resource_dir` | respects `HIMARI_HOME` |
| `logging_setup.py` | Rotating file log (2 MB × 3) | `configure_logging`, `log_file_path` | no console/Qt handler |
| `log_viewer.py` | In-app log snapshot dialog with level/text filters | `LogViewerDialog`, `read_log_tail`, `filter_log` | reads a bounded tail; no live tailing |

## Conversation

| Module | Responsibility | Key entry points | Notes |
|---|---|---|---|
| `llm.py` (372 L) | Ollama client, streaming, tool loop, retries, thinking toggle | `LLM.stream_chat`, `.vision`, `.preload`, `.model_status` | validates tool args; bounded per-tool calls via `tool_exec` |
| `tool_exec.py` (49 L) | Shared bounded tool invocation for chat and agent | `call`, `timeout_for`, `ToolTimeoutError` | per-tool `timeout_seconds`, 30 s default, daemon worker thread |
| `tool_results.py` | Shared classification of raw tool return values | `classify_result` | used by chat logging, security audit, agent steps, and tool cards |
| `persona.py` (307 L) | Legacy system prompt builder + per-request directives | `build`, `diagram_directive`, `should_think`, `available_tools_block` | primary prompt used by UI |
| `personality/` | Persona object, modes, expression mapping, prompt fragments | `load_persona`, `build_messages`, `build_system_prompt` | second prompt path; used for extra instructions |
| `chat_web.py` (789 L) | Markdown/math/Mermaid → HTML for QtWebEngine | `markdown_to_html`, `build_render_payload` | bundled JS/CSS, strict CSP; incremental updates, highlighting, Qt copy bridge |
| `chat_format.py` | Plain-text fallback formatting | `format_messages` | no tables/math |
| `attachments.py` (411 L) | File/image loading, extraction, downscaling, limits | `load_attachment`, `attachment_text_block`, `image_attachment` | PDF/DOCX/XLSX/text |
| `personality/state.py` | Expression state machine | `PersonalityState` | avatar only |

## Agent

| Module | Responsibility | Key entry points | Notes |
|---|---|---|---|
| `agent/orchestrator.py` | Plan → execute → observe loop, max 5 steps | `AgentOrchestrator.run/cancel` | used only by the agent pane, not normal chat |
| `agent/planner.py` | One LLM planning call returning JSON tool calls | `Planner.plan` | keeps only the first call; no retry; cancellation between steps only |
| `agent/executor.py` | Validate, authorize, execute with 30 s timeout, classify result | `Executor.execute` | timeout cannot kill a running handler |
| `agent/tool_registry.py` | Tool registry + JSON-schema argument validation | `ToolRegistry.validate_arguments` | fail-closed; used only by agent |
| `agent/state.py` | Enums/dataclasses for agent states and steps | `AgentState`, `StepStatus`, `CancellationToken`, `AgentCancelledError` | |

## Capabilities

| Module | Responsibility | Key entry points | Notes |
|---|---|---|---|
| `tools.py` | Core tool registry plus shared app/file/browser/research/media handlers | `TOOLS` (69 entries after `skills.skill_tools()` is merged), `research_web`, `open_app`, `list_controls_tool`, `click_control_tool` | risk/permissions external; duplicate close logic lives here too |
| `research.py` | Regex research router + DuckDuckGo query + cache | `should_research`, `research_for_prompt` | snippets only, single query |
| `browser/browser_manager.py` | Playwright launch with isolated context | `BrowserManager` | installed browsers only |
| `browser/session.py` | Dedicated thread + queue RPC, permission gate | `session.call`, `shutdown` | sync Playwright isolation |
| `browser/navigation.py` | URL validation and navigation | `normalize_url`, `navigate` | http/https only |
| `browser/tabs.py` | Tab list/focus/close/close-all, search URLs | `list_tabs`, `close_tab`, `open_page` | 20-tab cap |
| `browser/page_reader.py` | Text extraction, element locate/read | `read_page`, `locate`, `read_elements` | fixed JS, 8k char cap, index-based selectors |
| `browser/interactions.py` | Click/fill/submit with safety guards | `click`, `fill`, `submit` | refuses payment/CAPTCHA/password flows |
| `windows/apps.py` | Installed-app discovery and matching | `installed_apps`, `find_app` | Start Menu + registry + Get-StartApps, 60 s cache |
| `windows/launch.py` | Launch/close apps, browser-window guard | `launch_app`, `close_app` | `WM_CLOSE`, ambiguous-name refusal |
| `windows/enumeration.py` | Top-level window enumeration and verified focus | `list_windows`, `focus_window`, `request_window_close` | focus is verified against `GetForegroundWindow` |
| `windows/processes.py` | psutil process views | `running_processes` | |
| `windows/input.py` | Bounded SendInput keyboard/mouse injection | `type_text`, `press_keys`, `click_at`, `scroll_screen` | Windows-only; refuses the Windows key; DPI-aware physical pixels; one action per call |
| `windows/uia.py` | Semantic window/control access through pywinauto UI Automation | `find_window`, `list_controls`, `click_control`, `set_control_text` | lazy `pywinauto` import; exact-then-substring matching; duplicate names refused; password fields refused |
| `windows/errors.py` | App lookup exceptions | `AppNotFoundError`, `AmbiguousAppError` | |
| `perception/capture.py` | Monitor/region/active-window capture (mss) | `capture_screen`, `captured_screen` | honors `screen.monitor` including the saved `screen.region`; active-window needs `allow_active_window` |
| `perception/ocr.py` | WinRT OCR wrapper | `ocr_image` | OS language profile |
| `perception/scene.py` | Window list + active window “scene” | `build_scene`, `active_window_info` | exposed through the `screen_scene` tool |
| `screen.py` | Capture/OCR helpers, active-window rect | `capture`, `analyze`, `active_window_rect` | shared with perception |
| `vision.py` | Vision-model call with capability hints | `describe_images` | replaces text-only vision config |
| `integrations/base.py` | Integration contract | `Integration` | availability scans are expensive |
| `integrations/registry.py` | Import-time singleton registry | `get`, `all_integrations` | |
| `integrations/spotify.py` | Spotify open/status | methods | playback not implemented (honest refusal) |
| `integrations/steam.py` | Steam open/status | methods | imports private tool helpers |
| `integrations/vscode.py` | VS Code open/status | methods | |
| `integrations/chrome.py` | Chrome open/status | methods | |
| `integrations/discord.py` | Discord status | methods | sending refused |
| `development/workspace.py` | Approved dev workspaces and the last opened project | `discover_workspaces`, `workspace_for`, `set_active_project`, `active_project` | used by `development/launcher.py`, `open_project`, `read_file` |
| `development/launcher.py` | Find/create a project and open it in VS Code | `find_project`, `create_project`, `open_in_editor` | reachable through the `open_project` tool; workspace-scoped |
| `development/editor.py` | Apply code changes | `apply_change` | not exposed |
| `development/code_search.py` | Search within workspace | `search_code` | exposed through the `search_code` tool |
| `development/file_reader.py` | Read source files | `read_source` | not exposed |
| `development/test_runner.py` | Run project tests | `run_tests` | not exposed |

## Companion skills

Modular tools added on 2026-11-14. `skills/__init__.py` exposes `skill_tools()`, which
`tools.py` merges into `TOOLS` after the core list is built; duplicate names are dropped.

| Module | Responsibility | Key entry points | Notes |
|---|---|---|---|
| `skills/__init__.py` | Aggregates module `TOOLS` lists | `skill_tools` | imported at the end of `tools.py`; first definition wins |
| `skills/watch.py` | Opt-in bounded watch session, game detection, in-memory observations | `WatchSession`, `session`, `watch_start`, `watch_stop`, `watch_status`, `watch_observe`, `detect_game` | interval from Settings (default 20 s), 30 min cap, permission re-checked every tick, nothing persisted |
| `skills/coach.py` | Setup playbooks, topic aliases, secret masking, live verification | `setup_guide`, `setup_verify`, `playbook_status`, `inspect_settings`, `setup_remember` | reports whether a secret exists, never its value |
| `skills/doctor.py` | Read-only system/program diagnosis and event-log summarization | `inspect_system`, `diagnose_program`, `recent_system_events`, `recent_app_events` | redacts sensitive text; refuses service/registry/startup/security changes |
| `skills/pair.py` | Reads VS Code workspace state and open editors; diff-first edits; allowlisted tests | `open_editors`, `read_open_file`, `propose_change`, `apply_change`, `run_project_tests` | gated by `allow_vscode_state`; window-title fallback when state is unreadable |
| `skills/media.py` | Public YouTube caption fetch and timedtext parsing | `youtube_transcript`, `video_id`, `caption_url`, `parse_timedtext` | needs `allow_web_research`; bounded response, no download or playback |
| `skills/continuity.py` | Activity memory and combined project context | `remember_activity`, `project_context` | writes the `activity` category; context is assembled read-only |

## Memory and data

| Module | Responsibility | Key entry points | Notes |
|---|---|---|---|
| `db.py` (312 L) | SQLite schema/migrations, messages, sessions, memories, summaries, actions, cached memory vectors | `history`, `messages_detailed`, `add_memory`, `relevant_memories`, `save_summary` (merges overlapping summaries), `summary_for_session`, `log_action` | one global lock; schema created on demand |
| `memory/manager.py` | Category-aware memory CRUD, normalization, migration, fuzzy merge | `MemoryManager` | |
| `memory/models.py` | `Memory` dataclass (with retrieval score/reason), categories | `CATEGORIES` | |
| `memory/scoring.py` | Shared relevance/recency/importance scorer | `rank`, `score`, `is_near_duplicate` | used by `db.relevant_memories` and retrieval |
| `memory/conflicts.py` | Lexical contradiction heuristic over saved memories | `find_conflicts` | exposed via `MemoryManager.conflicts()`, report-only |
| `memory/retrieval.py` | Bounded hybrid retrieval with score/reason metadata | `retrieve` | shares `scoring.rank` |
| `memory/embeddings.py` | Optional local Ollama embeddings with cached vectors | `configured_model`, `semantic_scores` | off unless configured; keyword fallback |
| `memory/extraction.py` | “remember that …” extraction | `extract_candidate` | unused by live path |
| `memory/summarizer.py` | Local summary generation | `summarize_session`, `summarize_older` | keeps newest 10 summaries per session |

## Security

| Module | Responsibility | Key entry points | Notes |
|---|---|---|---|
| `security/__init__.py` | Central authorization + audit wrapper | `SecurityLayer.authorize`, `.record_result`, `.wrap_tools` | chat path uses this |
| `security/permissions.py` | Risk model, permission keys, session grants, `Decision` | `PermissionManager.authorize` | |
| `security/policies.py` | Tool → risk and tool → permission maps | `risk_for`, `permission_key_for`, `CONFIRMATION_TOOLS` | must be updated with every new tool |
| `security/confirmation.py` | Confirmation request, pending-decision registry, fail-closed waits | `new_decision`, `resolve_decision`, `release_pending_confirmations`, `require_confirmation`, `wait_for_decision` | 120 s bound; Stop/cancel/close release waiters |
| `security/validation.py` | Command/path/text validation | `validate_path`, `validate_command` | |
| `security/audit.py` | Redacted audit rows | `audit`, `redact_value` | writes to `db.actions` |

## Control center

| Module | Responsibility | Key entry points | Notes |
|---|---|---|---|
| `control/dashboard.py` | Snapshot of Ollama, voice, permissions, integrations, memory, audit | `snapshot` | runs expensive integration checks |
| `control/diagnostics.py` | Runtime/asset diagnostics | `run_diagnostics` | |
| `control/settings.py` | Validated settings service | `SettingsService` | **unused by UI today** |
| `control/activity_view.py` | Activity/audit rendering helper | `format_events` | |
| `control/memory_view.py` | Memory display helper | `rows` | |
| `control/permissions_view.py` | Permission descriptions | `describe`, `set_permission` | only reachable via dashboard |

## Dependency observations

- No import cycles were found at module import time. The heavy coupling is architectural, not cyclic:
  `ui.py` imports almost everything, and `tools.py` is imported by `research.py`, `persona.py` (lazily),
  the agent registry, integrations, and tests.
- Three parallel “capability→UI” paths exist: `tools.TOOLS` (which now includes the `skills/`
  package through `skill_tools()`), the agent registry, and `integrations/` + `development/`. The
  `open_project` tool reaches `development/launcher.py`, and `skills/pair.py` covers the
  read/diff/apply/test portion of `development/`; the integration classes are still not
  registered as tools.
- Dead or unreachable code today: `control/settings.py`, `memory/extraction.py`, and integration
  tools (no matching entries in `tools.TOOLS`). `development/launcher.py` backs `open_project`,
  `development/code_search.py` backs `search_code`, and `skills/pair.py` uses the same workspace
  rules for reading and editing. `perception/scene.build_scene` and the safe read-only environment
  helpers (`installed_apps`, `list_windows`, `running_processes`, `find_app`) are reachable through
  `tools.TOOLS` and the watch/doctor skills.
- Prompt logic is split between `persona.py` and `personality/`; only the former is used for the
  main system prompt.
