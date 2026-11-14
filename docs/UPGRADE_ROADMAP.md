# Himari 4 — Upgrade Roadmap

Status as of 2026-11-13. This file is the running record of completed and remaining work.
The staging order follows the upgrade brief, with one deliberate reordering: **context and reasoning
correctness first**, because every later feature depends on the model actually receiving the tools,
history, and instructions it is given.

## Stage 0 — Audit and baseline

- [x] Read the full source tree (65 modules, ~12.2k lines) and all tests
- [x] Build the application map — see [MODULE_MAP.md](MODULE_MAP.md)
- [x] Draw the architecture and flow diagrams — [ARCHITECTURE.md](ARCHITECTURE.md),
      [DATA_FLOW.md](DATA_FLOW.md), [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md)
- [x] Record concrete weaknesses — [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md)
- [x] Baseline: `compileall` OK, `pip check` OK, **439 passed / 1 skipped**
- [x] Fix test isolation so unit tests do not read the live user config

## Stage 1 — Conversation correctness (completed)

These came out of the audit and were implemented before feature work:

- [x] Send and respect `num_ctx` (default 8192) on every Ollama request (`llm.py`)
- [x] Bound every prompt block so Ollama never silently evicts the system prompt
      (history 9k, summary 3k, research 6k, vision 5k, attachments 10k characters)
- [x] Rolling conversation summaries for long chats (first at 48 messages, then every 24)
- [x] Per-model thinking decisions: complex/factual/multi-step prompts get a thinking pass,
      casual chat stays fast (`persona.should_think`)
- [x] Browser-safety and app-discovery fixes (never close a whole browser for a tab request;
      substring/registry app lookup with ambiguous-name candidates)
- [x] Drawn schemas via a per-request Mermaid directive
- [x] Prompt section on planning, pronoun resolution, adapting after failure, and claiming only
      tool-confirmed actions

## Stage 2 — Core intelligence and agent system (current)

Goal: one reliable execution path for tools, honest capability reporting, and better answers.

- [x] Model capability detection
  - Add `himari/models.py`: query Ollama `/api/show`, cache per model, expose
    `supports("completion" | "tools" | "thinking" | "vision")`
  - Do not send `think` to models without thinking support; report tool/vision gaps honestly
- [x] Chat-path tool argument validation
  - Reuse `ToolRegistry.validate_arguments` before any chat handler runs
  - Return a structured “Invalid arguments” observation the model can correct
- [x] Per-tool execution metadata (partial)
  - `timeout_seconds` is read from `tools.TOOLS` entries by both chat and agent
    (`research_web` 90 s, `browser_*` 90 s, screen-control tools 25 s, default 30 s)
  - `mutates_state` and `output_schema` are still open
- [x] Unify chat and agent execution
  - [x] Shared bounded invocation (`himari/tool_exec.py`) now backs both `LLM.stream_chat` and
        `agent.Executor`: per-tool `timeout_seconds`, a 30 s default, honest timeout text, and the
        same worker-thread isolation
  - [x] One result classifier and audit trail across both paths
        (`himari/tool_results.classify_result`): the security layer stamps every recorded result
        with `{"ok": bool, "error": text}` in its audit entry, the chat logs classified failures,
        the agent keeps the same failure semantics, and tool cards are marked `TOOL · FAILED`
  - Browser tools now declare 90 s timeouts so a first Playwright launch is not cut off
- [x] Completion gating and verification reporting
  - `verified` is included in every agent status event and the final state
  - A completed task with denied/invalid/failed steps is labeled
    “completed (some steps unverified)” in the agent pane and appends a warning message
  - The agent never presents such a task as fully verified; the status stays `COMPLETED`
    because an honest final answer was produced (changing it to `FAILED` would misreport
    deliberately answered tasks, as covered by existing tests)
- [x] Confirmation bounds
  - `wait_for_decision` waits at most 120 s, fails closed, and is used by both chat and
    agent confirmation paths; a timeout shows “the action was not allowed”
  - Outstanding confirmations register in `security.confirmation` (`new_decision` /
    `resolve_decision` / `release_pending_confirmations`); Stop, cancel-agent and window close
    release every waiter as denied and reject an open dialog, so a tool never sits in a
    confirmation wait after the user has cancelled or quit
  - the tool invocation helper now uses a daemon worker thread instead of a
    `ThreadPoolExecutor`, so a timed-out long-running tool can no longer keep the process alive
    at exit; the honest “may still be running” message is unchanged
- [x] Empty-reply retry keeps tool observations
  - the retry context keeps the system rules, the current request, and subsequent assistant/tool
    messages instead of dropping everything after the user turn; long tool outputs are capped at
    1,200 characters and the tail is bounded to 12 messages

Acceptance for stage 2: malformed tool arguments never reach a handler; a model without tool support
is reported instead of looping; the agent cannot present a task with failed steps as fully verified;
confirmation waits cannot hang forever; full suite green (469 passed, 1 skipped).

## Stage 3 — Research engine

- [x] Multiple focused queries per research request (primary + one intent-aware refinement:
      “latest developments” for freshness intents, “comparison” for vs/compare intents)
