"""Registry and argument validation for agent-callable tools.

The registry reuses the existing ``himari.tools.TOOLS`` entries; it does not
re-implement any tool. Validation is fail-closed: unknown tools, non-object
arguments, missing required fields, unexpected fields, and wrong types are
rejected before any handler runs.
"""

from .. import tools as builtin_tools


class UnknownToolError(KeyError):
    pass


class ToolArgumentError(ValueError):
    pass


_TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, (list, tuple)),
    "object": lambda value: isinstance(value, dict),
}


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
        if not isinstance(arguments, dict):
            raise ToolArgumentError("Tool arguments must be an object.")
        parameters = self._parameters(name)
        properties = parameters.get("properties") or {}
        required = parameters.get("required") or []

        missing = [key for key in required if key not in arguments]
        if missing:
            raise ToolArgumentError(
                "Missing required argument(s): " + ", ".join(sorted(missing))
            )

        if properties:
            unexpected = [key for key in arguments if key not in properties]
            if unexpected:
                raise ToolArgumentError(
                    "Unexpected argument(s): " + ", ".join(sorted(unexpected))
                )

        for key, value in arguments.items():
            expected = (properties.get(key) or {}).get("type")
            checker = _TYPE_CHECKS.get(expected)
            if checker and not checker(value):
                raise ToolArgumentError(
                    f"Argument '{key}' must be a {expected}."
                )
            allowed_values = (properties.get(key) or {}).get("enum")
            if allowed_values and value not in allowed_values:
                raise ToolArgumentError(
                    f"Argument '{key}' must be one of: "
                    + ", ".join(str(item) for item in allowed_values)
                )
        return dict(arguments)
