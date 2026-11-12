"""Spotify integration: open, close, and search.

Playback of a named track is not claimed: without a Spotify API the local
client can only open a search, and the user picks the result.
"""

from urllib.parse import quote

from .. import windows
from ..tools import _open_protocol
from .base import Integration


class SpotifyIntegration(Integration):
    name = "spotify"
    launch_name = "Spotify"
    discovery_names = ("Spotify",)
    process_names = ("spotify.exe",)

    def _extra_handlers(self):
        return {"search": self._search}

    def _open(self, arguments, confirm):
        if _open_protocol("spotify:"):
            return {"ok": True, "message": "Opened Spotify."}
        return windows.launch_app(self.launch_name)

    def _search(self, arguments, confirm):
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "Tell me the song or artist to search for."}
        if _open_protocol(f"spotify:search:{quote(query)}"):
            return {
                "ok": True,
                "message": (
                    f"Opened Spotify search for '{query}'. "
                    "Select a result in Spotify to start playback."
                ),
            }
        return {"ok": False, "error": "Could not open Spotify search. Is Spotify installed?"}