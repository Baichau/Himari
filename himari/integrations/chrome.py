"""Chrome integration: open, close, and open a validated URL."""

import subprocess

from .. import windows
from ..browser.navigation import BrowserError, validate_url
from .base import Integration


class ChromeIntegration(Integration):
    name = "chrome"
    launch_name = "Google Chrome"
    discovery_names = ("Google Chrome", "chrome")
    process_names = ("chrome.exe",)

    def _extra_handlers(self):
        return {"open_url": self._open_url}

    def _open_url(self, arguments, confirm):
        try:
            target = validate_url(arguments.get("url", ""))
        except BrowserError as exc:
            return {"ok": False, "error": str(exc)}
        executable = self._executable()
        if not executable:
            return {"ok": False, "error": "Chrome's executable path was not discovered."}
        subprocess.Popen([executable, target])
        return {"ok": True, "message": f"Opened Chrome at {target}."}