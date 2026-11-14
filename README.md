# Himari 5.0 (ひまり) — Local AI Desktop Companion

Himari is a Windows desktop companion built with PySide6. Chat and inference use a locally running Ollama service; conversation history and memories are stored in a local SQLite database. It does not use hosted AI APIs or telemetry. Optional, user-requested web research sends focused search terms to DuckDuckGo; it does not send chat history.

## Current capabilities

- Streaming Ollama chat with Qwen3 and bounded native tool calling.
- A living-companion shell: a persistent glass sidebar navigates Chat, Companion, Dashboard, Tasks, Activity, Memory, Settings and Diagnostics while keeping recent chats and the live status chip visible. Chat has rich Markdown replies (code blocks, lists, links), distinct user/Himari bubbles with timestamps, a small avatar badge and animated typing dots on Himari's replies, a streaming cursor, Stop for in-flight replies, and an optional Tools view. **Companion** mode shows the large avatar, live state, mood line and a voice waveform with Talk, Capture screen, Float avatar and Back to chat actions. The avatar is state-driven from real events — listening while the microphone records, thinking while the model generates, searching during web research, working during tasks, speaking during text-to-speech, happy after success, and concerned on failure. Sakura petals and light motes drift behind glass cards and aurora dividers; message entrance, tab fades and collapsible Settings cards animate smoothly and honor the system reduced-motion preference.
- Readable code and transcripts: fenced code is syntax-highlighted locally (Python, JavaScript/TypeScript, JSON, Bash, PowerShell, SQL, C/C++, Java, and CSS) with a language label and copy button; every message has a Copy action that keeps the original Markdown. Highlighting runs in the embedded page without a new dependency or network access. Long restored conversations jump straight to the newest message instead of animating through thousands of pixels, so the transcript never appears blank, and it stays pinned to the bottom while late diagrams finish drawing unless you scroll up.
- ChatGPT-style rich replies rendered in an embedded offline browser view: bold/lists/tables, LaTeX formulas through bundled KaTeX, and Mermaid flowcharts, mind maps, sequence, class, and state diagrams. Math, tables, and diagrams are drawn locally; the page blocks scripts, raw model HTML, and remote resources. A classic plain-text view remains selectable in Settings.
- Local vision: screenshots and attached images are read by a local Ollama vision-language model (`qwen2.5vl:3b` by default), which transcribes visible text, identifies the app and layout, reads values exactly, and answers your question about the image. Windows OCR is only a fallback when the vision model is unavailable.
- Attachments: images, PDF, Word (.docx), Excel (.xlsx/.csv), and text/code files can be attached with the Attach button, drag-and-drop, or a one-shot screenshot. They are read into bounded context for that message only and never uploaded.
- Semantic screen control for open applications, opt-in and off by default: Himari lists the real controls of a window through Windows UI Automation, then clicks a named button, menu item, or tab, replaces text in a named field, types literal text, sends one key combination, or falls back to a confirmed coordinate click or scroll. When several windows share a title, the foreground window can be targeted explicitly; asking to open an app focuses its existing window instead of starting duplicates. Every input action asks for confirmation; the Windows key is refused, password fields are never filled, duplicate control names are reported instead of guessed, and there is no continuous capture or background automation. Himari cannot generate, draw, or edit pictures.
- **Watch companion**, opt-in and bounded: she takes one short look at the active window about every 20 seconds while you play or work, gives advice in chat, and shows a visible pink indicator in the sidebar and Companion screen. Each look re-checks the active-window permission, the session stops by itself after 30 minutes, and observations stay in memory only — no recording, no screenshots saved, nothing written to disk. Known games are detected from process and window names; turning it off is one button.
- **Setup Coach** on the Companion screen: pick Spotify credentials, VS Code pairing, voice and TTS, Ollama models, browser tools or the watch companion and get numbered steps plus a Verify button that checks the real configuration in the background. Secrets are never echoed — it reports only whether a value is present.
- **System Doctor** in Diagnostics: read-only checks of Ollama, disk space, memory, recent Windows events and a named program's app/process state. Event details are redacted, and it refuses to modify services, registry values, startup entries or security settings.
- **VS Code pair programmer**: with the `allow_vscode_state` opt-in, she reads the file and folder actually open in VS Code (read-only workspace state, with a window-title fallback), reviews the code like a fellow programmer, and shows a diff before any edit. Edits still require approval and tests run only from the allowlist.
- **YouTube transcripts**: give a watch URL or video ID and `youtube_transcript` returns a bounded, timestamped transcript of the public captions. Nothing is downloaded, saved or played, and the existing web-research permission applies.
- **Memory continuity**: a new `activity` memory category records what you were working on through `remember_activity`, and `project_context` brings together the active project, open editor, watch session and recent memories so she can pick up where you left off. The environment brief now includes the active VS Code file and any running watch session.
- Patient local-model handling: a visible elapsed wait timer, a long reply limit (900 s by default, adjustable in Settings), a 30-minute keep-alive so follow-up messages do not reload the model, optional startup preload, automatic retries while Ollama starts up, and a Retry button that keeps any partial reply. Leaked `<think>` reasoning tags are hidden, and a reply that contains only hidden reasoning is retried once without deep thinking. If the model returns an empty answer on a long chat, Himari retries once with a shorter context before showing an error.
- Warm, cozy companion personality: Himari talks like a close friend, remembers details you share, and keeps casual replies short and affectionate while staying precise during technical work. Formulas, comparison tables, and Mermaid diagrams still render exactly as before.
- Fast, grounded answers: stable general knowledge is answered directly, keeping everyday chat snappy. Explicit search requests and time-sensitive questions (news, prices, weather, releases, current office holders) trigger a quiet DuckDuckGo check and a cited answer. Deep reasoning is reserved for explicit planning, debugging, and long multi-step requests, and can be turned off in Settings.
- Chat management: delete a single chat from the toolbar or by right-clicking it, or clear all chat history in Settings. Saved memories, settings, and the activity log are kept.
- One-click memory capture: select text in the transcript and choose **Save memory**, or use **Add** in the Memory tab. Explicit requests such as "remember that", "keep in mind that", "don't forget that", "note that", or "запомни, что" are remembered immediately and used in later chats; the Memory tab shows them alongside your saved facts.
- Configurable "Voice on/off" switch so replies can stay silent without disabling speech features; the push-to-talk and screen shortcuts are captured by pressing them and are shown in the buttons and under the message box.
- Outcome-driven tasks (Tasks tab) and chat share one capability layer: Himari reads the request into an intent, selects only the relevant tools, plans multi-step work, executes one step at a time with validation and confirmations, verifies the outcome, and reports honestly when something could not be confirmed. Failures are classified; a mutating action that timed out or could not be verified is never retried automatically. Chat and tasks use bounded reasoning budgets rather than a fixed five rounds.
- Dashboard and Diagnostics tabs showing Ollama/model status, voice configuration, enabled capabilities, memory counts, integrations, recent audit activity, and local dependency checks. Long checks run in background threads.
- Reliability aids: only one Himari window can run at a time (a second launch raises the first), crashes and Qt warnings are written to a rotating local log, and **View application log** in Settings opens a bounded, searchable, level-filtered viewer with copy and open-folder actions. Permission and other safe Settings changes save automatically through a validated service; invalid values keep the previous configuration instead of silently replacing it.
- Centralized security layer: risk levels, default-deny unknown tools, Settings permission checks, mandatory confirmations, path/command validation, and audit logging with secret redaction.
- Quiet, source-linked background web research for explicit searches and current questions; no browser window is opened. Time-sensitive topics such as news, prices, weather, releases, and current office holders are detected automatically, two focused queries are tried, up to three result pages are read for actual content, and answers cite titles, URLs, and publication dates when available. Stable general knowledge answers directly, keeping chat fast, recently fetched results are cached for 10 minutes, and questions about today's date, weekday, or local time use the local clock instead of the web.
- Videos that actually open: asking "play the first video" sends `open_video` to YouTube, which resolves real results and opens exactly one watch page in the signed-in default browser. `find_video` returns candidate titles, channels, durations, and watch URLs without opening anything when you want to choose, and `open_first_result` does the same for ordinary web links. Himari reports what opened and never claims a video is playing when only the page was opened.
- Read-only disk check: `scan_large_files` walks Downloads, Documents, or another folder allowed in Settings and reports the largest files plus per-subfolder totals. It deletes, moves, and opens nothing, and asks for the normal file-read confirmation once per session.
- Push-to-talk recording, local faster-whisper transcription, and interruptible English Piper / Windows Russian speech output.
- Selectable input microphone and output speaker, push-to-talk and screen-capture shortcuts you set by pressing them in Settings, multilingual speech recognition, chat, editable memories, and per-session local history.
- One-shot, user-confirmed screen capture from the configured capture area — the primary screen, all screens, the active window with its separate opt-in permission, or a custom region you drag out once in Settings — through the global capture hotkey or the Screen button. The screenshot becomes an attachment so you can add your own question before sending; it is analyzed by the local vision model only when you press Send and is never written to disk.
- Permission-gated app/browser launches, Spotify track playback with optional Web API search (credentials entered in Settings, never hardcoded), Steam game launch, system volume, and confirmed file access.
- Weather forecasts through Open-Meteo, and a local Himari calendar with confirmation-gated create/delete and `.ics` export. Calendar events do not yet trigger reminders.
- Windows-native app, process, and window discovery with graceful close requests; no forced termination.
- Optional browser automation through local Playwright and the user's installed Chrome, Edge, or Firefox. It opens a separate Himari browser window with an isolated profile, can search, open the first or Nth result, read pages, and list/focus/close its own tabs. Opening a result reuses the current tab by default, so one request leaves one page, and the window refuses to exceed five tabs. It is off by default, never touches the user's everyday Chrome tabs, never purchases or pays, refuses CAPTCHA/auth bypass and password entry, rejects ambiguous page elements, and asks before submit-like actions.
- Workspace-restricted development tools: file reading, code search, diff previews, approval-gated edits, and allowlisted test commands.
- Categorized long-term memory with deduplication, bounded relevance retrieval, saved-session summaries, and an approval workflow; categories now include activity notes so she remembers what you were doing, and memory can be disabled in Settings.
- Configurable personality (name, playfulness, roleplay level) with a serious technical mode. Persona settings never relax security rules.
- Optional Windows media-key controls. They target the active media session and cannot confirm which app handled a command or whether playback changed; use `play_music` when playback confirmation matters.
- Optional draggable floating avatar window with support for original transparent PNG expression and animation sprites.
- File tools are restricted to the folders listed under **Settings**. File writes and shell use are disabled by default.
- PyInstaller Windows build and Inno Setup installer scripts.

