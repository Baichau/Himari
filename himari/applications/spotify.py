"""Reliable Spotify search and playback.

Resolution order:
1. Spotify Web API (client credentials) resolves a track and returns its URI.
2. Without credentials, a public web search finds the exact
   ``open.spotify.com/track/<id>`` page, which gives the same URI.
3. The ``spotify:track:<id>`` deep link makes the installed desktop app play it.
4. Windows media session confirms the requested track is actually playing.
5. If resolution fails, Himari opens focused search and, when screen control is
   allowed, selects the best matching row through UI Automation.

Nothing is claimed as playing unless the media session confirms it.
"""

import base64
import difflib
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

import httpx

from ..config import APP_DIR, load as load_config
from ..windows import media_session

log = logging.getLogger("himari.applications.spotify")

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
HTTP_TIMEOUT_SECONDS = 10.0
TOKEN_SAFETY_SECONDS = 60
VERIFY_TIMEOUT_SECONDS = 18.0
VERIFY_POLL_SECONDS = 0.7
STORE_APP_ID = "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"
APP_HINT = "spotify"
_NOISE_WORDS = (
    "remaster",
    "remastered",
    "live",
    "karaoke",
    "instrumental",
    "cover",
    "sped up",
    "slowed",
    "nightcore",
    "radio edit",
)


class SpotifyError(RuntimeError):
    pass


class SpotifyAuthError(SpotifyError):
    pass


class SpotifyUnavailableError(SpotifyError):
    pass


@dataclass(frozen=True)
class Track:
    id: str
    uri: str
    name: str
    artists: tuple
    album: str = ""
    duration_ms: int = 0
    popularity: int = 0

    @property
    def artist_text(self):
        return ", ".join(self.artists)

    def to_dict(self):
        return {
            "id": self.id,
            "uri": self.uri,
            "title": self.name,
            "artist": self.artist_text,
            "album": self.album,
            "duration_seconds": round(self.duration_ms / 1000, 1),
            "popularity": self.popularity,
        }


def _config():
    config = load_config()
    return config.get("spotify", {}) if isinstance(config, dict) else {}


def _permissions():
    config = load_config()
    return config.get("permissions", {}) if isinstance(config, dict) else {}


def _normalized(value):
    text = str(value or "").casefold()
    text = re.sub(r"\((?:feat|ft|with)[^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(left, right):
    left_text = _normalized(left)
    right_text = _normalized(right)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    if left_text in right_text or right_text in left_text:
        return 0.9
    return difflib.SequenceMatcher(None, left_text, right_text).ratio()


def _has_noise(value):
    text = _normalized(value)
    return any(word in text for word in _NOISE_WORDS)


def installed():
    if os.name != "nt":
        return False
    candidates = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WindowsApps/Spotify.exe",
        Path(os.environ.get("APPDATA", "")) / "Spotify/Spotify.exe",
    )
    if any(candidate.is_file() for candidate in candidates):
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\spotify"):
            return True
    except Exception:
        return False


def running():
    try:
        from ..windows import running_processes

        return any(
            process.name.casefold() == "spotify.exe"
            for process in running_processes()
        )
    except Exception:
        return False


def _has_credentials():
    cfg = _config()
    return bool(str(cfg.get("client_id") or "").strip()) and bool(
        str(cfg.get("client_secret") or "").strip()
    )


def status():
    cfg = _config()
    return {
        "installed": installed(),
        "running": running(),
        "api_ready": _has_credentials(),
        "market": str(cfg.get("market") or "").strip() or "auto",
        "media_session": media_session.available(),
    }


def _token_path():
    return APP_DIR / "spotify_token.json"


def _cached_token():
    try:
        data = json.loads(_token_path().read_text(encoding="utf-8"))
        if float(data.get("expires_at", 0)) - time.time() > TOKEN_SAFETY_SECONDS:
            return str(data.get("access_token") or "")
    except (OSError, ValueError, TypeError):
        return ""
    return ""


