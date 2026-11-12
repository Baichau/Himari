"""Steam integration: open, close, list installed games, launch by exact title.

Reuses the existing Steam library discovery from himari.tools.
"""

from ..tools import _open_protocol, _steam_games
from .base import Integration


class SteamIntegration(Integration):
    name = "steam"
    launch_name = "Steam"
    discovery_names = ("Steam",)
    process_names = ("steam.exe",)

    def _extra_handlers(self):
        return {"launch_game": self._launch_game, "list_games": self._list_games}

    def _open(self, arguments, confirm):
        if _open_protocol("steam://open/main"):
            return {"ok": True, "message": "Opened Steam."}
        from .. import windows

        return windows.launch_app(self.launch_name)

    def _list_games(self, arguments, confirm):
        games = sorted({title for title, _ in _steam_games()})
        return {"ok": True, "games": games}

    def _launch_game(self, arguments, confirm):
        requested = str(arguments.get("name") or "").strip()
        if not requested:
            return {"ok": False, "error": "Tell me which installed Steam game to launch."}
        matches = [
            app_id for title, app_id in _steam_games()
            if title == requested.casefold()
        ]
        if not matches:
            return {"ok": False, "error": f"No installed Steam game titled '{requested}'."}
        if len(matches) > 1:
            return {
                "ok": False,
                "error": f"Several Steam libraries contain '{requested}'. Specify the exact library title.",
            }
        if _open_protocol(f"steam://rungameid/{matches[0]}"):
            return {"ok": True, "message": f"Asked Steam to launch '{requested}'."}
        return {"ok": False, "error": "Could not contact Steam. Make sure Steam is installed and running."}