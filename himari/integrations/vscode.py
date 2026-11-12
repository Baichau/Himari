"""Visual Studio Code integration: open, close, open a project folder."""

import os
import subprocess
from pathlib import Path

from .base import Integration


class VSCodeIntegration(Integration):
    name = "vscode"
    launch_name = "Visual Studio Code"
    discovery_names = ("Visual Studio Code", "VS Code")
    process_names = ("code.exe",)

    def _extra_handlers(self):
        return {"open_project": self._open_project}

    def _open_project(self, arguments, confirm):
        raw = arguments.get("path")
        if not raw:
            return {"ok": False, "error": "Provide the project folder path."}
        folder = Path(os.path.expandvars(os.path.expanduser(str(raw))))
        if not folder.is_dir():
            return {"ok": False, "error": f"Project folder not found: {raw}"}
        executable = self._executable()
        if not executable:
            return {"ok": False, "error": "VS Code's executable path was not discovered."}
        subprocess.Popen([executable, str(folder)])
        return {"ok": True, "message": f"Opened VS Code in {folder}."}