## Requirements and setup

1. Use 64-bit Windows 10/11 and install Python 3.10+ and Ollama. Windows OCR uses the system's installed OCR languages.
2. Run `setup_windows.bat` to install Python dependencies. Speech model and Piper voice downloads are separately prompted; they are optional and never happen during application startup.
3. Prepare the local chat model yourself with `ollama pull qwen3:8b` while online. Himari does not download Ollama models. Start Ollama before launching.
4. For screen and image understanding, also run `ollama pull qwen2.5vl:3b` (about 3.2 GB). Images are only sent to this local model when you attach one and press Send.
5. Screen control needs the `pywinauto` package, which `setup_windows.bat` installs. It stays disabled until **Settings → Screen control** is enabled, and every click, keystroke, or typed string still asks for confirmation. It is Windows-only and does not control elevated windows that Windows protects from normal input.
6. Run `run_himari.bat`. If speech assets are unavailable, their features report an error rather than downloading a model on first use.
7. To build the portable Windows release, prepare the build environment and run the PowerShell command below. It creates a single-file `release\Himari.exe`; no model is downloaded during the build.

```powershell
.\build_portable.ps1 -RequireOllama
```

## Disk footprint (about 9 GB with every optional model)

Himari keeps the app and the local models separate. The default profile is approximately:

