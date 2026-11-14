# Tool schemas and result contract

Every capability the model can invoke is declared in `himari/tools.py` and registered with risk,
permission, confirmation and verification metadata. Code: `tools.py`, `tool_schema.py`,
`tool_results.py`, `security/policies.py`, `core/capabilities.py`.

## The result contract

Tool handlers return either a plain string or a dictionary. Newer structured tools prefer dicts.

- Success: a dict without `ok: false`, or a non-empty string that does not start with a failure
  phrase.
- Failure: a dict with `ok: false` and an `error` string; `None`; an empty string; or a string that
  starts with `denied:`, `tool error:`, `permission denied`, `invalid arguments`, `unknown tool`,
  `outside the configured allowed folders`, `failed`, `could not`, `unable to`, or `cannot `.

`tool_results.classify_result(result)` returns `(succeeded, error_text)` and is used by both the
chat tool loop and the executor, so a tool reporting failure is never counted as success.
`tool_results.as_text(result)` JSON-encodes dict/list results for prompts and logs without losing
structure.

Handlers should not raise for expected failures; they return `{"ok": False, "error": "..."}`.
The executor still catches unexpected exceptions and reports them as failed steps.

### Recommended dict shape

```json
{
  "ok": true,
  "verified": true,
  "error": "",
  "...": "tool-specific fields"
}
```

- `ok` is the machine verdict; omit it only for generic read results where presence of the payload
  is the observation.
- `verified` is used by media playback; `verified: true` is the only thing that lets the persona say
  a song is playing.
- `error` is a user-readable sentence, never a stack trace.
- Optional `retry_safe` and `alternatives` guide recovery. Mutating tools must set
  `retry_safe: false` when they cannot prove the action did not execute.

## Argument validation

Both paths validate through `tool_schema.validate_arguments(parameters, arguments)` before any
handler runs. Validation is fail-closed for declared properties:

- arguments must be an object;
- every `required` key must be present;
- when the schema declares properties, unexpected keys are rejected (typos cannot be silently
  ignored);
- declared types are checked (`string`, `integer`, `number`, `boolean`, `array`, `object`; booleans
  are not accepted as integers);
- `enum` values must match exactly.

Chat rejects the call and shows the model the error. The agent marks the step `invalid`, which maps
to a failed step and is never retried blindly.

## Tool inventory (51)

Risk and permission come from `security/policies.py`; `—` in the permission column means no
permission toggle (always allowed, still audited). "Mutates" means the tool changes desktop, disk,
calendar or playback state.

The `browser_*` tools drive Himari's own isolated, signed-out Chrome window. They are opt-in in a
second sense as well: the capability registry removes them from a request's tool list unless the
request explicitly names Himari's browser or its tabs, so ordinary open, show, watch, and play
requests use `open_url`/`open_first_result` in the user's signed-in default browser.

| Tool | Category | Risk | Permission | Mutates |
|---|---|---|---|---|
| `active_window` | system | read | allow_active_window | no |
| `app_registry` | app | read | — | no |
| `browser_close` | browser | low | allow_browser_automation | yes |
| `browser_open` | browser | low | allow_browser_automation | yes |
| `browser_open_result` | browser | low | allow_browser_automation | yes |
| `browser_read` | browser | read | allow_browser_automation | no |
| `browser_search` | browser | low | allow_browser_automation | yes |
| `browser_tabs` | browser | medium | allow_browser_automation | yes |
| `calendar_create` | calendar | medium | — | yes |
| `calendar_delete` | calendar | medium | — | yes |
| `calendar_export` | calendar | low | — | yes |
| `calendar_list` | calendar | read | — | no |
| `capture_screen_text` | screen | medium | allow_screen_capture | no |
| `click_at` | screen | high | allow_screen_control | yes |
| `click_control` | screen | high | allow_screen_control | yes |
| `close_app` | app | medium | allow_open_app | yes |
| `find_app` | app | read | — | no |
| `find_video` | research | read | allow_web_research | no |
| `focus_window` | app | medium | allow_open_app | yes |
| `inspect_app` | app | read | — | no |
| `installed_apps` | app | read | — | no |
| `launch_game` | app | low | allow_open_app | yes |
| `list_controls` | screen | read | allow_screen_control | no |
| `list_project_files` | development | read | allow_read_file | no |
| `list_windows` | app | read | — | no |
| `media_control` | music | low | allow_media_control | yes |
| `now_playing` | music | read | — | no |
| `open_app` | app | low | allow_open_app | yes |
| `open_first_result` | browser | low | allow_open_url | yes |
| `open_project` | development | high | — | yes |
| `open_url` | browser | low | allow_open_url | yes |
| `open_video` | research | low | allow_open_url | yes |
| `play_music` | music | low | allow_open_app | yes |
| `press_keys` | screen | high | allow_screen_control | yes |
| `read_file` | file | read | allow_read_file | no |
| `research_web` | research | low | allow_web_research | no |
| `run_command` | system | high | allow_run_command | yes |
| `running_processes` | system | read | — | no |
| `scan_large_files` | file | read | allow_read_file | yes |
| `screen_scene` | screen | medium | allow_screen_capture | no |
| `scroll_screen` | screen | high | allow_screen_control | yes |
| `search_code` | development | read | allow_read_file | yes |
| `search_web` | browser | low | allow_open_url | yes |
| `search_youtube` | browser | low | allow_open_url | yes |
| `set_control_text` | screen | high | allow_screen_control | yes |
| `set_volume` | system | low | allow_volume | yes |
| `spotify_search` | music | read | — | no |
| `type_text` | screen | high | allow_screen_control | yes |
| `weather_forecast` | weather | read | — | no |
| `write_desktop_file` | file | medium | allow_write_file | yes |
| `write_file` | file | medium | allow_write_file | yes |

