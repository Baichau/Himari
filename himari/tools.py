import os
import re
import shlex
import shutil
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote, urlencode

from .config import load


def _perm(key):
    config = load()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    return bool(permissions.get(key, False))


def _file_path(path):
    if path is None:
        raise PermissionError("No path provided.")

    requested = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve(strict=False)
    config = load()
    permissions = config.get("permissions", {}) if isinstance(config, dict) else {}
    allowed_folders = permissions.get("allowed_folders", [])

    if not isinstance(allowed_folders, (list, tuple, set)):
        raise PermissionError("This path is outside the configured allowed folders.")

    roots = []
    for folder in allowed_folders:
        if folder is None:
            continue
        root = Path(os.path.expandvars(os.path.expanduser(str(folder)))).resolve(strict=False)
        roots.append(root)

    if not any(requested == root or requested.is_relative_to(root) for root in roots):
        raise PermissionError("This path is outside the configured allowed folders.")
    return requested


def _open_protocol(uri):
    try:
        if os.name == "nt":
            os.startfile(uri)
        else:
            webbrowser.open(uri)
        return True
    except (OSError, AttributeError):
        return False


def _start_menu_shortcut(name):
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for shortcut in root.rglob("*.lnk"):
            if shortcut.stem.casefold() == name.casefold():
                try:
                    os.startfile(str(shortcut))
                    return True
                except (OSError, AttributeError):
                    continue
    return False


def _start_menu_app_id(app_id):
    try:
        os.startfile(f"shell:AppsFolder\\{app_id}")
        return True
    except (OSError, AttributeError):
        return False


def open_app(name):
    if not _perm("allow_open_app"):
        return "Permission denied: open_app"

    requested = name.strip()
    alias = requested.casefold()
    if alias in {"browser", "web browser", "default browser"}:
        return "Opened the default browser." if webbrowser.open("https://www.google.com") else \
            "Could not open the default browser."

    protocol = {
        "spotify": "spotify:",
        "steam": "steam://open/main",
    }.get(alias)
    if protocol and _open_protocol(protocol):
        return f"Opened {requested}."

    shortcut_names = {
        "chrome": ("Google Chrome",),
        "google chrome": ("Google Chrome",),
        "edge": ("Microsoft Edge",),
        "microsoft edge": ("Microsoft Edge",),
        "minecraft": ("Minecraft Launcher", "Minecraft"),
        "minecraft launcher": ("Minecraft Launcher",),
    }.get(alias, (requested,))
    for shortcut_name in shortcut_names:
        if _start_menu_shortcut(shortcut_name):
            return f"Opened {shortcut_name}."
    if alias in {"minecraft", "minecraft launcher"} and _start_menu_app_id(
        "Microsoft.4297127D64EC_8wekyb3d8bbwe!Minecraft"
    ):
        return "Opened Minecraft Launcher."

    candidate = Path(os.path.expandvars(os.path.expanduser(requested)))
    if candidate.is_file():
        try:
            if os.name == "nt":
                os.startfile(str(candidate))
            else:
                subprocess.Popen([str(candidate)])
            return f"Opened {requested}."
        except OSError as e:
            return f"Failed to open {requested}: {e}"

    executable = shutil.which(requested)
    if executable:
        try:
            subprocess.Popen([executable])
            return f"Opened {requested}."
        except OSError as e:
            return f"Failed to open {requested}: {e}"
    return f"Could not find '{requested}'. Try an installed Start Menu app name or full path."


def open_url(url):
    if not _perm("allow_open_url"):
        return "Permission denied: open_url"
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        opened = webbrowser.open(url)
    except Exception as e:
        return f"Failed to open {url}: {e}"
    return f"Opened {url}" if opened else f"Could not open {url}"


def close_app(name):
    if not _perm("allow_open_app"):
        return "Permission denied: open_app"
    requested = (name or "").strip()
    if not requested:
        return "Tell me which app to close."
    try:
        import pygetwindow as gw
        windows = gw.getAllTitles()
        for title in windows:
            if title and requested.casefold() in title.casefold():
                w = gw.getWindowsWithTitle(title)
                if w:
                    w[0].close()
                    return f"Closed '{title}'."
    except Exception:
        pass
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/FI", f"WINDOWTITLE eq {requested}"], capture_output=True, text=True, check=False)
            return f"Attempted to close apps matching '{requested}'."
    except Exception as exc:
        return f"Could not close '{requested}': {exc}"
    return f"Could not find an open app matching '{requested}'."


