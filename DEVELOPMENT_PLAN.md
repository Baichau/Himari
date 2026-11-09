# Himari development plan

## Current architecture

- `himari/ui.py` owns the PySide6 application window, settings, activity list,
  tray behavior, microphone controls, and worker-thread orchestration.
- `himari/llm.py` streams local Ollama chat and executes a bounded set of
  dedicated tools.
- `himari/tools.py` contains local Windows integrations, path validation,
  permission checks, confirmation metadata, and activity logging.
- `himari/voice.py` provides local Faster-Whisper recognition, microphone
  capture, and Piper/Windows speech output.
- `himari/screen.py` captures a requested screen once and extracts text with
  Windows OCR; screenshot images are closed after OCR.
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

## Follow-up milestones

- Add generated conversation summaries that use only the configured local
  Ollama endpoint.
- Add searchable conversation history and optional local embedding retrieval;
  retain clearly labeled lexical search when embeddings are unavailable.
- Add active-window context only as an explicit, permission-gated request.
- Add screenshot preview and optional local vision-model analysis with image
  resizing and explicit confirmation.
- Expand the permission UI and task progress/cancellation controls as their
  dedicated tools are implemented and covered by tests.
- Validate Windows hardware paths (microphone, media sessions, OCR, tray, and
  packaged executable) on Windows with the relevant devices and models present.
