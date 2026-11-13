"""Shared JSON-schema validation for tool arguments.

Both the chat tool loop and the agent executor validate through this module so a
malformed call can never reach a handler on one path while being rejected on the
other.
"""


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


def validate_arguments(parameters, arguments):
    """Return a cleaned copy of ``arguments`` or raise ToolArgumentError.

    Validation is fail-closed for declared properties: missing required values,
    unexpected keys, wrong types, and enum violations are rejected before any
    handler runs.
    """
    if not isinstance(arguments, dict):
        raise ToolArgumentError("Tool arguments must be an object.")
    parameters = parameters or {}
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
        property_schema = properties.get(key) or {}
        checker = _TYPE_CHECKS.get(property_schema.get("type"))
        if checker and not checker(value):
            raise ToolArgumentError(
                f"Argument '{key}' must be a {property_schema.get('type')}."
            )
        allowed_values = property_schema.get("enum")
        if allowed_values and value not in allowed_values:
            raise ToolArgumentError(
                "Argument '" + key + "' must be one of: "
                + ", ".join(str(item) for item in allowed_values)
            )
    return dict(arguments)