def play_music(query):
    if not _perm("allow_open_app"):
        return "Permission denied: open_app"
    query = query.strip()
    if not query:
        return "Tell me the song or artist to search for."
    spotify_uri = f"spotify:search:{quote(query)}"
    if _open_protocol(spotify_uri):
        return f"Opened Spotify search for '{query}'. Select a result in Spotify to start playback."
    url = f"https://open.spotify.com/search/{quote(query)}"
    try:
        return f"Opened Spotify search for '{query}'. Select a result to start playback." if webbrowser.open(url) else \
            "Could not open Spotify. You can try opening it from the Start Menu."
    except Exception as e:
        return f"Could not open Spotify: {e}"


def _steam_games():
    roots = set()
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            roots.add(Path(base) / "Steam")
    if os.name == "nt":
        try:
            import winreg
            for hive, key in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, key) as steam_key:
                        install = winreg.QueryValueEx(steam_key, "SteamPath")[0]
                        roots.add(Path(install))
                except OSError:
                    pass
        except ImportError:
            pass

    libraries = set(roots)
    for root in roots:
        library_file = root / "steamapps" / "libraryfolders.vdf"
        try:
            contents = library_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw_path in re.findall(r'"path"\s+"((?:[^"\\]|\\.)*)"', contents):
            libraries.add(Path(raw_path.replace("\\\\", "\\")))

    games = []
    for library in libraries:
        for manifest in (library / "steamapps").glob("appmanifest_*.acf"):
            try:
                contents = manifest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            app_id = re.search(r'"appid"\s+"(\d+)"', contents)
            title = re.search(r'"name"\s+"([^"]+)"', contents)
            if app_id and title:
                games.append((title.group(1).casefold(), app_id.group(1)))
    return games


def launch_game(name):
    if not _perm("allow_open_app"):
        return "Permission denied: open_app"
    requested = name.strip()
    match = next((app_id for title, app_id in _steam_games()
                  if title == requested.casefold()), None)
    if match:
        uri = f"steam://rungameid/{match}"
        if _open_protocol(uri):
            return f"Asked Steam to launch '{requested}'."
        return "Could not contact Steam. Make sure Steam is installed and running."
    return open_app(requested)


def set_volume(percent):
    if not _perm("allow_volume"):
        return "Permission denied: set_volume"
    try:
        percent = max(0, min(100, int(percent)))
        from ctypes import windll
        windll.winmm.waveOutSetVolume(0, int((percent / 100) * 65535))
        return f"Volume set to {percent}%"
    except Exception as e:
        return f"Failed: {e}"


def read_file(path):
    if not _perm("allow_read_file"):
        return "Permission denied: read_file"
    try:
        path = _file_path(path)
        if not path.is_file():
            return f"File not found: {path}"
        if path.stat().st_size > 200_000:
            return "File too large to read safely."
        with path.open(encoding="utf-8", errors="replace") as f:
            return f.read()[:20_000]
    except (OSError, PermissionError) as e:
        return f"Failed: {e}"


def write_file(path, content):
    if not _perm("allow_write_file"):
        return "Permission denied: write_file"
    try:
        path = _file_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {path}"
    except (OSError, PermissionError) as e:
        return f"Failed: {e}"


def active_window():
    try:
        import pygetwindow as gw
        window = gw.getActiveWindow()
        return f"Active window: {window.title}"
    except Exception as e:
        return f"Failed: {e}"


def _safe_command_list(cmd):
    if isinstance(cmd, str):
        parts = shlex.split(cmd, posix=os.name != "nt")
    elif isinstance(cmd, (list, tuple)):
        parts = [str(part) for part in cmd]
    else:
        raise TypeError("Command must be a string or list of arguments.")
    if not parts:
        raise ValueError("Command is empty.")
    allowlist = {
        "dir", "type", "echo", "where", "whoami", "hostname", "ipconfig", "tasklist", "taskkill",
        "git", "python", "py", "cmd", "powershell", "powershell.exe", "wmic",
        "start", "notepad", "explorer", "reg", "sc", "netstat", "systeminfo",
    }
    exe = Path(parts[0]).name.lower()
    if exe not in allowlist:
        raise PermissionError(f"Command not allowed: {parts[0]}")
    return parts


