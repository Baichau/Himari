"""Common interface for application integrations.

Every integration exposes is_available(), is_running(), supported_actions(),
and execute(action, arguments). Results are structured dicts; unsupported or
unavailable functionality is reported honestly, never simulated. Application
control reuses the existing allow_open_app setting.
"""

import logging

from .. import windows
from ..config import load as load_config

log = logging.getLogger("himari.integrations")


def integration_allowed():
    config = load_config()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return bool(permissions.get("allow_open_app", False))


class Integration:
    name = ""
    launch_name = ""
    discovery_names = ()
    process_names = ()

    def is_available(self):
        return any(windows.find_app(candidate) for candidate in self.discovery_names)

    def is_running(self):
        wanted = {process.casefold() for process in self.process_names}
        return any(
            process.name.casefold() in wanted
            for process in windows.running_processes()
        )

    def supported_actions(self):
        return sorted(self._handlers())

    def execute(self, action, arguments=None, confirm=None):
        arguments = arguments if isinstance(arguments, dict) else {}
        result = {"ok": False, "integration": self.name, "action": action}
        handlers = self._handlers()
        if action not in handlers:
            result["error"] = (
                f"Unsupported action '{action}' for {self.name}. "
                f"Supported: {', '.join(sorted(handlers))}."
            )
            return result
        if not integration_allowed():
            result["error"] = (
                "Permission denied: application control is disabled in Settings."
            )
            return result
        try:
            outcome = handlers[action](arguments, confirm)
        except windows.AmbiguousAppError as exc:
            outcome = {"ok": False, "error": str(exc)}
        except windows.AppNotFoundError as exc:
            outcome = {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.warning("Integration %s action %s failed: %s", self.name, action, exc)
            outcome = {"ok": False, "error": str(exc)}
        result.update(outcome)
        return result

    def _handlers(self):
        handlers = {"open": self._open, "close": self._close}
        handlers.update(self._extra_handlers())
        return handlers

    def _extra_handlers(self):
        return {}

    def _open(self, arguments, confirm):
        return windows.launch_app(self.launch_name)

    def _close(self, arguments, confirm):
        return windows.close_app(self.launch_name)

    def _executable(self):
        from pathlib import Path

        for candidate in self.discovery_names:
            for app in windows.find_app(candidate):
                if app.target.casefold().endswith(".exe") and Path(app.target).is_file():
                    return app.target
        return None