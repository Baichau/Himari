"""Avatar expression definitions shared by the personality and UI layers."""

EXPRESSIONS = {
    "idle": {"label": "Idle", "transient": False, "seconds": None},
    "listening": {"label": "Listening", "transient": False, "seconds": None},
    "thinking": {"label": "Thinking", "transient": False, "seconds": None},
    "speaking": {"label": "Speaking", "transient": False, "seconds": None},
    "happy": {"label": "Happy", "transient": True, "seconds": 2.5},
    "confused": {"label": "Confused", "transient": True, "seconds": 2.5},
    "sad": {"label": "Sad", "transient": True, "seconds": 2.5},
    "error": {"label": "Error", "transient": True, "seconds": 3.5},
}

AVATAR_STATES = tuple(EXPRESSIONS)


def normalize_expression(value, default="idle"):
    text = str(value or "").strip().casefold()
    return text if text in EXPRESSIONS else default


def label_for(expression):
    return EXPRESSIONS[normalize_expression(expression)]["label"]


def is_transient(expression):
    return EXPRESSIONS[normalize_expression(expression)]["transient"]


def duration_seconds(expression, fallback=2.5):
    seconds = EXPRESSIONS[normalize_expression(expression)]["seconds"]
    return fallback if seconds is None else seconds


def expr_from_status(status):
    """Map an application status message to a safe avatar expression."""
    text = str(status or "").casefold()
    if "error" in text or "failed" in text or "unavailable" in text:
        return "error"
    if "listening" in text:
        return "listening"
    if "generating" in text or "think" in text or "checking" in text:
        return "thinking"
    if "speaking" in text:
        return "speaking"
    if "tool" in text or "completed" in text or "working" in text:
        return "thinking"
    return "idle"
