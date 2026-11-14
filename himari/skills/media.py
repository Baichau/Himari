"""Media companion: read a YouTube transcript without downloading anything.

Only the public watch page and its caption track are read. Nothing is saved,
nothing plays automatically, and no API key is used.
"""

import html
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from .common import bounded_text, permission

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 3_000_000
MAX_TRANSCRIPT_CHARS = 7000
MAX_CUE_LINES = 260
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CAPTION_BLOCK = re.compile(r'"captionTracks":(\[.*?\])', re.DOTALL)
_CUE = re.compile(r"<text([^>]*)>(.*?)</text>", re.DOTALL)
_START = re.compile(r'start="([0-9.]+)"')
_DETAILS_TITLE = re.compile(
    r'"videoDetails":\{.*?"title":"((?:[^"\\]|\\.)*)"', re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")


class MediaError(RuntimeError):
    """The video or its captions could not be read."""


def video_id(value):
    """Return an 11-character video id from an id, watch URL or short URL."""
    text = str(value or "").strip()
    if not text:
        return ""
    if VIDEO_ID.match(text):
        return text
    parsed = urlparse(text)
    host = (parsed.netloc or "").casefold()
    if "youtu.be" in host:
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if VIDEO_ID.match(candidate) else ""
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        if parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
            candidate = parsed.path.strip("/").split("/")[-1]
            return candidate if VIDEO_ID.match(candidate) else ""
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        return candidate if VIDEO_ID.match(candidate) else ""
    return ""


def _http_get(url, timeout=TIMEOUT_SECONDS):
    """Fetch one public page; isolated so tests can replace it."""
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"},
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise MediaError(f"YouTube returned HTTP {response.status}.")
        return response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES].decode(
            "utf-8", errors="replace"
        )


def page_title(document):
    match = _DETAILS_TITLE.search(document or "")
    if not match:
        return ""
    try:
        return bounded_text(json.loads(f'"{match.group(1)}"'), 160)
    except ValueError:
        return bounded_text(match.group(1), 160)


def caption_url(document):
    """Return the first caption track URL, preferring English."""
    match = _CAPTION_BLOCK.search(document or "")
    if not match:
        return ""
    try:
        tracks = json.loads(match.group(1))
    except ValueError:
        return ""
    if not isinstance(tracks, list):
        return ""
    readable = [track for track in tracks if isinstance(track, dict) and track.get("baseUrl")]
    if not readable:
        return ""
    for track in readable:
        if str(track.get("languageCode") or "").casefold().startswith("en"):
            return str(track["baseUrl"])
    return str(readable[0]["baseUrl"])


def _clock(seconds):
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def parse_timedtext(document):
    """Turn a timedtext XML document into ``[mm:ss] line`` cues."""
    cues = []
    for attrs, body in _CUE.findall(document or ""):
        start = _START.search(attrs)
        text = html.unescape(_TAG.sub("", body))
        text = " ".join(text.split())
        if not text:
            continue
        cues.append(f"[{_clock(start.group(1) if start else 0)}] {text}")
        if len(cues) >= MAX_CUE_LINES:
            break
    return cues


def _resolve(query):
    requested = str(query or "").strip()
    if not requested:
        raise MediaError("Tell me which video to read.")
    direct = video_id(requested)
    if direct:
        return direct, ""
    from ..youtube import search_videos

    videos, error = search_videos(requested, 1)
    if error:
        raise MediaError(error)
    if not videos:
        raise MediaError("No matching video was found.")
    found = video_id(videos[0].get("url"))
    if not found:
        raise MediaError("The first search result had no readable video link.")
    return found, str(videos[0].get("title") or "")


def youtube_transcript(query):
    """Read the caption track of one video and return timestamped text."""
    if not permission("allow_web_research"):
        return "Permission denied: web research is disabled in Settings."
    try:
        ident, known_title = _resolve(query)
        watch_url = WATCH_URL.format(video_id=ident)
        document = _http_get(watch_url)
        title = page_title(document) or known_title or ident
        track = caption_url(document)
        if not track:
            return (
                f'Found "{title}" ({watch_url}) but it has no readable captions. '
                "I cannot transcribe the audio locally without downloading it."
            )
        cues = parse_timedtext(_http_get(track))
    except MediaError as exc:
        return f"Could not read the transcript: {exc}"
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return f"Could not reach YouTube: {exc}"
    if not cues:
        return (
            f'"{title}" has a caption track, but it was empty or unreadable. '
            "Nothing was downloaded or saved."
        )
    body = bounded_text(" ".join(cues), MAX_TRANSCRIPT_CHARS)
    return (
        f'Transcript of "{title}" ({watch_url}), read from public captions:\n\n'
        f"{body}\n\n"
        "Nothing was downloaded, saved or played."
    )


TOOLS = [
    {
        "name": "youtube_transcript",
        "confirm": False,
        "timeout_seconds": 40,
        "spec": {
            "type": "function",
            "function": {
                "name": "youtube_transcript",
                "description": (
                    "Read the public captions of one YouTube video and return "
                    "timestamped text, so you can summarize or discuss it. Accepts "
                    "a video URL, an 11-character id or a search phrase. Uses no "
                    "API key, downloads nothing and plays nothing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A YouTube URL, video id or search phrase.",
                        }
                    },
                    "required": ["query"],
                },
            },
        },
        "fn": youtube_transcript,
    },
]