| Component | Size | Notes |
| --- | --- | --- |
| `Himari.exe` | ~0.6 GB | QtWebEngine, the Python runtime, speech libraries, Playwright, and UI Automation support |
| `qwen3:8b` | ~5.2 GB | Ollama chat model, managed by Ollama |
| `qwen2.5vl:3b` | ~3.2 GB | optional Ollama vision model for screenshots and images |
| **Total** | **~9.0 GB decimal (~8.4 GiB)** | without the optional vision model the profile is ~5.8 GB |

Himari no longer ships an image-generation engine, so the executable is small and the only external runtime dependency is Ollama. Larger chat models and additional speech models exceed this profile by design. Himari never downloads models automatically.

## Running the portable Windows application

Copy `release\Himari.exe` to any install location and run it. The speech assets and Python runtime are embedded in the single executable, so no adjacent folders are required and Python is not needed. Startup unpacks into a temporary folder, which is why the first launch takes longer than later ones. Ollama is installed separately and its local models are not bundled. If Ollama is unavailable or the selected model is missing, the UI and log explain how to connect/install it; Himari never downloads an Ollama model.

Speech recognition uses only model files already bundled with Himari or present in the local Hugging Face cache. The build script copies a complete local model into the distribution when one is available; it does not access the network to fetch weights. The currently tested distribution includes `base.en`, which is English-only and does not reliably recognize Russian. To build with multilingual recognition, prepare a complete multilingual model such as `large-v3-turbo` locally before building. Piper voices are bundled when prepared locally; additional local voices may be placed in `%USERPROFILE%\.himari\voices`. Russian replies use an installed Russian Windows speech voice if no Russian Piper voice is available. Voice assets are optional for chat-only operation. The application stores settings, database, temporary audio, and rotating logs in `%USERPROFILE%\.himari` (or the directory specified by `HIMARI_HOME`), never beside the installed executable. Windows OCR reads languages installed in Windows. Screen capture is explicit and one-shot: the user must enable it in Settings and confirm the prompt when the capture key or the capture button is used. The screenshot is attached to the chat message and analyzed by the local vision model; when that model is unavailable, the in-memory OCR text is attached instead. The image is never saved to disk and is sent only to your own local Ollama server.

