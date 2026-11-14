from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from himari.applications import spotify
from himari.windows import media_session


def _track(name, artists=("Artist",), popularity=50, tid="t1"):
    return spotify.Track(
        id=tid,
        uri=f"spotify:track:{tid}",
        name=name,
        artists=tuple(artists),
        album="Album",
        duration_ms=200000,
        popularity=popularity,
    )


def test_ranking_prefers_the_original_title_and_artist():
    original = _track("Blinding Lights", ("The Weeknd",), popularity=90, tid="a")
    remix = _track("Blinding Lights (Remix)", ("Some DJ",), popularity=92, tid="b")
    cover = _track("Blinding Lights", ("Cover Band",), popularity=95, tid="c")

    ranked = spotify.rank_tracks(
        [remix, cover, original], "Blinding Lights", artist="The Weeknd"
    )

    assert ranked[0].id == "a"
    assert [item.id for item in ranked].index("b") > 0


def test_ranking_penalizes_live_and_remix_when_not_requested():
    live = _track("Song (Live)", ("Artist",), popularity=99)
    studio = _track("Song", ("Artist",), popularity=10)
    ranked = spotify.rank_tracks([live, studio], "Song", artist="Artist")
    assert ranked[0].name == "Song"


def test_track_matching_allows_missing_artist_data():
    now = SimpleNamespace(title="Blinding Lights", artist="")
    assert spotify._track_matches(now, _track("Blinding Lights", ("The Weeknd",)))
    assert spotify._track_matches(now, None) is True


def test_search_parses_tracks(monkeypatch):
    payload = {
        "tracks": {
            "items": [
                {
                    "id": "abc",
                    "uri": "spotify:track:abc",
                    "name": "Blinding Lights",
                    "artists": [{"name": "The Weeknd"}],
                    "album": {"name": "After Hours"},
                    "duration_ms": 200040,
                    "popularity": 88,
                }
            ]
        }
    }
    response = Mock(status_code=200)
    response.json.return_value = payload
    client = Mock()
    client.get.return_value = response
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)

    monkeypatch.setattr(spotify.httpx, "Client", Mock(return_value=client))
    monkeypatch.setattr(spotify, "_access_token", lambda force=False: "token")

    tracks = spotify.search_tracks("Blinding Lights", artist="The Weeknd")

    assert tracks[0].id == "abc"
    assert tracks[0].artist_text == "The Weeknd"
    sent = client.get.call_args
    assert "Blinding Lights" in sent.kwargs["params"]["q"]


def _offline(monkeypatch):
    monkeypatch.setattr(spotify, "focus_app", lambda timeout=4.0: True)
    monkeypatch.setattr(
        spotify,
        "public_resolve_track",
        lambda query, artist=None, limit=3: (_ for _ in ()).throw(
            spotify.SpotifyError("no public result")
        ),
    )


def test_play_without_api_credentials_reports_honestly(monkeypatch):
    opened = []
    monkeypatch.setattr(spotify, "installed", lambda: True)
    monkeypatch.setattr(spotify, "ensure_running", lambda timeout=12.0: True)
    monkeypatch.setattr(spotify, "_has_credentials", lambda: False)
    monkeypatch.setattr(spotify, "_open_uri", lambda uri: opened.append(uri) or True)
    _offline(monkeypatch)

    result = spotify.play("Blinding Lights", artist="The Weeknd")

    assert result["ok"] is False
    assert result["verified"] is False
    assert "no track was selected" in result["error"]
    assert opened == ["spotify:search:Blinding%20Lights"]


def test_play_without_credentials_uses_public_track_link(monkeypatch):
    opened = []
    track = _track("Blinding Lights", ("The Weeknd",), tid="4JkIs37a2JnYdY82fdavcw")
    monkeypatch.setattr(spotify, "installed", lambda: True)
    monkeypatch.setattr(spotify, "ensure_running", lambda timeout=12.0: True)
    monkeypatch.setattr(spotify, "_has_credentials", lambda: False)
    monkeypatch.setattr(spotify, "focus_app", lambda timeout=4.0: True)
    monkeypatch.setattr(
        spotify, "public_resolve_track", lambda q, artist=None, limit=3: (track, [])
    )
    monkeypatch.setattr(spotify, "_open_uri", lambda uri: opened.append(uri) or True)
    confirmed = media_session.NowPlaying(
        app="Spotify.exe", title=track.name, artist=track.artist_text, playing=True
    )
    monkeypatch.setattr(
        spotify, "wait_until_playing", lambda expected, timeout=18.0: (True, confirmed)
    )

    result = spotify.play("Blinding Lights", artist="The Weeknd")

    assert result["ok"] is True
    assert result["method"] == "public-search"
    assert opened == [track.uri]


