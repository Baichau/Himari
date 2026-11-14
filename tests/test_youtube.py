import json
from urllib.error import URLError

import pytest

from himari import tools, youtube

INITIAL_DATA = {
    "contents": {
        "twoColumnSearchResultsRenderer": {
            "primaryContents": {
                "sectionListRenderer": {
                    "contents": [
                        {
                            "itemSectionRenderer": {
                                "contents": [
                                    {
                                        "videoRenderer": {
                                            "videoId": "abc123DEF45",
                                            "title": {"runs": [{"text": "10 Hours Fireplace"}]},
                                            "ownerText": {"runs": [{"text": "Cozy Sounds"}]},
                                            "lengthText": {"simpleText": "10:00:00"},
                                        }
                                    },
                                    {
                                        "videoRenderer": {
                                            "videoId": "xyz789GHI01",
                                            "title": {"runs": [{"text": "Fireplace Ambience"}]},
                                            "ownerText": {"runs": [{"text": "Calm Channel"}]},
                                            "lengthText": {"simpleText": "3:00:00"},
                                        }
                                    },
                                    {
                                        "videoRenderer": {
                                            "videoId": "abc123DEF45",
                                            "title": {"runs": [{"text": "Duplicate"}]},
                                        }
                                    },
                                ],
                            }
                        }
                    ]
                }
            }
        }
    }
}


def _page(payload=None, extra=""):
    data = json.dumps(payload if payload is not None else INITIAL_DATA)
    return f"<html><script>var ytInitialData = {data};</script>{extra}</html>"


def test_extract_videos_reads_initial_data_and_dedupes():
    videos = youtube.extract_videos(_page())

    assert [video["url"] for video in videos] == [
        "https://www.youtube.com/watch?v=abc123DEF45",
        "https://www.youtube.com/watch?v=xyz789GHI01",
    ]
    assert videos[0]["title"] == "10 Hours Fireplace"
    assert videos[0]["channel"] == "Cozy Sounds"
    assert videos[0]["duration"] == "10:00:00"


def test_extract_videos_falls_back_to_renderer_blocks():
    html = (
        '<script>"videoRenderer":{"videoId":"abc123DEF45","thumbnail":{},'
        '"title":{"runs":[{"text":"Cozy \\"Fireplace\\" Hour"}]}}</script>'
    )

    videos = youtube.extract_videos(html)

    assert videos == [{
        "title": 'Cozy "Fireplace" Hour',
        "url": "https://www.youtube.com/watch?v=abc123DEF45",
        "channel": "",
        "duration": "",
    }]


def test_extract_videos_returns_nothing_for_unreadable_pages():
    assert youtube.extract_videos("<html>consent wall</html>") == []


def test_search_videos_reports_network_failure(monkeypatch):
    def boom(request, timeout=None):
        raise URLError("offline")

    monkeypatch.setattr(youtube, "urlopen", boom)

    videos, error = youtube.search_videos("fireplace")

    assert videos == []
    assert "couldn't reach YouTube" in error


def test_search_videos_rejects_an_empty_query():
    videos, error = youtube.search_videos("   ")

    assert videos == []
    assert "what video" in error


def test_find_video_returns_watch_urls_without_opening(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(youtube, "search_videos", lambda query, limit: ([
        {
            "title": "10 Hours Fireplace",
            "url": "https://www.youtube.com/watch?v=abc123DEF45",
            "channel": "Cozy Sounds",
            "duration": "10:00:00",
        }
    ][:limit], None))

    result = tools.find_video("fireplace video")

    assert "nothing was opened" in result
    assert "https://www.youtube.com/watch?v=abc123DEF45" in result
    assert "open only that watch URL" in result


def test_open_video_opens_exactly_one_watch_url(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    opened = []
    monkeypatch.setattr(
        tools,
        "open_url",
        lambda url: opened.append(url) or f"Opened {url}",
    )
    monkeypatch.setattr(youtube, "search_videos", lambda query, limit: ([
        {
            "title": "10 Hours Fireplace",
            "url": "https://www.youtube.com/watch?v=abc123DEF45",
            "channel": "Cozy Sounds",
            "duration": "10:00:00",
        }
    ][:limit], None))

    result = tools.open_video("fireplace video")

    assert opened == ["https://www.youtube.com/watch?v=abc123DEF45"]
    assert "Opened video 1" in result
    assert "not verified" in result


def test_open_video_reports_a_missing_index(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(youtube, "search_videos", lambda query, limit: ([], None))

    assert "does not exist" in tools.open_video("fireplace video", index=2)


def test_open_video_requires_permission(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert "disabled in Settings" in tools.open_video("fireplace video")


def test_find_video_requires_web_research_permission(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: False)

    assert "disabled in Settings" in tools.find_video("fireplace video")


def test_find_video_reports_search_errors(monkeypatch):
    monkeypatch.setattr(tools, "_perm", lambda name: True)
    monkeypatch.setattr(youtube, "search_videos", lambda query, limit: ([], "YouTube returned HTTP 429."))

    assert tools.find_video("fireplace video") == "YouTube returned HTTP 429."