The portable release includes a `--self-test` mode. To validate dependencies and models and open/close the packaged UI once, run:

```powershell
.\release\Himari.exe --self-test --gui
```

Add `--require-ollama` to require a running local Ollama service and the configured model. The same test is run automatically by `build_portable.ps1`.

When you ask Himari to search, verify something, or ask about news, prices, weather, releases, scores, or who currently holds an office, she checks DuckDuckGo over HTTPS and answers with citations. This background research does not open a browser window or fetch result pages. Search terms are sent to DuckDuckGo; background research can be disabled in **Settings**. Stable general knowledge is answered directly, keeping normal chat fast; if the search service cannot be reached, Himari says what she could not verify instead of guessing. Deep reasoning is used only for explicit planning, debugging, and long multi-step requests (the "Deep reasoning" setting), so greetings, personal questions, and everyday chat stay snappy.

Two kinds of link actions are available. `open_url`, `search_web`, `search_youtube`, `open_first_result`, and `open_video` open pages in the user's default browser; `open_first_result` resolves the search first and opens the chosen result instead of another results page, while `open_video` resolves a YouTube search and opens exactly one watch page (the first by default). Ordinary open, show, watch, and play requests — including YouTube and Spotify pages — always use that signed-in browser; the isolated Himari window is never chosen on its own. With browser automation enabled, `browser_open`, `browser_search`, `browser_open_result`, `browser_tabs`, `browser_read`, and `browser_close` operate on a separate visible Himari Chrome window that keeps its tabs between messages, and they are offered only when you explicitly ask for Himari's own browser or its tabs. That window uses an isolated profile without the user's saved logins, and it never lists or closes tabs in the user's own Chrome window.

## Offline preparation

On an internet-connected Windows machine with the same Python version and architecture, download compatible wheels into a `wheelhouse` folder:

```powershell
python -m pip download -r requirements.txt -d wheelhouse
```

Copy the project and `wheelhouse` to the offline machine, then run `setup_windows.bat`; it uses `pip --no-index`. To prepare a standalone speech-enabled build offline, first run setup on an internet-connected machine and copy the ignored `models\large-v3-turbo` and `models\piper-voices` folders with the project. Separately install Ollama and prepare its `qwen3:8b` model, and add Russian Windows speech/OCR languages if needed. Ollama model files are not included in the installer. Background web research and explicit website/Spotify actions require an internet connection.

## Use and privacy

