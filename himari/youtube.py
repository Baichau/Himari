"""Resolve YouTube video links without a browser window or an API key.

One request is sent to the public results page, the embedded ``ytInitialData``
JSON is read locally, and the first few video links are returned. Nothing is
downloaded, opened, or played here; the caller decides whether to open a single
page.
"""

import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger("himari.youtube")

SEARCH_URL = "https://www.youtube.com/results"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2_000_000
MAX_RESULTS = 5
MAX_WALK_NODES = 200_000

_INITIAL_DATA = (
    re.compile(r"var\s+ytInitialData\s*=\s*(\{.*?\});\s*</script>", re.DOTALL),
    re.compile(r"window\[\"ytInitialData\"\]\s*=\s*(\{.*?\});\s*</script>", re.DOTALL),
)
_FALLBACK_RENDERER = re.compile(
    r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})".{0,4000}?'
    r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
    re.DOTALL,
)


def _runs_text(block):
    if not isinstance(block, dict):
        return ""
    runs = block.get("runs")
    if not isinstance(runs, list):
        return ""
    return "".join(
        str(run.get("text") or "")
        for run in runs
        if isinstance(run, dict)
    ).strip()


def _simple_text(block):
    if not isinstance(block, dict):
        return ""
    return str(block.get("simpleText") or "").strip()


def _walk(node, found, budget):
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, dict):
        renderer = node.get("videoRenderer")
        if isinstance(renderer, dict):
            record = _video_record(
                renderer.get("videoId"),
                _runs_text(renderer.get("title")),
                _runs_text(renderer.get("ownerText"))
                or _runs_text(renderer.get("longBylineText")),
                _simple_text(renderer.get("lengthText")),
            )
            if record:
                found.append(record)
        reel = node.get("reelItemRenderer")
        if isinstance(reel, dict):
            record = _video_record(
                reel.get("videoId"),
                _simple_text(reel.get("headline")),
                "",
                "",
            )
            if record:
                found.append(record)
        for value in node.values():
            _walk(value, found, budget)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found, budget)


def _video_record(video_id, title, channel, duration):
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None
    if not title:
        return None
    return {
        "title": " ".join(str(title).split()),
        "url": WATCH_URL.format(video_id=video_id),
        "channel": " ".join(str(channel).split()),
        "duration": " ".join(str(duration).split()),
    }


def _json_string(raw):
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw


def _extract_from_initial_data(html):
    for pattern in _INITIAL_DATA:
        match = pattern.search(html)
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            continue
        found = []
        _walk(payload, found, [MAX_WALK_NODES])
        if found:
            return found
    return []


def _extract_from_renderers(html):
    found = []
    for video_id, raw_title in _FALLBACK_RENDERER.findall(html):
        record = _video_record(video_id, _json_string(raw_title), "", "")
        if record:
            found.append(record)
    return found


def extract_videos(html, limit=MAX_RESULTS):
    """Return unique video records found in a YouTube results page."""
    videos = _extract_from_initial_data(html)
    if not videos:
        videos = _extract_from_renderers(html)
    unique = []
    seen = set()
    for video in videos:
        if video["url"] in seen:
            continue
        seen.add(video["url"])
        unique.append(video)
        if len(unique) >= limit:
            break
    return unique


def search_videos(query, limit=MAX_RESULTS):
    """Return (videos, error_message); network problems are reported, not raised."""
    query = str(query or "").strip()
    if not query:
        return [], "Tell me what video to look for."
    request = Request(
        f"{SEARCH_URL}?{urlencode({'search_query': query})}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status < 200 or response.status >= 300:
                return [], f"YouTube returned HTTP {response.status}."
            document = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        return [], f"YouTube returned HTTP {exc.code}."
    except (URLError, TimeoutError, OSError) as exc:
        log.info("YouTube search request failed: %s", exc)
        return [], "I couldn't reach YouTube; the internet may be unavailable."

    html = document[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
    videos = extract_videos(html, limit)
    if not videos:
        return [], "YouTube responded, but no video links could be read from the page."
    return videos, None
