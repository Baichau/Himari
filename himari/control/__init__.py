"""Control Center backends for the PySide6 UI.

The modules here are Qt-free so they can be tested without a display. The UI
calls them from worker threads and updates widgets through Qt signals.
"""

from .activity_view import activity_rows, format_activity, recent_summary
from .dashboard import (
    build_dashboard,
    build_dashboard_async,
    format_dashboard,
)
from .diagnostics import (
    diagnostics_async,
    format_diagnostics,
    run_diagnostics,
    summary as diagnostics_summary,
)
from .memory_view import (
    approve,
    delete,
    memory_rows,
    reject,
    stats as memory_stats,
    suggestion_rows,
    update,
)
from .permissions_view import (
    PERMISSION_LABELS,
    enabled_capabilities,
    permission_rows,
    requires_confirmation_summary,
    set_permission,
)
from .settings import SCHEMA, SettingsError, SettingsService

__all__ = [
    "PERMISSION_LABELS",
    "SCHEMA",
    "SettingsError",
    "SettingsService",
    "activity_rows",
    "approve",
    "build_dashboard",
    "build_dashboard_async",
    "delete",
    "diagnostics_async",
    "diagnostics_summary",
    "enabled_capabilities",
    "format_activity",
    "format_dashboard",
    "format_diagnostics",
    "memory_rows",
    "memory_stats",
    "permission_rows",
    "recent_summary",
    "reject",
    "requires_confirmation_summary",
    "run_diagnostics",
    "set_permission",
    "suggestion_rows",
    "update",
]