The chat tab restores recent conversations from the local database, so closing and reopening Himari does not lose context. While the local model loads or writes, the status line shows how many seconds Himari has been waiting and explains that the very first reply after starting the app can take longer while the model loads; if preload is enabled, startup warms it in the background so later replies are quicker. The reply wait limit is adjustable in Settings (900 s by default), and the model stays loaded for 30 minutes so follow-up replies start faster. If Ollama is briefly unreachable Himari retries twice on its own; if a reply still fails, the **Retry** button resends the last prompt and any partial reply is kept on screen instead of being discarded. Delete one chat with **Delete chat** or by right-clicking it in the sidebar, or remove every chat in **Settings → Clear all chat history**; saved memories are not touched. Press the push-to-talk key (F9 by default, configurable in Settings) or the microphone button once to start recording and press it again to stop; Himari then transcribes locally and sends the recognized text to the assistant. No wake word is required. Push-to-talk recording stays active through pauses so a short break in speech will not cut off a sentence. In Settings, choose Automatic for multilingual language detection, or select English or Russian when you want to constrain recognition, and pick the microphone and speaker Himari should use (the speaker list includes System default). Recognition uses the locally bundled faster-whisper model, app-name hotwords, beam search, audio level normalization, and voice-activity detection. Clear commands to open Minecraft Launcher are normalized when transcription slightly misspells its name. The included model depends on the assets prepared before building; this tested release contains the English-only `base.en` model. Optional wake-word listening can instead monitor for the exact phrase "Himari" using local faster-whisper transcription, with an opt-in toggle and visual indicator; an energy-based voice-activity check transcribes one complete phrase after you stop speaking instead of every audio chunk. Spotify playback is requested through a track deep link, and Himari checks the Windows media session before saying the song is playing; without Spotify credentials it still plays the best title match but cannot rank covers and remixes. Steam games are matched by exact installed library title. File operations need per-action confirmation and must remain inside a folder explicitly allowed in Settings.

Screen capture happens only after it is enabled in **Settings** and the user presses the global capture key, clicks its one-shot button, or explicitly requests screen reading and confirms the prompt; no live capture is available. The capture key is configurable in **Settings**. Himari must still be running in the system tray; the shortcut is not available after choosing **Quit**. The screenshot is added to the message as an attachment so you can write your own question; it is held in memory, sent to the local vision model only when you press Send, and never saved to disk. If the vision model is not installed, Himari falls back to Windows OCR for screenshots and says that it could not analyze the picture fully. Attached files are read only for that message: text is bounded, PDF pages are capped, spreadsheets are capped by rows and columns, large images are downscaled, and nothing is uploaded. Screen control is separately permission-gated and off by default. When enabled, Himari reads a window's control tree and acts only on the control or point named in the confirmed action: it never launches, closes, or kills an app, never sends the Windows key, refuses password fields, rejects ambiguous control names, and does not capture or watch the screen in the background. Every input action is a single confirmed step. Active-window detection is off by default and only checks the foreground window when requested and enabled. Windows media controls are separately permission-gated and send media keys to the active Windows media session; they may affect an app other than Spotify and do not confirm playback state. Shell commands are off by default. General file writes remain scoped to allowed folders and require confirmation; the dedicated Desktop text-file action is limited to `.txt` files on the Desktop and also requires confirmation. The disk check (`scan_large_files`) is read-only and reports sizes only inside those allowed folders; it cannot delete or move anything. Website, app, screen-capture, screen-control, vision, active-window, and media permissions can be changed in **Settings**. Safe changes such as permission toggles, sliders, and device or language choices are saved automatically through a validated settings service; shortcuts save as soon as they are recorded, and text fields such as server URLs and model names are validated when you finish editing or when the window closes. An invalid value keeps the previous configuration and reports the problem instead of overwriting it. Tool activity is logged locally in `%USERPROFILE%\.himari\himari.db`; crashes and warnings go to the rotating log at `%USERPROFILE%\.himari\logs\himari.log`, which **View application log** opens in a bounded, searchable viewer.

## Avatar customization

The sprite renderer accepts original transparent PNG assets. Add them to `%USERPROFILE%\.himari\avatar_assets` to keep them across updates, or to `himari\avatar_assets` while developing; user assets take precedence. All frames for one animation should share the same canvas size and character position.

| State | Files |
| --- | --- |
| Idle | `idle.png`, optionally `idle_01.png`, `idle_02.png`, … |
| Blink | `idle_blink.png` (shown briefly while idle) |
| Listening | `listening.png` |
| Thinking | `thinking.png` |
| Speaking | `speaking_01.png`, `speaking_02.png`, … or `speaking.png` |
| Expressions | `happy.png`, `confused.png`, `sad.png`, `error.png` |

Multi-frame idle and speaking sprites are cycled automatically; speaking animation follows the text-to-speech status, and phoneme-level lip sync is not available. Without artwork Himari shows a clear placeholder rather than a geometric character mockup. A future Live2D renderer would be optional and behind the same avatar-state interface, and would never be required for chat, voice, or the sprite fallback.