def run_command(cmd):
    if not _perm("allow_run_command"):
        return "Permission denied: run_command is disabled by default."
    try:
        parts = _safe_command_list(cmd)
        result = subprocess.run(parts, capture_output=True, text=True, timeout=20, shell=False)
        return (result.stdout + result.stderr)[:4000] or "(no output)"
    except (PermissionError, ValueError, TypeError) as e:
        return f"Failed: {e}"
    except Exception as e:
        return f"Failed: {e}"


def search_web(query):
    return open_url(f"https://www.google.com/search?{urlencode({'q': query})}")


def search_youtube(query):
    return open_url(f"https://www.youtube.com/results?{urlencode({'search_query': query})}")


def list_project_files(path, max_files=100):
    if not _perm("allow_read_file"):
        return "Permission denied: read_file"
    root = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve(strict=False)
    if not root.exists() or not root.is_dir():
        return f"Project path not found: {path}"
    try:
        _file_path(str(root))
    except PermissionError:
        return "This project path is outside the configured allowed folders."

    ignore = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".pytest_cache", ".mypy_cache", ".idea"}
    matches = []
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(root)
        if any(part in ignore for part in rel.parts):
            continue
        matches.append(str(rel).replace("\\", "/"))
        if len(matches) >= max_files:
            break
    return matches


TOOLS = [
    {"name": "open_app", "confirm": False, "spec": {"type": "function", "function": {
        "name": "open_app", "description": "Open a Windows app by its Start Menu name, a common app alias (browser, Spotify, Steam, Minecraft), or a full path.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
     "fn": open_app},
    {"name": "launch_game", "confirm": False, "spec": {"type": "function", "function": {
        "name": "launch_game", "description": "Launch an installed Steam game by its exact library title, or open a game launcher by its Start Menu name.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
     "fn": launch_game},
    {"name": "play_music", "confirm": False, "spec": {"type": "function", "function": {
        "name": "play_music", "description": "Open Spotify to search for a song or artist. The user chooses a result to begin playback.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
     "fn": play_music},
    {"name": "open_url", "confirm": False, "spec": {"type": "function", "function": {
        "name": "open_url", "description": "Open a website URL in the default browser.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
     "fn": open_url},
    {"name": "search_web", "confirm": False, "spec": {"type": "function", "function": {
        "name": "search_web", "description": "Search the web in the default browser.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
     "fn": search_web},
    {"name": "search_youtube", "confirm": False, "spec": {"type": "function", "function": {
        "name": "search_youtube", "description": "Open YouTube search results for a query.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
     "fn": search_youtube},
    {"name": "close_app", "confirm": False, "spec": {"type": "function", "function": {
        "name": "close_app", "description": "Close an open desktop app if it matches the provided name.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
     "fn": close_app},
    {"name": "list_project_files", "confirm": True, "confirm_message": "Allow Himari to inspect this project folder?",
     "spec": {"type": "function", "function": {
         "name": "list_project_files", "description": "List project files while ignoring common build/cache folders.",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "max_files": {"type": "integer"}}, "required": ["path"]}}},
     "fn": list_project_files},
    {"name": "set_volume", "confirm": False, "spec": {"type": "function", "function": {
        "name": "set_volume", "description": "Set system volume from 0 to 100.",
        "parameters": {"type": "object", "properties": {"percent": {"type": "integer"}}, "required": ["percent"]}}},
     "fn": set_volume},
    {"name": "read_file", "confirm": True, "confirm_message": "Allow Himari to read this file?",
     "spec": {"type": "function", "function": {
         "name": "read_file", "description": "Read a text file the user specified.",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
     "fn": read_file},
    {"name": "write_file", "confirm": True, "confirm_message": "Allow Himari to write this file?",
     "spec": {"type": "function", "function": {
         "name": "write_file", "description": "Write text to a file.",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"]}}},
     "fn": write_file},
    {"name": "active_window", "confirm": False, "spec": {"type": "function", "function": {
        "name": "active_window", "description": "Get the active window title.",
        "parameters": {"type": "object", "properties": {}}}},
     "fn": active_window},
    {"name": "run_command", "confirm": True, "confirm_message": "Allow Himari to run this shell command?",
     "spec": {"type": "function", "function": {
         "name": "run_command", "description": "Run a shell command (disabled by default).",
         "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
     "fn": run_command},
]
