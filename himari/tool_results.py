"""Shared classification of raw tool return values.

Chat and agent execution both use this so a tool that reports failure is never
counted or presented as a success. Classification only reads the value; it
never changes the observation the model sees.
"""

_FAILURE_PREFIXES = (
    "denied:",
    "tool error:",
    "permission denied",
    "invalid arguments",
    "unknown tool",
    "outside the configured allowed folders",
    "failed",
    "could not",
    "unable to",
    "cannot ",
)


def classify_result(result):
    """Return ``(succeeded, error_text)`` for a raw tool return value."""
    if result is None:
        return False, "The tool returned no result."
    if isinstance(result, dict) and result.get("ok") is False:
        return False, str(result.get("error") or "The tool reported failure.")
    if isinstance(result, str):
        text = result.strip()
        if not text:
            return False, "The tool returned an empty result."
        lowered = text.casefold()
        if lowered.startswith(_FAILURE_PREFIXES):
            return False, text
    return True, ""