def test_public_track_parser_prefers_the_named_artist():
    document = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fopen.spotify.com%2Ftrack%2F2FRnf9qhLbvw8fu4IBXx78">'
        "Last Christmas - Song, Lyrics, and Music Video by Wham! | Spotify</a>"
        '<a class="result__snippet">Listen to Last Christmas by Wham! on Spotify.</a>'
        '<a class="result__a" href="https://open.spotify.com/track/6irkI8hqZqB4BC6xM4iHhb">'
        "Last Christmas - Remastered | Spotify</a>"
        '<a class="result__snippet">Wham!</a>'
    )

    ranked = spotify._parse_public_tracks(document, "last christmas", "wham")

    assert ranked[0][1] == "2FRnf9qhLbvw8fu4IBXx78"


def test_play_uses_api_and_requires_media_confirmation(monkeypatch):
    track = _track("Blinding Lights", ("The Weeknd",))
    played = []

    monkeypatch.setattr(spotify, "installed", lambda: True)
    monkeypatch.setattr(spotify, "ensure_running", lambda timeout=12.0: True)
    monkeypatch.setattr(spotify, "_has_credentials", lambda: True)
    monkeypatch.setattr(spotify, "focus_app", lambda timeout=4.0: True)
    monkeypatch.setattr(spotify, "resolve_track", lambda q, artist=None: (track, []))
    monkeypatch.setattr(
        spotify, "_open_uri", lambda uri: played.append(uri) or uri == track.uri
    )

    confirmed = media_session.NowPlaying(
        app="Spotify.exe", title=track.name, artist=track.artist_text, playing=True
    )
    monkeypatch.setattr(
        spotify, "wait_until_playing", lambda expected, timeout=18.0: (True, confirmed)
    )

    result = spotify.play("Blinding Lights", artist="The Weeknd")

    assert result["ok"] is True
    assert result["verified"] is True
    assert result["method"] == "spotify-api"
    assert played == [track.uri]


def test_play_does_not_claim_success_when_media_session_is_silent(monkeypatch):
    track = _track("Blinding Lights", ("The Weeknd",))
    monkeypatch.setattr(spotify, "installed", lambda: True)
    monkeypatch.setattr(spotify, "ensure_running", lambda timeout=12.0: True)
    monkeypatch.setattr(spotify, "_has_credentials", lambda: True)
    monkeypatch.setattr(spotify, "focus_app", lambda timeout=4.0: True)
    monkeypatch.setattr(spotify, "resolve_track", lambda q, artist=None: (track, []))
    monkeypatch.setattr(spotify, "_open_uri", lambda uri: True)
    monkeypatch.setattr(
        spotify, "wait_until_playing", lambda expected, timeout=18.0: (False, None)
    )

    result = spotify.play("Blinding Lights", artist="The Weeknd")

    assert result["ok"] is False
    assert result["verified"] is False
    assert "did not confirm playback" in result["error"]


def test_local_fallback_selects_a_row_only_when_uia_does(monkeypatch):
    monkeypatch.setattr(spotify, "installed", lambda: True)
    monkeypatch.setattr(spotify, "ensure_running", lambda timeout=12.0: True)
    monkeypatch.setattr(spotify, "_has_credentials", lambda: False)
    monkeypatch.setattr(spotify, "_open_uri", lambda uri: True)
    _offline(monkeypatch)
    monkeypatch.setattr(
        spotify,
        "_uia_search_and_select",
        lambda query, artist, timeout=15.0: {
            "attempted": True,
            "selected": "Blinding Lights — The Weeknd",
        },
    )
    confirmed = media_session.NowPlaying(
        app="Spotify.exe", title="Blinding Lights", artist="The Weeknd", playing=True
    )
    monkeypatch.setattr(
        spotify, "wait_until_playing", lambda expected, timeout=8.0: (True, confirmed)
    )

    result = spotify.play("Blinding Lights", artist="The Weeknd", allow_ui=True)

    assert result["ok"] is True
    assert result["method"] == "local-search"
    assert result["now_playing"]["title"] == "Blinding Lights"


def test_now_playing_is_flat_and_honest(monkeypatch):
    monkeypatch.setattr(
        media_session,
        "now_playing",
        lambda hint=None: media_session.NowPlaying(
            app="Spotify.exe", title="Song", artist="Artist", playing=True
        ),
    )
    result = spotify.now_playing()
    assert result["ok"] is True
    assert result["title"] == "Song"

    monkeypatch.setattr(media_session, "now_playing", lambda hint=None: None)
    missing = spotify.now_playing()
    assert missing["ok"] is False
    assert "nothing is playing" in missing["error"]


def test_unsupported_control_action_is_rejected():
    result = spotify.control("explode")
    assert result["ok"] is False
    assert "Unsupported" in result["error"]