- [x] Fetch and extract readable text from the top pages (script/style/nav/header/footer/aside/form
      removal, class/id/role boilerplate markers, duplicate-line collapse, 1,300-character page budget,
      1.5 MB response cap, 8 s per page, three pages fetched concurrently)
- [x] Deduplicate near-identical pages and track source domains (one page per domain, URL dedupe
      across both queries; overlapping results merge)
- [x] Extract publication dates where available and surface them (`article:published_time`,
      `og:published_time`, `datePublished`, `<time datetime>`)
- [x] Structured source list with titles, URLs, dates, and which claims they support
  - each research entry is numbered with its title, publication date when known, excerpt, and
    `Source:` URL; the prompt now asks the model to put the matching entry number in brackets
    after every factual claim and to end with a `Sources:` line naming only the entries used
  - attribution is model-generated from the numbered evidence (not independently fact-checked);
    titles, URLs, and dates come from the fetched pages
- [x] Provider abstraction (DuckDuckGo today; additional privacy-respecting providers optional)
  - `_fetch_web_results` dispatches to DuckDuckGo by default or to a user-configured self-hosted
    SearXNG instance (`research.searx_url`, JSON API); result URLs are still filtered to the public
    web, and instance errors/invalid JSON are reported honestly
- [x] Research progress events in the UI (query → sources → reading → answer)
  - `research_web(..., progress=...)` emits search/read/answer stages; the chat worker forwards them
    to the status line (“Searching: …”, “Found N source(s)…”, “Read N page(s)…”)
- [x] Cancellation between fetches (page reads run in a bounded ThreadPoolExecutor, no cancel token yet)
  - `research_web(..., cancel=...)` checks a cancellation event before searching, after each search,
    and while collecting page futures; cancelled research returns an honest cancellation message
    instead of a partial answer
- [x] Tests: parser, multi-query, extraction, citation rendering, failure honesty

Implementation notes (verified 2026-11-12):
- `research_web` now returns `Web research for:`, `Search queries used:`, a read count, numbered
  entries with `Page excerpt:` (or honest `Snippet (page could not be read):`), `Published:` when
  known, `Source: <url>`, and an explicit untrusted-data warning. Output is capped at 6,000 characters.
- `_is_public_url` refuses non-HTTP(S), localhost/`.local`/`.internal`/`.home.arpa`, and IP literals
  that are not globally routable; redirects are re-checked before parsing.
- Live check: “Python 3.13 release notes” ran two queries, read three pages, cited dates, 6,098 chars.
- Limitation: pages that require JavaScript render only their static HTML; those fall back to the
  search snippet. There is no headless-browser page reader because browser automation is opt-in.

Acceptance: a “latest changes in X” question uses at least two queries and at least one full page, and
the answer cites named sources with dates when available. (Tested: two queries, three pages, dates.)
Full suite green (**563 passed, 1 skipped**); SearXNG parsing and cancellation are covered by unit
tests with fake HTTP responses.

## Stage 4 — Image generation and editing (completed, then removed on 2026-11-12)

> Superseded: the entire image-generation feature was deleted in Stage 8 at the user's request.
> The notes below remain as a historical record and no longer describe the shipped app.

- [x] Provider interface (`ImageProvider`) with the current A1111-compatible backend as default
  - `himari/imagegen_backends.py` defines `ImageProvider`, `ProviderResult`, `A1111Provider`, and
    `ComfyUIProvider`; `imagegen._providers()` keeps the bundled sd-server / A1111 path first in
    automatic mode
- [x] Optional ComfyUI adapter, endpoint configured locally, no automatic model downloads
  - Uses ComfyUI's local `/prompt` → `/history/{id}` → `/view` flow; a minimal text-to-image workflow
    needs only an installed checkpoint name; an API-format workflow file is optional
  - Missing checkpoint/workflow and unsupported modes are reported honestly; nothing is downloaded
- [x] img2img, inpainting, upscaling where the backend supports them
  - A1111 `/sdapi/v1/img2img` with reference images, denoising strength, and masks; AI upscaling via
    `/sdapi/v1/extra-single-image`
  - When a backend lacks AI upscaling, Himari falls back to a local Lanczos resize and labels it as
    such instead of pretending it was model upscaling
  - ComfyUI editing/upscaling require a custom workflow with `{{input_image}}`; otherwise the refusal
    explains what to add
- [x] Negative prompts, seed control, batch count, workflow presets
  - Negative prompts, explicit seeds, batch 1–2; A1111-reported seeds are recorded, and ComfyUI’s
    default workflow reuses the exact seed it reports (one random draw per request)
  - Built-in `cinematic`, `anime`, and `photo` presets; `imagegen.presets` can add more
- [x] Retain generation context (prompt, negative, seed, workflow, previous image) for follow-up edits
  - `last_generation()` remembers the latest record and falls back to the newest history entry, so
    `"last"` references and edit modes keep working after an app restart
  - Edit/inpaint/upscale use its first file when no reference path is supplied
  - Reference reads are limited to the Himari data folder and the configured allowed folders