Confirmation (from `security/policies.py`): `close_app`, `calendar_create`, `calendar_delete`,
`list_project_files`, `search_code`, `read_file`, `scan_large_files`, `write_file`, `write_desktop_file`,
`capture_screen_text`, `screen_scene`, `focus_window`, all screen-input tools and `run_command`.
`press_keys` and `browser_submit` never receive a session-wide grant; `browser_submit` is reserved
for the browser interaction layer and is not part of the 51 registered chat tools.

## Detailed schemas — daily-use core

### Music

| Tool | Arguments | Returns |
|---|---|---|
| `play_music` | `query` (string, required), `artist` (string, optional) | verified playback or an explicit failure |
| `spotify_search` | `query` (string, required), `artist` (string), `limit` (integer 1–20, default 5) | candidate tracks; needs Web API credentials |
| `now_playing` | none | active Windows media session |
| `media_control` | `action` enum `play_pause` / `next` / `previous` / `stop` | media session state after the command |

`play_music` behavior:

1. refuse cleanly when Spotify is not installed;
2. start Spotify if needed and verify a process appears;
3. with credentials, search the Web API, open the `spotify:track:<id>` link, and poll the Windows
   media session for up to 18 s;
4. without credentials, open `spotify:search:<query>`; optional UIA selection only when the tool was
   asked to allow it; otherwise ask the user to pick the result.

Verified success:

```json
{
  "ok": true,
  "verified": true,
  "method": "spotify-api",
  "track": {"id": "<spotify-track-id>", "uri": "spotify:track:<spotify-track-id>",
             "title": "Blinding Lights", "artist": "The Weeknd",
             "album": "After Hours", "duration_seconds": 200.0, "popularity": 90},
  "now_playing": {"app": "Spotify", "title": "Blinding Lights", "artist": "The Weeknd",
                   "album": "After Hours", "playing": true,
                   "position_seconds": 1.2, "duration_seconds": 200.0, "label": "Spotify"},
  "message": "Spotify is playing 'Blinding Lights' by The Weeknd. Verified from the Windows media session."
}
```

Honest failure (the app opened the track but the media session did not confirm it):

```json
{
  "ok": false,
  "verified": false,
  "method": "spotify-api",
  "track": {"title": "Blinding Lights", "artist": "The Weeknd", "uri": "spotify:track:..."},
  "now_playing": null,
  "error": "Spotify opened 'Blinding Lights' by The Weeknd, but the Windows media session did not confirm playback. The track may still be loading, or Spotify may be paused.",
  "retry_safe": false,
  "alternatives": ["now_playing", "media_control"]
}
```

### Weather

`weather_forecast(location: string | null, days: integer 1–14 = 3)`. Omitting `location` uses the
configured city, then automatic IP-based detection. Data is cached for 10 minutes per
location/days/units tuple. Failures return `{"ok": false, "error": "..."}`; weather is never
answered from memory.

```json
{
  "ok": true,
  "location": {"name": "Paris", "latitude": 48.8534, "longitude": 2.3488,
                "timezone": "Europe/Paris", "country": "France"},
  "timezone": "Europe/Paris",
  "units": "metric",
  "temperature_unit": "°C",
  "wind_unit": "km/h",
  "current": {"condition": "Partly cloudy", "code": 2, "temperature": "11.4",
               "feels_like": "10.1", "humidity": 76, "precipitation": "0.00",
               "wind_speed": "8.2", "is_day": true, "time": "2026-11-13T12:00"},
  "daily": [{"date": "2026-11-13", "weekday": "Friday", "condition": "Partly cloudy",
              "code": 2, "high": "13.0", "low": "7.2", "rain_probability": 10,
              "sunrise": "...", "sunset": "..."}],
  "source": "Open-Meteo",
  "fetched_at": "2026-11-13T12:04:11+01:00",
  "formatted": "…human-readable forecast…"
}
```