Memory is saved immediately when you explicitly ask Himari to remember something — for example “remember that …”, “keep in mind that …”, “don’t forget that …”, “note that …”, or “запомни, что …”. It is available in later chats right away and appears in the **Memory** tab alongside facts you save yourself. You can also select text in a chat and press **Save memory**, or use **Add** in the Memory tab. Obvious credential phrases, contact details, and short-lived facts are filtered; do not use memory for secrets. Each turn includes a few recent facts plus the most relevant memories, and Himari is instructed to use them naturally rather than recite a list. Search in the Memory tab uses local lexical matching. Optionally, enter the name of an embedding model you have already installed in local Ollama (for example `nomic-embed-text`) in **Settings → Memory embedding model** to blend local semantic similarity into memory retrieval; Himari never downloads a model, and leaving the field empty keeps keyword-only search. **Check contradictions** lists saved memories whose wording or polarity appears to disagree; it is a conservative lexical check that misses paraphrased conflicts, and it never edits or deletes anything on its own. **Settings → Enable long-term memory** turns memory off entirely; existing records are not deleted. Deleting a chat or clearing history never deletes memories.

Browser automation is opt-in. When enabled, Himari drives a separate visible Chrome window with Playwright and the installed browser channel; no browser binary is downloaded and the window uses an isolated profile without the user's saved logins. Tab tools only see and close tabs in that window. Himari refuses payments, purchases, donations, CAPTCHA or authentication bypass, password fields, and model-generated JavaScript. Submit-like clicks and form submissions require confirmation every time and are canceled on cancel. Himari never stores passwords.

Personality settings can be edited in `config.json` under `personality` (`name`, `playfulness`: low/medium/high, `roleplay`: none/minimal/moderate). The core safety and honesty prompt is always included; personality never overrides permissions, confirmations, or the ban on inventing results. Avatar expressions remain the existing sprite states (idle, listening, thinking, speaking, happy, confused, sad, error); artwork is still user-supplied.

Tasks run in the Tasks tab with progress and a Cancel button, under the same permissions and confirmations as chat. The reasoning budget depends on the request (direct, guided, or deep, with bounded replans), and a step that failed, was denied, or could not be verified is reported as such; a possibly-executed mutating action is never retried automatically.

## Development

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md), [docs/AGENT_DESIGN.md](./docs/AGENT_DESIGN.md), [docs/EXECUTION_ENGINE.md](./docs/EXECUTION_ENGINE.md), [docs/TOOL_SCHEMAS.md](./docs/TOOL_SCHEMAS.md), [docs/APP_DISCOVERY.md](./docs/APP_DISCOVERY.md), [docs/FAILURE_RECOVERY.md](./docs/FAILURE_RECOVERY.md), [docs/SECURITY_MODEL.md](./docs/SECURITY_MODEL.md), [docs/MODULE_MAP.md](./docs/MODULE_MAP.md), and [docs/UPGRADE_ROADMAP.md](./docs/UPGRADE_ROADMAP.md) for architecture, module boundaries, completed work, and remaining milestones. Known weaknesses are tracked in [docs/TECHNICAL_DEBT.md](./docs/TECHNICAL_DEBT.md). Changes are tracked in [CHANGELOG.md](./CHANGELOG.md). The current memory search is local lexical matching (including Cyrillic); embeddings are not installed or described as semantic search.

Run tests with:

```powershell
python -m pytest -q
```

On this machine the test command used during development was:

```powershell
NO_PROXY= no_proxy= HIMARI_HOME="$env:TEMP\himari-test-home" python -m pytest -q
```

Clearing `NO_PROXY` only works around a local environment issue where a malformed `[::1]` entry breaks the Ollama client during collection; it does not modify system settings. The suite includes mocked tests for every new module plus a practical headless-browser test that skips when Chrome is unavailable.

### Reproducible portable build

Use 64-bit Windows Python 3.10–3.13, install dependencies, and pin the release packager to the version in `requirements-build.txt`:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
.\build_portable.ps1
```

The build refuses to overwrite an existing `release\Himari.exe`. It runs syntax checks and the test suite, stages only already-local Faster-Whisper/Piper assets, builds the single-file executable, and runs its packaged self-test. If models/voices are not staged, setup can be rerun to prepare them explicitly; `-AllowMissingSpeechAssets` allows a chat-only build with clear startup warnings. To require Ollama and the selected local model in the smoke test, use `.\build_portable.ps1 -RequireOllama`. The build script does not invoke `ollama pull` or download speech models.

`build_windows.bat` delegates to the same portable build and produces the same single executable.