- [x] Generation history and a preview panel with advanced settings collapsed by default
  - `generated/history.json` keeps the newest 200 records; the new Images tab shows thumbnails, a
    large preview, prompt/seed/mode/provider metadata, open-folder, and clear-list actions
  - Provider URL, ComfyUI URL/checkpoint/workflow live under a collapsed “Image generation
    (advanced)” disclosure; the generation permission stays visible
- [x] Restart sd-server after a crash (remove the `_STARTED` latch)
  - The facade tracks the launched process and checks `poll()`; a dead process is restarted on the
    next request, while a live one is not duplicated
- [x] Tests with a fake HTTP backend; live test documented as optional
  - `tests/test_imagegen_backends.py` exercises A1111 txt2img/img2img/upscale/errors and the ComfyUI
    workflow, upload, honest-refusal, and probe paths against an in-memory HTTP double
  - `tests/test_imagegen.py` covers edits from the previous image, presets, seeds/batch, history,
    reference-path permissions, inpainting masks, local upscale fallback, restart-safe edits, image
    caps, and crash restart
  - Diagnostics probe the configured ComfyUI URL when that provider is selected instead of always
    testing the A1111 port
  - Live verification needs a local A1111/ComfyUI server with a model; it is optional and was not run
    in this environment

Acceptance: text-to-image, image editing, inpainting, and upscaling all run through one provider
interface; a missing backend or unsupported mode produces an actionable error rather than a false
success; generation metadata survives for follow-up edits and appears in the Images tab; full suite
green (**534 passed, 1 skipped**).

## Stage 5 — Screen and application understanding

- [x] Respect monitor selection and add active-window / region capture in the UI path
  - `perception.capture.capture_screen()` reads `screen.monitor` from config
  - `capture_screen_text` and `screen_scene` accept `target` (configured / primary / all /
    active_window) and `monitor`; `screen_scene` also accepts a `region`
  - active-window capture requires `allow_active_window` in addition to `allow_screen_capture`
- [x] Windows UI Automation adapter for semantic elements (buttons, fields, menus)
  - completed later in Stage 8 with a new `pywinauto` dependency; scope is intentionally narrow
    (named controls only, no post-action verification)
- [x] `focus_window` with `SetForegroundWindow` and a verification step
  - matches by title or process name, refuses ambiguous matches with a candidate list,
    restores minimized windows, then verifies `GetForegroundWindow` and reports failure honestly
  - policy: `MEDIUM`, `allow_open_app`, per-action confirmation
- [ ] Post-action verification: capture/inspect after launch/focus/click and report what changed
  - focus is verified against `GetForegroundWindow`; `open_app` now snapshots window handles,
    waits up to 3 s for a new matching window, and reports either “Confirmed: … is visible” or an
    honest “no matching new window appeared” instead of trusting the launch API
  - click verification is still absent: Stage 8 added confirmed click/type/key tools, but Himari
    cannot prove that an application reacted to an input event
- [x] Register the safe read-only environment tools (`installed_apps`, `list_windows`,
      `running_processes`, `find_app`) with output caps
- [x] Find-or-create workspace handling for VS Code projects
  - `development/launcher.py` resolves a project by folder name or path strictly inside the
    configured `development.workspaces`, refuses ambiguous matches with a candidate list, and can
    create a new folder only in the first workspace (validated name, no traversal)
  - the `open_project` tool (confirmation required) requires `allow_open_app`; creation also
    requires `allow_write_file`; a missing VS Code install is reported honestly, and the launch is
    window-verified
  - Settings now exposes the workspaces list next to the file-tool folders
- [x] On-demand capture only; no background polling (the screen tools are one-shot and discard images)

Acceptance: full suite green (**554 passed, 1 skipped**); the new Settings list was smoke-tested
offscreen, launch verification and workspace resolution have unit tests.

## Stage 6 — Memory and voice

- [x] Optional local embeddings backend with hybrid (semantic + keyword) retrieval
  - `memory/embeddings.py` uses an embedding model the user has already installed in local
    Ollama, configured as `memory.embedding_model`; nothing is downloaded automatically
  - vectors are cached in SQLite per model and invalidated when a memory is edited or deleted;
    cosine similarity is blended with the keyword score, and an empty model keeps keyword-only
    behavior. A missing model, stopped server, or bad response logs a warning and falls back to
    keyword ranking instead of silently failing
- [x] Relevance + recency + importance scoring with a token budget and “why retrieved” metadata
  - `memory/scoring.py` ranks by query coverage, phrase hits, category importance, age, and an
    optional project boost; each selected item carries `score` and `reason`
  - `db.relevant_memories` and `memory.retrieval.retrieve` share the same scorer, so the two paths
    cannot drift
- [x] Prune summaries; keep a bounded history of prior summaries
  - `db.save_summary(..., keep=10)` keeps the newest summaries per session and deletes older ones;
    `summary_for_session` reads the newest deterministically
