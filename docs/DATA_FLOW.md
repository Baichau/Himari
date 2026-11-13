# Himari 4 — Data Flow

## B. Message lifecycle

What happens from pressing **Send** to a rendered reply, with the real call sites.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant W as MainWindow (Qt thread)
    participant T as Worker thread
    participant P as persona.build
    participant L as LLM.stream_chat
    participant S as SecurityLayer
    participant H as Tool handler
    participant D as SQLite

    U->>W: Enter message + attachments
    W->>D: add_message(user, text)
    W->>W: render user bubble, busy = true
    W->>T: start _prepare_and_run
    Note over T: attachments parsed
    alt images attached (max 3)
        T->>T: vision.describe_images() on local vision model
    else screen capture without vision
        T->>T: Windows OCR fallback
    end
    T->>T: should_research(text) / should_think(text)
    opt research route
        T->>T: DuckDuckGo Lite fetch (5 snippets)
    end
    T->>D: history(60 msgs / 9000 chars)
    T->>D: relevant memories + latest summary
    T->>P: build(system + tools + context)
    T->>L: stream_chat(messages, think)
    loop streaming
        L-->>W: token signal (rendered every 70 ms)
    end
    alt model requested tools
        L->>L: append assistant tool_calls
        L->>S: authorize(name, args)
        alt denied / confirmation refused
            S-->>L: Denied
        else allowed
            S->>H: run handler
            H-->>S: result
            S->>D: audit row
        end
        L->>L: append role=tool observation
        L->>L: call model again (max 5 rounds)
    end
    L-->>T: final text
    T-->>W: done signal
    W->>D: add_message(assistant, final text)
    W->>W: re-render, refresh sessions, maybe summarize
    W->>W: speak reply (optional TTS)
```

Key properties:

- Only the **final assistant text** is persisted. Intermediate tool calls and observations live only
  in the local `messages` list of that turn.
- Streaming tokens go straight from the worker to the Qt thread via `token`; the web view is fully
  re-rendered on a 70 ms timer.
- Tool calls are authorized inside the worker thread. A confirmation dialog is marshalled to the UI
  with a blocking `Event.wait()` (no timeout).
- `Cancel` sets one `threading.Event`; it is checked per streamed chunk and before each tool call, so a
  tool that is already running or a model that is still loading cannot be interrupted.
- If the model returns an empty reply, `_short_retry_messages()` drops history/tool rounds and retries
  once with system + last user message.

## Research route

```mermaid
flowchart LR
    Q["user question"] --> R{"should_research()<br/>regex router"}
    R -- no --> N["normal prompt"]
    R -- yes --> C{"allow_web_research?"}
    C -- no --> N
    C -- yes --> Qc["clean query<br/>(strip 'can you search')"]
    Qc --> Cache{"cached < 10 min?"}
    Cache -- yes --> Prompt["system prompt:<br/>WEB RESEARCH<br/>untrusted data"]
    Cache -- no --> DDG["DuckDuckGo Lite<br/>1 request · 5 results · 8 s"]
    DDG --> Parse["HTMLParser on<br/>a.result-link / .result-snippet"]
    Parse --> Prompt
    DDG -. failure .-> Honest["honest 'could not verify' text"]
    Honest --> Prompt
    N --> LLM["LLM.stream_chat"]
    Prompt --> LLM
```

## F. Multimodal flow

```mermaid
flowchart TD
    subgraph IN["Inputs"]
        TXT["Text / files"]
        IMGIN["Attached images"]
        SCREEN["Screen capture<br/>(screenshot hotkey)"]
        MIC["Microphone<br/>STT or wake word"]
    end

    subgraph PRE["Pre-processing"]
        PARSE["attachments.py<br/>PDF · DOCX · XLSX · text · downscale"]
        VIS["vision.describe_images<br/>qwen2.5vl:3b (max 3)"]
        OCR["Windows OCR<br/>fallback"]
        STT["faster-whisper<br/>CPU int8"]
    end

    subgraph CORE["Conversation core"]
        PROMPT["persona.build"]
        LLM["stream_chat · tool loop"]
    end

    subgraph OUT["Outputs"]
        TEXT["Markdown reply<br/>KaTeX · Mermaid"]
        TTS["Piper / SAPI<br/>sentence-by-sentence"]
        ACT["Screen-control action<br/>UIA · SendInput"]
        AUDIO["avatar expression<br/>+ spoken audio"]
    end

    TXT --> PARSE --> PROMPT
    IMGIN --> VIS --> PROMPT
    SCREEN --> OCR --> PROMPT
    SCREEN --> VIS
    MIC --> STT --> PROMPT
    PROMPT --> LLM
    LLM --> TEXT --> TTS --> AUDIO
    LLM --> ACT -->|"tool result"| TEXT
    TEXT --> AUDIO
```

Notes:

- The chat model is text-only; images are converted to a description by a separate vision model first.
- OCR and vision are complementary, not equivalent: OCR is used only when vision is unavailable and the
  image came from the screen.
- Screen-control actions are single confirmed steps: UI Automation resolves a named control or
  `windows/input.py` injects one bounded key/mouse event, and the tool result reports what was sent.
  There is no continuous capture, background automation, or image generation.
- Voice input never reaches Ollama during wake-word monitoring; only the final transcript is sent.

## Data stores

| Store | Location | Written by | Read by | Retention |
|---|---|---|---|---|
| `messages` | SQLite | `db.add_message` (user + final assistant) | session list, prompt history | until user clears chat/history |
| `summaries` | SQLite | `memory.summarizer` | prompt assembly (latest only) | accumulates; not pruned |
| `memories` | SQLite | `MemoryManager`, suggestions | retrieval (max 8 per turn) | until deleted |
| `actions` | SQLite | `security.audit` | Activity pane / dashboard | last 50 shown |
| `config.json` | `%USERPROFILE%\.himari` | settings UI at close, config APIs | all subsystems | persistent |
| Logs | `%USERPROFILE%\.himari\logs` | `logging_setup` | diagnostics only | 3 × 2 MB |
| Browser profile | none (fresh context per launch) | Playwright | — | discarded on close |

## Context budget (as sent to Ollama)

| Block | Cap | Source |
|---|---|---|
| System prompt + tool specs | ~10.4k chars (~2.6k tokens) | `persona.build` |
| Conversation summary | 3,000 chars | `db.summary_for_session` |
| Web research | 6,000 chars | `research.research_for_prompt` |
| Vision description | 5,000 chars | `vision.describe_images` |
| Attachment text | 10,000 chars | `attachments.attachment_text_block` |
| Recent history | 9,000 chars | `db.history` |
| Reply | model-controlled | `num_predict` default |

Ollama's `num_ctx` is configured (`ollama.context_window`, default 8192) and sent on every request.
If a prompt still overflows, Ollama keeps only a few tokens when truncating — which is why every block
above is explicitly capped.