### Calendar

| Tool | Arguments | Effect |
|---|---|---|
| `calendar_list` | `days` (integer, default 7), `start`, `end` (strings; `start` accepts "tomorrow", ISO dates/times) | read-only |
| `calendar_create` | `title` (required), `start` (required; "tomorrow at 12:00" or ISO), `duration_minutes` (integer 5–1440, default 60), `location`, `notes`, `attendees` | writes one local event; confirmed |
| `calendar_delete` | `event_id` (required, from `calendar_list`) | deletes one local event; confirmed |
| `calendar_export` | `path` (optional; default under the Himari data folder) | writes an `.ics` file; verified on disk |

`calendar_create` returns the stored event and any overlapping events:

```json
{
  "ok": true,
  "event": {"id": "9f1c2a7b4d10", "uid": "himari-9f1c2a7b4d10@local",
             "title": "Project sync", "start": "2026-11-14T12:00",
             "end": "2026-11-14T13:00", "duration_minutes": 60,
             "location": "", "notes": "", "attendees": "",
             "when": "Saturday 14 November 2026 at 12:00"},
  "conflicts": []
}
```

Verification re-reads the event by id after creation and confirms absence after deletion. The
calendar is local: nothing is sent to a cloud calendar service.

### Application discovery

| Tool | Arguments | Returns |
|---|---|---|
| `find_app` | `name` (required) | text list of installed matches |
| `app_registry` | `query` (optional), `limit` (1–100, default 25) | `{ok, count, applications:[…]}` with running/support state |
| `inspect_app` | `name` or alias (required) | one resolved app, windows and support level, or ambiguity candidates |
| `installed_apps` | none | text listing of discovered applications |
| `open_app` | `name` (required) | verified launch/focus message |
| `focus_window` | `name` (required) | focuses an existing window |
| `list_windows` | optional filters | visible top-level windows |

`inspect_app` success:

```json
{
  "ok": true,
  "application": "Spotify",
  "target": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
  "source": "store",
  "running": true,
  "windows": ["Spotify Premium"],
  "support": "integrated",
  "note": "Integrated means a dedicated integration exists. Inspectable means a window can be read. Interactable is verified per control through list_controls, not assumed from installation."
}
```

Ambiguity is an explicit result, never a silent pick:

```json
{"ok": false, "ambiguous": true, "error": "2 applications match 'code'.", "candidates": ["Visual Studio Code", "Code::Blocks"]}
```

See [APP_DISCOVERY.md](APP_DISCOVERY.md) for discovery sources and support levels.

## Verification coverage

Implemented in `agent/verification.py` (details in [EXECUTION_ENGINE.md](EXECUTION_ENGINE.md)):

- **media**: `play_music` (claimed verification or live media session), `now_playing`,
  `media_control` (partial);
- **data**: `weather_forecast` (structured days), `calendar_list` (events list), `spotify_search`
  (track count);
- **database**: `calendar_create` (event exists), `calendar_delete` (event absent);
- **disk**: `write_file`, `write_desktop_file`, `calendar_export`;
- **unverifiable by design**: discovery/listing tools and any tool without an independent
  observation. These are reported as unverified, not as success with proof.

`open_app` verifies its own launch inside the handler (process/window snapshot before and after),
but the generic verifier cannot independently re-check every launch mode; its result is treated as
the observation.

## Storage and privacy

- `spotify.client_secret` is stored in `config.json`, used only to obtain a Client Credentials
  token, and excluded from prompts. Audit arguments are redacted by key and by secret-like value.
- Web API tokens are cached under the Himari data directory with an expiry; no refresh token is
  stored because the Client Credentials flow does not issue one.
- Weather uses only the configured/queried place name and coordinates.
- Calendar entries stay in the local SQLite database.

## Adding a tool

1. Add the handler and OpenAI-style `spec` to `tools.TOOLS`.
2. Add the name to `TOOL_RISKS` and, when a permission applies, `TOOL_PERMISSIONS` in
   `security/policies.py`. Unknown tools are denied.
3. Add confirmation to `CONFIRMATION_TOOLS` if the action is consequential.
4. Add category/tags/verification metadata to `CAPABILITY_META` so selection and prompts include it.
5. Return the dict contract for anything with a verifiable outcome.
6. Add a verification branch if the application can observe the outcome.
7. Add tests for schema validation, success, failure and (where applicable) verification.