- [x] Merge overlapping summaries into one
  - `db.save_summary` compares the newest stored summary with the new one (Unicode-aware token
    Jaccard, at least six meaningful tokens per side, threshold 0.6); an overlapping summary
    updates the newest row with sentence-level deduplication instead of adding another near-copy,
    while distinct-topic summaries still keep a bounded history
- [x] Deduplicate near-identical memories
  - exact normalized duplicates and fuzzy near-duplicates (token Jaccard/prefix) merge into one row;
    the longer phrasing wins and an explicit category/project is adopted
- [x] Detect contradictions between memories
  - `memory/conflicts.py` flags pairs whose token overlap is at least 0.5 and that either use
    opposite terms (like/dislike, always/never, enable/disable) or disagree in polarity (one side
    negated); `MemoryManager.conflicts()` feeds the Memory tab’s “Check contradictions” button,
    which lists the pairs and states plainly that nothing is changed automatically. It is a
    conservative lexical heuristic: it can miss paraphrased conflicts and never edits or deletes
    user memories on its own
- [x] Memory search/filter/edit in the Memory pane
  - search plus a category filter; rows carry their memory id so edit/delete act on the selected
    item even when the list is filtered
- [x] Wake-word redesign (dedicated engine or VAD push-to-talk); stop TTS while listening
  - the monitor now uses an energy VAD: audio above the threshold opens an utterance, a 0.3 s
    pre-roll keeps the first syllable, and only after 0.6 s of trailing silence (or an 8 s cap)
    is the complete phrase transcribed once. Blips shorter than 0.25 s of speech are ignored, so
    speech recognition no longer runs on every noisy callback or splits the wake phrase
  - no new engine, model, or download was added; starting push-to-talk or a wake command still
    stops TTS before the microphone opens (covered by voice and UI interruption tests)
- [x] Voice settings apply immediately; output device selection
  - TTS reads voice, volume, microphone and speaker settings each time it speaks or records, so
    changes take effect on the next reply or recording without restarting Himari
  - Settings lists available output devices (System default plus `sounddevice` outputs); playback
    uses the chosen speaker and an unavailable device produces an explicit error instead of
    silently falling back to the system default
- [x] Interrupt TTS with the mic or the Stop key
  - starting push-to-talk or a wake-word command stops any speech already playing before the
    microphone opens, preventing Himari from transcribing its own voice; the existing
    “Stop voice” button remains the explicit interrupt

## Stage 7 — UI, reliability, release

- [ ] Split `ui.py` into chat, settings, voice and agent controllers
  - deferred as a post-release refactor: `ui.py` (2,414 L) remains window orchestration, while
    rendering, settings validation, tools, voice, memory and agent logic already live in separate
    modules. Moving the remaining Qt slots now would be a high-risk rewrite with no behavior change
- [x] Incremental chat rendering (no full re-render every token)
  - `chat_web.build_render_payload` keeps a full-render baseline (`html`) and, when only the
    last visible message is still streaming, sends just that card (`last`); the page replaces
    `#transcript`'s last element instead of rebuilding the whole transcript
  - tool visibility toggles, message-count changes, and any non-streaming final update fall
    back to a full render; covered by unit tests and verified in an offscreen QtWebEngine page
- [x] Syntax highlighting and copy buttons
  - fenced code blocks get a labeled toolbar with a copy action; Python, JavaScript,
    TypeScript, JSON, Bash, PowerShell, SQL, C/C++, Java, and CSS are highlighted with a small
    built-in tokenizer (no new dependency); tool output is never tokenized, and highlighting is
    skipped while a message streams
  - every message with text has a “Copy” action that copies the original Markdown; copying is
    bridged through a one-way `prompt("himari-copy", …)` handler so it works without browser
    clipboard permissions (falls back to the browser API when the page is opened outside the app)
  - verified in an offscreen QtWebEngine page: 9,000-character copy round-trips byte-for-byte
- [x] Wire the existing `control/settings.py` service and permission toggles
  - the Settings close path now builds one updates object (privacy, permissions, Ollama, image,
    UI, voice, screen, development) and saves it through `SettingsService.update`, which validates
    every key before writing and preserves untouched sections
  - invalid values are logged and shown once instead of silently replacing the file; the image
    provider/ComfyUI fields were added to the validation schema
- [x] Crash handler (`sys.excepthook` + Qt message handler)
  - `himari/crash.py` logs unhandled main-thread and worker-thread exceptions and maps Qt messages
    into the log; a one-time dialog names the log file
- [x] In-app log viewer
  - `himari/log_viewer.py` shows a bounded 200 KB tail of the rotating log in a read-only dialog
    with a minimum-level filter (INFO/WARNING/ERROR), text search, refresh, copy, and open-folder;
    tracebacks stay attached to the entry above them and a missing log is reported honestly
  - opened from Settings next to “Open log folder”; the dialog instance is reused; the tail reader
    skips a partial first line and never loads the whole file on the UI thread
- [x] Single-instance guard
  - `himari/single_instance.py` uses a per-user `QLocalServer`; a second launch asks the first
    window to show itself and exits; verified offscreen and unit-tested
