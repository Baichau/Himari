# Avatar assets

Himari's avatar renderer is sprite-based and accepts original transparent PNG
illustrations. No character artwork is bundled, so the app displays an explicit
placeholder until you add your own assets.

Put sprites in `%USERPROFILE%\.himari\avatar_assets` to keep them across app
updates, or in `himari\avatar_assets` when developing from source. User assets
take precedence over bundled assets. Use PNG files with transparent backgrounds;
all frames for one animation should use the same canvas size and character
position.

Supported names:

| State | Files |
|---|---|
| Idle | `idle.png`, optionally `idle_01.png`, `idle_02.png`, ... |
| Blink | `idle_blink.png` (shown briefly while idle) |
| Listening | `listening.png` |
| Thinking | `thinking.png` |
| Speaking | `speaking_01.png`, `speaking_02.png`, ... or `speaking.png` |
| Expressions | `happy.png`, `confused.png`, `sad.png`, `error.png` |

The renderer cycles multi-frame idle and speaking sprites. Speaking animation
starts and stops with Himari's TTS status; phoneme-level lip synchronization is
not available because Piper playback does not currently expose timing events.
The floating window can be dragged and resized by the app. It has no paid
renderer dependency.

A future Live2D integration should be an optional renderer behind the same
avatar state interface, loaded only when the user supplies a compatible model
and runtime. It must not be required for chat, voice, or the sprite fallback.
