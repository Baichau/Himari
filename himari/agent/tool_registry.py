"""Registry and argument validation for agent-callable tools.

The registry reuses the existing ``himari.tools.TOOLS`` entries; it does not
re-implement any tool. Validation is fail-closed: unknown tools, non-object
arguments, missing required fields, unexpected fields, and wrong types are
rejected before any handler runs.
"""

from .. import tools as builtin_tools
from ..tool_schema import ToolArgumentError, validate_arguments


class UnknownToolError(KeyError):
    pass


class ToolRegistry:
    def __init__(self, tools=None):
        self._tools = {}
        for entry in builtin_tools.TOOLS if tools is None else tools:
            self.register(entry)

    def register(self, entry):
        name = entry.get("name")
        if not name or not callable(entry.get("fn")):
            raise ValueError("A tool entry needs a name and a callable fn.")
        self._tools[name] = entry
        return entry

    def get(self, name):
        entry = self._tools.get(name)
        if entry is None:
            raise UnknownToolError(name)
        return entry

    def has(self, name):
        return name in self._tools

    def names(self):
        return sorted(self._tools)

    def specs(self):
        return [entry["spec"] for entry in self._tools.values() if entry.get("spec")]

    def _parameters(self, name):
        spec = self.get(name).get("spec") or {}
        return (spec.get("function") or {}).get("parameters") or {}

    def validate_arguments(self, name, arguments):
        """Return a cleaned arguments dict or raise ToolArgumentError."""
        return validate_arguments(self._parameters(name), arguments)