- [x] Apply settings on change; validate before writing
  - `_settings_updates(text_fields=False)` builds the subset of widget values that are valid by
    construction (checkboxes, combos, sliders, spin box, folder/workspace lists, TTS voice) and a
    single-shot 600 ms timer saves it through the validated `SettingsService` after any change
  - failures during autosave log a warning and show one status message instead of a modal; the
    close-time save still writes every field (including URLs, model ids and hotkeys, which stay
    commit-on-close because they may be mid-typing) and keeps the “Settings not saved” dialog
- [x] Rebuild `release\Himari.exe`; packaged smoke test
  - README updated for syntax highlighting/copy, the Images tab and generation history,
    verified agent completion labels, multi-query research, reliability aids (single instance,
    crash log, log viewer, validated settings autosave), monitor/active-window capture, and the
    new documentation links; the stale `DEVELOPMENT_PLAN.md` reference was removed
  - rebuilt on 2026-11-12 after the running windows were closed: 627 passed, 1 skipped, assets
    staged (`base.en`, `en_US-amy-medium`), the image engine embedded, and the packaged
    `--self-test --gui --require-ollama` smoke test passed with exit code 0. The previous 2.5 GB
    executable was preserved as `release\Himari-previous-2026-11-12.exe`

- [x] Deterministic managed image checkpoint
  - `imagegen.managed_model` (validated, default empty) lets the managed `sd-server` load a
    specific installed `.gguf`; a missing file logs a warning and falls back instead of failing
  - `embed_imagegen_payload.py` prefers the small `stable-diffusion` checkpoint, so installing a
    large model in `%USERPROFILE%\.himari\imagegen\models` does not inflate the release payload;
    `--model` selects a different checkpoint explicitly
  - tests cover configured selection, warning fallback, and payload checkpoint choice

## Stage 8 — Screen control replaces image generation (completed 2026-11-12)

- [x] Remove image generation end-to-end
  - deleted `imagegen.py`, `imagegen_backends.py`, `imagegen_payload.py`, the embed script, the
    Images tab, Settings fields, the `generate_image` tool, `IMAGE_PATH:` transport, local model
    assets, tests, notices, and docs
  - the release carries no image-model weights and Himari cannot draw, paint, or edit pictures
- [x] Gated low-level input layer (`himari/windows/input.py`)
  - `SendInput` Unicode typing, key combinations, absolute virtual-desktop clicks, and wheel
    scrolling; per-monitor DPI awareness; one bounded action per call; honest send-error reporting
  - the Windows key is refused, text is capped, and coordinates must be on the visible desktop
- [x] Semantic control (`himari/windows/uia.py`, `pywinauto`)
  - `find_window` resolves an exact title, then a substring, then a process name; ambiguity is an
    error with a candidate list
  - `list_controls` is read-only and does not steal focus; `click_control` and `set_control_text`
    match exact names first, then substrings; duplicate names are refused; password fields are
    refused; click falls back from `click_input` to `invoke`
- [x] Register seven tools: `list_controls` (READ), `click_control`, `set_control_text`,
  `type_text`, `press_keys`, `click_at`, `scroll_screen` (all HIGH)
  - new `allow_screen_control` permission, off by default, in Settings and the schema
  - every input tool requires confirmation; `press_keys` is in `NEVER_SESSION_GRANT`
  - tools re-check the permission inside the handler as defence in depth
- [x] Persona, diagnostics, packaging, and documentation
  - persona explains semantic-before-coordinate ordering and the password/secret rule
  - diagnostics reports UI Automation availability; build script no longer bundles an image engine
  - `pywinauto`, `comtypes`, and `psutil` are packaged; requirements and notices updated
  - tests cover key parsing, input bounds, coordinate rejection, ambiguity, password refusal,
    fallback activation, and fail-closed permission gating

Acceptance: image generation is absent from code, config, UI, and the build; screen control is
unusable until enabled and confirmed, refuses the Windows key and password fields, never guesses
duplicates, and never runs continuously. Full suite green (**586 passed, 1 skipped**).

Verified so far: **586 passed, 1 skipped**; image generation removed from the executable and the
user-authorized `%USERPROFILE%\.himari\imagegen` assets (5.9 GB) deleted. The screen-control layer
passed a live test against Windows Calculator: `list_controls` enumerated the real control tree,
semantic `click_control` produced 1 + 2 = 3, and `type_text` + `press_keys` produced 12 + 7 = 19.
The rebuilt onefile is 610 MB (previously 2.52 GB) and its packaged `--self-test --gui
--require-ollama` smoke test passed. Remaining manual checks: typing into password fields is
refused, and a multi-window ambiguity must be resolved by a more specific title.

## Stage 9 — Deep control and action reasoning (completed 2026-11-12)

- [x] `open_app` focuses an existing window
  - process-name matches are preferred over title matches, so a note titled “Chrome” is
    never mistaken for the browser; the tool reports the focused window and starts no duplicate
  - launch verification waits up to 8 s and accepts a new process as evidence, so a slow cold
    start is no longer reported as a failed launch
