"""Tool risk classification and permission mapping.

Every tool the agent can call must appear here; unknown names are denied.
"""

from .permissions import RiskLevel

TOOL_RISKS = {
    # Existing chat tools
    "open_app": RiskLevel.LOW,
    "launch_game": RiskLevel.LOW,
    "play_music": RiskLevel.LOW,
    "open_url": RiskLevel.LOW,
    "search_web": RiskLevel.LOW,
    "open_first_result": RiskLevel.LOW,
    "research_web": RiskLevel.LOW,
    "search_youtube": RiskLevel.LOW,
    "close_app": RiskLevel.MEDIUM,
    "list_project_files": RiskLevel.READ,
    "set_volume": RiskLevel.LOW,
    "read_file": RiskLevel.READ,
    "write_file": RiskLevel.MEDIUM,
    "write_desktop_file": RiskLevel.MEDIUM,
    "capture_screen_text": RiskLevel.MEDIUM,
    "active_window": RiskLevel.READ,
    "media_control": RiskLevel.LOW,
    "generate_image": RiskLevel.LOW,
    "run_command": RiskLevel.HIGH,
    # Windows environment
    "installed_apps": RiskLevel.READ,
    "running_processes": RiskLevel.READ,
    "list_windows": RiskLevel.READ,
    "find_app": RiskLevel.READ,
    "launch_app": RiskLevel.LOW,
    # Perception
    "capture_screen": RiskLevel.MEDIUM,
    "screen_scene": RiskLevel.MEDIUM,
    # Browser
    "browser_open": RiskLevel.LOW,
    "browser_navigate": RiskLevel.LOW,
    "browser_search": RiskLevel.LOW,
    "browser_open_result": RiskLevel.LOW,
    "browser_tabs": RiskLevel.MEDIUM,
    "browser_close": RiskLevel.LOW,
    "browser_read": RiskLevel.READ,
    "browser_click": RiskLevel.MEDIUM,
    "browser_fill": RiskLevel.MEDIUM,
    "browser_submit": RiskLevel.HIGH,
    # Integrations
    "integration_status": RiskLevel.READ,
    "integration_open": RiskLevel.LOW,
    "integration_close": RiskLevel.MEDIUM,
    "integration_action": RiskLevel.MEDIUM,
    # Development
    "read_source": RiskLevel.READ,
    "search_code": RiskLevel.READ,
    "propose_change": RiskLevel.READ,
    "apply_change": RiskLevel.MEDIUM,
    "run_tests": RiskLevel.MEDIUM,
    # Memory
    "memory_add": RiskLevel.LOW,
    "memory_search": RiskLevel.READ,
    "memory_delete": RiskLevel.MEDIUM,
}

TOOL_PERMISSIONS = {
    "open_app": "allow_open_app",
    "launch_game": "allow_open_app",
    "play_music": "allow_open_app",
    "open_url": "allow_open_url",
    "search_web": "allow_open_url",
    "search_youtube": "allow_open_url",
    "open_first_result": "allow_open_url",
    "research_web": "allow_web_research",
    "close_app": "allow_open_app",
    "read_file": "allow_read_file",
    "list_project_files": "allow_read_file",
    "write_file": "allow_write_file",
    "write_desktop_file": "allow_write_file",
    "set_volume": "allow_volume",
    "run_command": "allow_run_command",
    "capture_screen_text": "allow_screen_capture",
    "capture_screen": "allow_screen_capture",
    "screen_scene": "allow_screen_capture",
    "active_window": "allow_active_window",
    "media_control": "allow_media_control",
    "generate_image": "allow_image_generation",
    "launch_app": "allow_open_app",
    "integration_open": "allow_open_app",
    "integration_close": "allow_open_app",
    "integration_action": "allow_open_app",
    "browser_open": "allow_browser_automation",
    "browser_navigate": "allow_browser_automation",
    "browser_search": "allow_browser_automation",
    "browser_open_result": "allow_browser_automation",
    "browser_tabs": "allow_browser_automation",
    "browser_close": "allow_browser_automation",
    "browser_read": "allow_browser_automation",
    "browser_click": "allow_browser_automation",
    "browser_fill": "allow_browser_automation",
    "browser_submit": "allow_browser_automation",
}

BLOCKED_PATH_PARTS = (
    "\\windows\\system32",
    "/windows/system32",
)

BLOCKED_FILE_NAMES = (
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "secrets.json",
    "ntds.dit",
)

BLOCKED_FILE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".keystore", ".ppk")

# Tools that already asked for per-action confirmation in the chat UI keep
# asking when the agent or wrapped tools run them.
CONFIRMATION_TOOLS = {
    "close_app",
    "list_project_files",
    "read_file",
    "write_file",
    "write_desktop_file",
    "capture_screen_text",
    "run_command",
    "browser_submit",
}

# Even after approval these must ask again every time.
NEVER_SESSION_GRANT = {"browser_submit"}


def confirmation_required_for(tool):
    return tool in CONFIRMATION_TOOLS


def tool_is_known(tool):
    return tool in TOOL_RISKS


def risk_for(tool):
    return TOOL_RISKS.get(tool, RiskLevel.HIGH)


def permission_key_for(tool):
    return TOOL_PERMISSIONS.get(tool)