def _save_token(access_token, expires_in):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": access_token,
            "expires_at": time.time() + max(60, int(expires_in)),
        }
        temp = _token_path().with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp, _token_path())
    except OSError as exc:
        log.debug("Could not cache the Spotify token: %s", exc)


def _access_token(force=False):
    if not force:
        cached = _cached_token()
        if cached:
            return cached
    cfg = _config()
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise SpotifyAuthError(
            "Spotify API credentials are not configured. Add a Spotify Developer "
            "client ID and secret in Settings, or use local search fallback."
        )
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {basic}"},
            )
    except httpx.HTTPError as exc:
        raise SpotifyError(f"Could not reach Spotify: {exc}") from exc
    if response.status_code != 200:
        raise SpotifyAuthError(
            "Spotify rejected the configured credentials "
            f"(HTTP {response.status_code}). Check the client ID and secret."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SpotifyError("Spotify returned an unreadable token response.") from exc
    token = str(payload.get("access_token") or "")
    if not token:
        raise SpotifyAuthError("Spotify did not return an access token.")
    _save_token(token, payload.get("expires_in", 3600))
    return token


def search_tracks(query, artist=None, limit=8):
    """Search Spotify for tracks; returns an ordered list of candidates."""
    query = str(query or "").strip()
    artist = str(artist or "").strip()
    if not query and not artist:
        raise SpotifyError("Tell me which song or artist to look for.")
    term = query or artist
    q = term
    if query and artist:
        q = f'track:"{query}" artist:"{artist}"'
    elif artist:
        q = f'artist:"{artist}"'
    cfg = _config()
    params = {"q": q, "type": "track", "limit": max(1, min(int(limit), 20))}
    market = str(cfg.get("market") or "").strip()
    if market:
        params["market"] = market

    for attempt in range(2):
        token = _access_token(force=attempt > 0)
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = client.get(
                    SEARCH_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise SpotifyError(f"Could not reach Spotify search: {exc}") from exc
        if response.status_code == 401 and attempt == 0:
            continue
        if response.status_code != 200:
            raise SpotifyError(
                f"Spotify search failed (HTTP {response.status_code})."
            )
        break

    try:
        items = (response.json().get("tracks") or {}).get("items") or []
    except ValueError as exc:
        raise SpotifyError("Spotify returned an unreadable search response.") from exc
    tracks = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        tracks.append(
            Track(
                id=str(item["id"]),
                uri=str(item.get("uri") or f"spotify:track:{item['id']}"),
                name=str(item.get("name") or ""),
                artists=tuple(
                    str(artist_item.get("name") or "")
                    for artist_item in item.get("artists") or []
                    if isinstance(artist_item, dict)
                ),
                album=str((item.get("album") or {}).get("name") or ""),
                duration_ms=int(item.get("duration_ms") or 0),
                popularity=int(item.get("popularity") or 0),
            )
        )
    return rank_tracks(tracks, query or artist, artist)


def rank_tracks(tracks, query, artist=None):
    """Score candidates so duplicates, remixes and covers do not win."""
    wanted_artist = str(artist or "").strip()
    query_noise = _has_noise(query)
    scored = []
    for track in tracks:
        title_score = _similarity(query, track.name)
        artist_score = (
            max((_similarity(wanted_artist, name) for name in track.artists), default=0.0)
            if wanted_artist
            else 1.0
        )
        score = title_score * 0.6 + artist_score * 0.3 + (track.popularity / 100.0) * 0.1
        if wanted_artist and artist_score < 0.45:
            score -= 0.45
        if _has_noise(track.name) and not query_noise:
            score -= 0.25
        scored.append((round(score, 4), track))
    scored.sort(key=lambda item: (-item[0], -item[1].popularity))
    ranked = [track for score, track in scored if score > 0]
    return ranked or ([scored[0][1]] if scored else [])


def resolve_track(query, artist=None):
    candidates = search_tracks(query, artist=artist)
    if not candidates:
        raise SpotifyError(
            f"Spotify did not return a track for '{query or artist}'. "
            "Nothing was started."
        )
    return candidates[0], candidates[1:5]


# ---- Credential-free resolution -------------------------------------------

PUBLIC_SEARCH_URL = "https://html.duckduckgo.com/html/"
PUBLIC_CACHE_SECONDS = 600
_PUBLIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TRACK_LINK = re.compile(
    r"open\.spotify\.com(?:%2F|/)track(?:%2F|/)([A-Za-z0-9]{16,})", re.I
)
_RESULT_ANCHOR = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S
)
_RESULT_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_TAG = re.compile(r"<[^>]+>")
_public_cache = {}


def _plain(fragment):
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", str(fragment or "")))).strip()


def _candidate_label(title):
    label = re.sub(r"\s*\|\s*Spotify\s*$", "", _plain(title), flags=re.I)
    label = re.split(r"\s+-\s+(?:Song|Listen)", label, maxsplit=1)[0]
    return label.strip() or "Spotify track"


def _parse_public_tracks(document, query, artist):
    candidates = []
    seen = set()
    for match in _RESULT_ANCHOR.finditer(document):
        href, title = match.group(1), match.group(2)
        snippet_match = _RESULT_SNIPPET.search(
            document[match.end():match.end() + 2000]
        )
        snippet = _plain(snippet_match.group(1)) if snippet_match else ""
        haystack = " ".join((href, title, snippet))
        label = _candidate_label(title)
        for track_id in _TRACK_LINK.findall(haystack):
            if track_id in seen:
                continue
            seen.add(track_id)
            candidates.append((track_id, label))
    if not candidates:
        for match in _TRACK_LINK.finditer(document):
            track_id = match.group(1)
            if track_id in seen:
                continue
            seen.add(track_id)
            context = _plain(document[max(0, match.start() - 600):match.start()])
            candidates.append((track_id, _candidate_label(context[-220:])))
    wanted_artist = _normalized(artist)
    scored = []
    for track_id, label in candidates:
        normalized = _normalized(label)
        title_score = _similarity(query, label)
        artist_score = (
            1.0
            if wanted_artist and wanted_artist in normalized
            else (0.0 if wanted_artist else 1.0)
        )
        score = title_score * 0.65 + artist_score * 0.35
        if _has_noise(label) and not _has_noise(query):
            score -= 0.2
        if score > 0:
            scored.append((round(score, 4), track_id, label))
    scored.sort(key=lambda item: -item[0])
    return scored


def _searx_document(base_url, search_query):
    """Render a configured SearXNG JSON response as simple result markup."""
    try:
        with httpx.Client(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": _PUBLIC_UA, "Accept": "application/json"},
        ) as client:
            response = client.get(
                f"{base_url}/search",
                params={"q": search_query, "format": "json"},
            )
        if response.status_code != 200:
            return ""
        results = response.json().get("results") or []
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        log.info("SearXNG track lookup failed: %s", exc)
        return ""
    blocks = []
    for result in results[:8]:
        if not isinstance(result, dict):
            continue
        link = str(result.get("url") or "")
        title = html.escape(str(result.get("title") or ""), quote=True)
        snippet = html.escape(str(result.get("content") or ""), quote=True)
        blocks.append(
            f'<a class="result__a" href="{html.escape(link, quote=True)}">{title}</a>'
            f'<a class="result__snippet">{snippet}</a>'
        )
    return "\n".join(blocks)


def public_resolve_track(query, artist=None, limit=3):
    """Find an exact Spotify track URI without API credentials.

    Uses the same DuckDuckGo HTML search the local research pipeline already
    relies on, and only accepts links that point at a real track page.
    """
    query = str(query or "").strip()
    artist = str(artist or "").strip()
    term = " ".join(part for part in (query, artist) if part).strip()
    if not term:
        raise SpotifyError("Tell me which song to play.")
    key = term.casefold()
    cached = _public_cache.get(key)
    if cached and time.time() - cached[0] < PUBLIC_CACHE_SECONDS:
        tracks, error = cached[1], cached[2]
        if tracks:
            return tracks[0], tracks[1:limit]
        raise SpotifyError(error or "No Spotify track page was found.")
    search_query = f"site:open.spotify.com/track {term}"
    document = ""
    searx_url = str(
        (load_config().get("research") or {}).get("searx_url") or ""
    ).strip()
    if searx_url.startswith(("http://", "https://")):
        document = _searx_document(searx_url.rstrip("/"), search_query)
    if not document:
        url = f"{PUBLIC_SEARCH_URL}?{quote(search_query)}"
        try:
            with httpx.Client(
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": _PUBLIC_UA, "Accept": "text/html"},
            ) as client:
                response = client.get(url)
                if response.status_code == 200:
                    document = response.text
        except httpx.HTTPError as exc:
            log.info("Spotify public search failed: %s", exc)
    ranked = _parse_public_tracks(document, query or term, artist or None) if document else []
    if not ranked:
        error = (
            "Spotify API credentials are not configured and the public search did "
            "not return a usable track link."
        )
        _public_cache[key] = (time.time(), [], error)
        raise SpotifyError(error)
    tracks = [
        Track(
            id=track_id,
            uri=f"spotify:track:{track_id}",
            name=query or label,
            artists=(artist,) if artist else (),
            album="",
        )
        for _, track_id, label in ranked
    ]
    _public_cache[key] = (time.time(), tracks, "")
    return tracks[0], tracks[1:limit]


def _spotify_windows():
    try:
        from ..windows import list_windows
    except Exception as exc:
        log.debug("Window discovery unavailable: %s", exc)
        return []
    try:
        return [
            window
            for window in list_windows()
            if (window.process_name or "").casefold() == "spotify.exe"
            and str(window.title or "").strip()
        ]
    except Exception as exc:
        log.debug("Could not list Spotify windows: %s", exc)
        return []


def focus_app(timeout=4.0):
    """Bring Spotify to the foreground; returns True only when Windows agrees."""
    deadline = time.time() + max(0.5, timeout)
    try:
        from ..windows import focus_window
    except Exception:
        return False
    while time.time() < deadline:
        for window in _spotify_windows():
            try:
                if focus_window(window.hwnd):
                    return True
            except Exception as exc:
                log.debug("Could not focus Spotify: %s", exc)
        time.sleep(0.4)
    return False


def _open_uri(uri):
    if os.name != "nt":
        raise SpotifyUnavailableError("Spotify deep links only work on Windows.")
    try:
        os.startfile(uri)
        return True
    except OSError as exc:
        log.warning("Spotify deep link failed: %s", exc)
        return False


def ensure_running(timeout=12.0):
    if running():
        return True
    if not installed():
        raise SpotifyUnavailableError(
            "Spotify is not installed, so no track can be played."
        )
    if not _open_uri("spotify:"):
        try:
            os.startfile(f"shell:AppsFolder\\{STORE_APP_ID}")
        except OSError as exc:
            raise SpotifyUnavailableError(
                f"Could not start Spotify: {exc}"
            ) from exc
    deadline = time.time() + timeout
    while time.time() < deadline:
        if running():
            return True
        time.sleep(0.5)
    return running()


def _track_matches(now, track):
    if now is None:
        return False
    if track is None:
        return bool(now.title)
    title_ok = _similarity(track.name, now.title) >= 0.72
    artist_ok = (
        not track.artists
        or not getattr(now, "artist", "")
        or max((_similarity(name, now.artist) for name in track.artists), default=0.0)
        >= 0.55
    )
    return title_ok and artist_ok


def wait_until_playing(track=None, timeout=VERIFY_TIMEOUT_SECONDS):
    """Poll the media session until the expected track is playing."""
    deadline = time.time() + max(1.0, timeout)
    last = None
    while time.time() < deadline:
        try:
            last = media_session.now_playing(APP_HINT)
        except media_session.MediaSessionError as exc:
            log.info("Media session unavailable while verifying: %s", exc)
        if last is not None and _track_matches(last, track):
            if last.playing:
                return True, last
            try:
                media_session.play_pause(APP_HINT)
            except media_session.MediaSessionError:
                pass
            time.sleep(1.0)
            try:
                resumed = media_session.now_playing(APP_HINT)
            except media_session.MediaSessionError:
                resumed = last
            if resumed is not None and _track_matches(resumed, track) and resumed.playing:
                return True, resumed
        time.sleep(VERIFY_POLL_SECONDS)
    return False, last


def _uia_search_and_select(query, artist, timeout=15.0):
    """Last-resort control of the Spotify window. Requires screen control."""
    if not _permissions().get("allow_screen_control", False):
        return {
            "attempted": False,
            "reason": "Screen control is disabled in Settings.",
        }
    from ..windows import uia

    try:
        uia.focus_window("Spotify")
    except uia.ScreenControlError as exc:
        return {"attempted": False, "reason": f"Spotify window not ready: {exc}"}
    time.sleep(1.0)
    control = None
    for candidate in ("Search", "search"):
        try:
            controls = uia.list_controls("Spotify", name_filter=candidate).get("controls", [])
        except uia.ScreenControlError as exc:
            return {"attempted": False, "reason": str(exc)}
        edits = [
            item
            for item in controls
            if str(item.get("control_type", "")).casefold() == "edit"
        ]
        if edits:
            control = edits[0]
            break
    if control is None:
        return {
            "attempted": False,
            "reason": "The Spotify search field was not exposed through UI Automation.",
        }
    try:
        uia.set_control_text("Spotify", control["name"], query, control_type="Edit")
        from ..windows.input import press_keys

        press_keys("enter")
    except Exception as exc:
        return {"attempted": False, "reason": f"Could not search Spotify: {exc}"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            listing = uia.list_controls("Spotify", name_filter=query)
        except uia.ScreenControlError:
            listing = {"controls": []}
        best = None
        best_score = 0.0
        for item in listing.get("controls", []):
            name = str(item.get("name") or "")
            score = _similarity(query, name)
            if artist:
                score = max(score, _similarity(f"{query} {artist}", name))
            if score > best_score:
                best, best_score = item, score
        if best is not None and best_score >= 0.55:
            try:
                uia.activate_control("Spotify", best["name"], double=True)
                return {
                    "attempted": True,
                    "selected": best["name"],
                    "score": round(best_score, 3),
                }
            except Exception as exc:
                return {"attempted": True, "reason": f"Could not select the result: {exc}"}
        time.sleep(1.0)
    return {
        "attempted": True,
        "reason": "No matching result row was exposed through UI Automation.",
    }


def play(query, artist=None, allow_ui=False):
    """Play one specific track and verify it, or report exactly what failed."""
    query = str(query or "").strip()
    artist = str(artist or "").strip()
    if not query and not artist:
        return {
            "ok": False,
            "error": "Tell me the song or artist to play.",
        }
    if not installed():
        return {
            "ok": False,
            "error": (
                "Spotify is not installed, so the requested track cannot be played. "
                "Nothing was started."
            ),
            "alternatives": ["open_app", "browser_open"],
        }
    try:
        if not ensure_running():
            return {
                "ok": False,
                "error": "Spotify was started but no Spotify process appeared.",
                "retry_safe": True,
            }
    except SpotifyUnavailableError as exc:
        return {"ok": False, "error": str(exc)}

    focus_app(timeout=3.0)
    track = None
    api_error = ""
    method = "spotify-api"
    if _has_credentials():
        try:
            track, others = resolve_track(query, artist=artist)
        except SpotifyAuthError as exc:
            api_error = str(exc)
        except SpotifyError as exc:
            api_error = str(exc)
    if track is None:
        method = "public-search"
        try:
            track, others = public_resolve_track(query, artist=artist)
        except SpotifyError as exc:
            api_error = api_error or str(exc)
    if track is not None:
        if not _open_uri(track.uri):
            return {
                "ok": False,
                "error": (
                    f"Spotify found '{track.name}'"
                    + (f" by {track.artist_text}" if track.artist_text else "")
                    + " but the desktop app did not accept the playback link."
                ),
                "track": track.to_dict(),
            }
        focus_app(timeout=3.0)
        verified, observed = wait_until_playing(track)
        if verified:
            return {
                "ok": True,
                "verified": True,
                "method": method,
                "track": track.to_dict(),
                "now_playing": observed.to_dict() if observed else None,
                "message": (
                    f"Spotify is playing '{observed.label if observed else track.name}'. "
                    "Verified from the Windows media session."
                ),
            }
        return {
            "ok": False,
            "verified": False,
            "method": method,
            "track": track.to_dict(),
            "now_playing": observed.to_dict() if observed else None,
            "error": (
                f"Spotify opened '{track.name}'"
                + (f" by {track.artist_text}" if track.artist_text else "")
                + ", but the Windows media session did not confirm playback. "
                "The track may still be loading, or Spotify may be paused."
            ),
            "retry_safe": False,
            "alternatives": ["now_playing", "media_control"],
        }

    search_uri = f"spotify:search:{quote(query or artist)}"
    if not _open_uri(search_uri):
        return {
            "ok": False,
            "error": "Spotify could not open its search view.",
            "api_error": api_error,
        }
    focus_app(timeout=2.5)
    if allow_ui:
        ui = _uia_search_and_select(query, artist)
    else:
        ui = {
            "attempted": False,
            "reason": "Local search fallback was not requested.",
        }
    selected = str((ui or {}).get("selected") or "").strip()
    if not selected:
        return {
            "ok": False,
            "verified": False,
            "method": "local-search",
            "api_error": api_error,
            "ui_automation": ui,
            "error": (
                "Spotify search is open, but no track was selected or confirmed. "
                "Select the result in Spotify, or add Spotify API credentials in "
                "Settings so Himari can choose the exact track."
            ),
            "retry_safe": False,
            "alternatives": ["now_playing", "play_music"],
        }
    expected = Track(
        id="",
        uri="",
        name=query or selected,
        artists=(artist,) if artist else (),
    )
    verified, observed = wait_until_playing(expected, timeout=8.0)
    if verified:
        return {
            "ok": True,
            "verified": True,
            "method": "local-search",
            "selected": selected,
            "now_playing": observed.to_dict() if observed else None,
            "message": (
                f"Spotify is playing '{observed.label}'. "
                "Verified from the Windows media session."
            ),
        }
    return {
        "ok": False,
        "verified": False,
        "method": "local-search",
        "api_error": api_error,
        "ui_automation": ui,
        "now_playing": observed.to_dict() if observed else None,
        "error": (
            "Spotify selected a search result, but playback of the requested track "
            "is not confirmed by the Windows media session."
        ),
        "retry_safe": False,
        "alternatives": ["now_playing", "media_control"],
    }


def control(action):
    action = str(action or "").strip().casefold()
    try:
        if action in {"play_pause", "pause", "resume", "toggle"}:
            ok = media_session.play_pause(APP_HINT)
        elif action in {"next", "skip"}:
            ok = media_session.next_track(APP_HINT)
        elif action in {"previous", "back"}:
            ok = media_session.previous_track(APP_HINT)
        elif action == "stop":
            ok = media_session.stop(APP_HINT)
        else:
            return {
                "ok": False,
                "error": "Unsupported action. Use play_pause, next, previous or stop.",
            }
    except media_session.MediaSessionError as exc:
        return {"ok": False, "error": str(exc)}
    observed = None
    try:
        observed = media_session.now_playing(APP_HINT)
    except media_session.MediaSessionError:
        observed = None
    if not ok:
        return {
            "ok": False,
            "error": "Spotify or Windows refused the media command.",
            "now_playing": observed.to_dict() if observed else None,
        }
    return {
        "ok": True,
        "action": action,
        "now_playing": observed.to_dict() if observed else None,
    }


def now_playing():
    try:
        observed = media_session.now_playing(APP_HINT)
    except media_session.MediaSessionError as exc:
        return {"ok": False, "error": str(exc)}
    if observed is None:
        return {
            "ok": False,
            "error": "No Spotify media session is active, so nothing is playing.",
        }
    return {"ok": True, **observed.to_dict()}