- [x] Active-window targeting
  - `window="active"` (also `foreground`, `current`) resolves the real foreground window in
    `windows/uia.py`; duplicate titles such as several Chrome windows no longer block control
  - read-only `list_controls("active")` still does not steal focus
- [x] Deep reasoning covers app actions
  - `persona.should_think` treats desktop action verbs (open, launch, click, type, press, focus,
    window, browser, …) as worthy of the thinking pass when `deep_reasoning` is enabled; the
    Settings label and tooltip now say so
- [x] Persona control playbook
  - open once, then read controls; one confirmed action per step; a denied screen action is never
    reported as a failed launch; use `active` for duplicate titles; Chrome page content goes
    through `open_url`/`browser_*`, not screen control

Verification: **591 passed, 1 skipped**. Live: `open_app("Google Chrome")` focused an existing
window without starting another; `list_controls("active")` read that window's real controls; and
`should_think("open chrome")` is now true. Rebuilding `release\Himari.exe` is the only remaining
step and needs the running app closed first.

## Stage 10 — One request, one page (completed 2026-11-12)

- [x] Background video resolution
  - `himari/youtube.py` reads the public YouTube results page once and extracts title, channel,
    duration, and watch URL from the embedded `ytInitialData` JSON. No API key, browser window,
    or download is involved.
  - New `find_video` tool (silent, READ, `allow_web_research`) returns up to five candidates and
    opens nothing. Live check: "fireplace video 10 hours" returned three real watch URLs.
- [x] Tabs follow the request
  - `browser_open_result` reuses the current tab by default and replaces the search page;
    `new_tab=true` is opt-in. `open_search` replaces an existing search tab instead of stacking.
  - Himari's own browser refuses to exceed five tabs with a clear message, and points at
    `browser_tabs` or `new_tab=false` instead of opening without bound.
- [x] Model guidance and window filtering
  - The persona opens a browser only when asked, allows one final page per request, and requires
    `research_web`/`find_video` before opening a single chosen URL. Repeated candidates are forbidden.
  - `list_windows` accepts `name_filter` (and the `window` alias the model had tried), so window
    inspection no longer fails with an unexpected keyword argument.
- [x] Verification
  - Full suite: **606 passed, 1 skipped**.
  - Stubbed live model runs: "open a fireplace video" called `find_video` then exactly one
    `browser_open` (browser opens = 1); "open the first result for fireplace videos" made one
    `open_url` call; "what is a fireplace?" opened nothing.
  - Rebuilt `release\Himari.exe` (609.8 MB); the packaged `--self-test --gui` smoke test passed.

## Stage 11 — Desktop polish, custom keys and capture region (completed 2026-11-12)

- [x] Design and motion
  - New `himari/ui_effects.py`: window fade on first show, page fades when switching tabs (skipping
    `QWebEngineView` pages to avoid compositing artifacts), message/element fade helper, pulse, and
    `CollapsibleSection` with an animated height transition and a checkable header.
  - `himari/theme.py` gained styles for Settings cards, section headers, hints and the key-capture
    button, plus a subtle header gradient and menu padding. Palette colors are unchanged.
  - Chat transcript: new messages animate in with a staggered fade/slide, the welcome screen has an
    entrance animation and clickable prompt chips, and smooth scrolling is used for settled updates
    while streaming stays instant. A `prefers-reduced-motion` media query disables it.
- [x] Settings rebuilt around sections (`himari/ui_settings.py`)
  - Voice & microphone, Screen & shortcuts and Privacy & memory open by default; Permissions,
    Advanced and Window & data start folded. The dead run-command control was removed; reminders
    that are not wired or not installed are stated honestly instead of presented as toggles.
  - The Settings tab builder moved out of `ui.py`, which keeps the main window a chat shell.
- [x] Custom shortcuts (`himari/ui_widgets.py`)
  - `KeyCaptureButton` records the next chord, normalizes it to `keyboard` package syntax
    (modifier-first, de-duplicated), rejects lone printable keys, and clears with Backspace/Delete.
  - Global hotkeys are suspended while a shortcut is being recorded and rebound immediately after
    saving. Duplicate push-to-talk/capture keys are refused with an explicit message.
  - The chat footer shows the active shortcuts; Settings changes update the buttons and labels.
- [x] Custom screen capture region (`himari/region_select.py`)
  - A one-time screenshot of the primary monitor is dimmed and shown full-screen; dragging a
    rectangle maps the selection to absolute physical pixels, so display scaling cannot shift it.
  - The chosen region is saved as `screen.region` with `screen.monitor = "region"`, validated by the
    Settings schema, and used by the capture hotkey, the Screen button and `capture_screen()`.
    Missing or invalid regions are reported instead of silently capturing the whole screen.
- [x] First-reply latency made explicit
  - The waiting indicator now says the local model is waking and that the first reply after launch
    can be slower; preload reports “warming” and “ready” states. No speed was faked.
- [x] Documentation cleanup
  - Deleted `AVATAR_GUIDE.md`; its sprite names, sizing guidance and Live2D boundary now live in the
    README avatar section (the avatar placeholder points at the assets folder).
- [x] Verification
  - Offscreen construction of the real window: 6 tabs, 6 Settings sections, shortcut labels, screen
    area defaults, section expansion and welcome-chip fill all exercised without errors.
  - Full suite: **623 passed, 1 skipped**.

## Stage 12 — Outcome-driven agent and daily-use core (completed 2026-11-13)

Goal: turn comprehension → planning → execution → verification → honest reporting into the one path
that both chat and tasks use, and make the three daily-use integrations real.

- [x] Understanding layer (`himari/core/`)
  - Rules-first `Intent` extraction (category, goal, entities, expected outcome, confidence), optional
    model merge that may only refine a rules result, and validation of merged output.
  - `capabilities.py` registry: tags, risk/permission metadata, 30 s availability TTL, required vs
    optional filtering, and a 16-tool ceiling per request.
  - `context.py` environment brief (OS, desktop, available helpers) appended as guidance, not as
    user instructions.
  - `reasoning.py` profiles — direct (3 rounds / 3 steps), guided (8 / 8, one replan), deep
    (16 / 20, two replans) — with automatic escalation; the model still cannot raise its own budget.
- [x] Outcome-driven execution (`himari/agent/`)
  - `AgentOrchestrator` runs plan mode (validated DAG, one ready step per round, skips dependents of
    blocked steps) or step mode (one next action per round); chat and tasks select tools through the
    same capability registry (`tools_for_intent`) and share schema validation and result
    classification, while tasks add planning, per-tool verification, recovery and persisted state.
  - `Executor` pipeline: known tool → schema validation → authorization → handler with timeout →
    failure classification, with per-tool verification and an objective check before a task can be
    reported complete.
  - Conservative recovery (`recovery.py`): permission stops, invalid replans, unavailable uses a
    working alternative, a timed-out or unverified *mutating* action is never retried automatically,
    and unclear failures ask the user.
  - `TaskRecord` lifecycle persisted to SQLite; blocked tools, replan counters and cancellation are
    enforced rather than described.
- [x] Real daily-use integrations
  - Spotify: Client Credentials token (client ID/secret from Settings only), search and ranking,
    `spotify:track:` deep link, playback confirmation by polling the Windows media session for 18 s,
    UIA fallback, and an explicit `verified` flag instead of an assumed success.
  - Weather: Open-Meteo with geocoding and IP fallback, WMO descriptions, 10-minute cache, structured
    location in the result so failures can be reported honestly.
  - Calendar: local SQLite events, natural-language parsing, confirmation-gated create/delete, and
    `.ics` export whose success is verified on disk.
- [x] UI and Settings
  - Tasks tab (create, watch, cancel) and Activity tab over the real action log; Settings gained the
    services section for Spotify credentials and calendar options.
- [x] Documentation
  - [ARCHITECTURE.md](ARCHITECTURE.md) rewritten for the current runtime, plus
    [AGENT_DESIGN.md](AGENT_DESIGN.md), [EXECUTION_ENGINE.md](EXECUTION_ENGINE.md),
    [TOOL_SCHEMAS.md](TOOL_SCHEMAS.md), [APP_DISCOVERY.md](APP_DISCOVERY.md),
    [FAILURE_RECOVERY.md](FAILURE_RECOVERY.md) and [SECURITY_MODEL.md](SECURITY_MODEL.md).
- [x] Verification
  - `compileall` OK; full suite **709 passed, 1 skipped**.
  - Tests cover intent extraction, capability selection, reasoning budgets, plan validation,
    executor failure classification, recovery decisions, verification (including weather structure
    and calendar export on disk), Spotify ranking, weather parsing and calendar round-trips.
  - Follow-up fixes on 2026-11-13: long restored transcripts no longer animate through a huge smooth
    scroll, which left the embedded view unpainted and looked like missing text; the view now jumps
    instantly for long distances, stays pinned to the bottom as late content grows, and unpins when
    you scroll up. Ordinary open/watch/play requests are structurally routed to the user's signed-in
    default browser: `browser_*` tools are removed from intent tool lists unless the request explicitly
    names Himari's browser or its tabs, with regression tests for both paths. The Tasks table now uses
    the app theme, a styled header and status colors instead of the default gray grid.
  - Packaged portable build produced on 2026-11-13: `release\Himari.exe` (610,009,595 bytes,
    SHA-256 `613D4FE439C2C3809AE53E39008818F4D06DBBCE7C393B1BB1351D388C60BD19`), bundling `base.en`
    and `en_US-amy-medium`; the packaged `--self-test --gui` smoke test passed, and a packaged
    launch with a seeded 32-message transcript showed the complete tail with code and table blocks
    after restoration. The pre-fix executable is archived as
    `release\Himari-previous-build-2026-11-13-1320.exe`.

Remaining after this stage:

- Calendar reminders (no scheduler runs yet) and editing an already-created event.
- More apps at the *inspectable/controllable* support level; most discovered apps are still
  launch-only, which the UI states rather than hides.
- A multilingual speech model is not bundled; rebuild with one prepared locally if Russian
  recognition is required.

## Stage 13 — Companion skills: watch, coaching, diagnosis and continuity (completed 2026-11-14)

Goal: make Himari feel like a companion who can help with almost anything on the machine without
widening the security boundary. Everything new lives in `himari/skills/` and is merged into the
existing registry, so risk checks, confirmations and audit logging keep applying.

- [x] `skills/` package with lazy tool aggregation (`skill_tools()`), imported at the end of
      `tools.py`; 69 registered tools, no duplicate names.
- [x] Watch companion — periodic, opt-in, visible, bounded
  - One short look at the active window every 20 s (Settings), a pink sidebar indicator, and an
    automatic stop after 30 minutes.
  - Observations live only in memory; the active-window permission is re-checked on every tick
    and the session ends if it is revoked. Known games are detected from process/window names.
  - UI: sidebar card with a live countdown and Stop, plus Companion-screen start/stop and status.
- [x] Setup Coach — interactive onboarding
  - Playbooks for Spotify credentials, VS Code pairing, voice/TTS, Ollama models, browser tools
    and the watch companion, with an aliases resolver and numbered steps.
  - `inspect_settings` / `setup_verify` report only whether a secret is configured, never its
    value; verification runs in a background thread.
- [x] System Doctor — read-only diagnosis
  - `inspect_system` and `diagnose_program` cover Ollama, disk, memory, GPU, battery, top
    processes and recent Windows event entries, with redaction.
  - Refuses to modify services, registry values, startup entries or security settings.
- [x] VS Code pair programmer
  - Reads open editors and the workspace from read-only `workspaceStorage` state behind the new
    `allow_vscode_state` permission, with a window-title fallback.
  - `propose_change` shows a diff, `apply_change` still needs confirmation, and `run_tests`
    accepts only allowlisted commands.
- [x] Media companion
  - `youtube_transcript` resolves a watch URL or ID, fetches public captions and returns a
    bounded, timestamped transcript. Needs the existing web-research permission; nothing is
    downloaded, saved or played.
- [x] Memory continuity
  - New `activity` memory category (weight 0.85), `remember_activity` and `project_context`.
  - Intent routing gained a `continuity` category; the environment brief now includes the active
    VS Code file and any running watch session.
- [x] Security and confirmation hygiene
  - `open_project` was missing from `TOOL_RISKS`/`TOOL_PERMISSIONS`/`CONFIRMATION_TOOLS` and was
    therefore denied by the default-deny layer; it is now registered.
  - `apply_change`/`propose_change` confirmations show the path, size and a 500-character preview
    instead of the whole file.
- [x] Verification
  - `compileall` OK; full suite **777 passed, 1 skipped**; new `tests/test_skills.py` and
    `tests/test_ui_skills.py`, with the memory category test updated.
  - Offscreen construction of the full window (eight screens, watch indicator, coach and doctor
    cards) succeeded and exited cleanly.

Remaining after this stage:

- Watch mode gives text advice from a single look; it does not yet track progress over time or
  suggest timed prompts.
- Setup Coach covers six topics; more integrations can be added by extending its playbooks.
- System Doctor reports only; it does not offer guided fixes for the problems it finds.

## Optional local backends

Himari must stay usable without any of these; missing backends are reported, never faked.

| Capability | Required | Install |
|---|---|---|
| Chat + tools + thinking | **Required** | `ollama pull qwen3:8b` |
| Vision | Optional (recommended) | `ollama pull qwen2.5vl:3b` |
| Speech recognition | Optional | local faster-whisper model staged under `models\`; see `prepare_speech_model.py` |
| Speech synthesis | Optional | Piper voice under `models\piper-voices`; see `prepare_release_assets.py` |
| Memory embeddings | Optional | any embedding model already installed in Ollama, e.g. `ollama pull nomic-embed-text` (user-initiated; never automatic) |

## Hardware notes

- Target machine: RTX 4060 Laptop, 8 GB VRAM. `qwen3:8b` at `num_ctx 8192` fits fully on the GPU;
  12288 spills ~0.9 GB to CPU and is slower. Keep the default at 8192.
- A vision request loads a second model; Himari unloads it when idle through Ollama's keep-alive
  rules rather than forcing it out.
- 8B model intelligence is the ceiling; orchestration, context quality, verification and research
  depth are what this roadmap improves. Larger models can be configured manually in `config.json`.

## Known limitations that will remain after this roadmap

- Some integrations will stay “open only”.
- Screen control cannot see inside elevated windows that Windows isolates from normal input, and
  browser pages expose only partial accessibility metadata.
- Browser automation cannot use the user’s normal Chrome profile without explicit design work.
- Wake-word quality is limited by the local STT engine.
- Agent completion can never be a hard guarantee for actions that have no observable side effect.

## How to verify a stage

```powershell
cd C:\Users\Lenovo\OneDrive\Desktop\Himari
python -m compileall -q himari
python -m pytest -q            # expected: all green, optional live tests skipped
powershell -File build_portable.ps1   # after closing Himari; rebuilds release\Himari.exe
```

Live checks that require Ollama should be run manually and their results recorded here.
