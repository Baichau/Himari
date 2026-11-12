"""Activity feed backed by the local audit log."""

import json
from datetime import datetime

from .. import db


def parse_arguments(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {"raw": str(value)}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def activity_rows(limit=50):
    rows = []
    for action in db.recent_actions(limit=limit):
        rows.append({
            "id": action.get("id"),
            "tool": action.get("tool", ""),
            "arguments": parse_arguments(action.get("args")),
            "result": str(action.get("result", ""))[:1000],
            "approved": bool(action.get("approved")),
            "timestamp": float(action.get("ts") or 0),
            "display_time": datetime.fromtimestamp(action.get("ts") or 0).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        })
    return rows


def format_activity(row):
    status = "allowed" if row["approved"] else "denied"
    return (
        f"{row['display_time']}  {row['tool']}  [{status}]\n"
        f"{row['result']}"
    )


def recent_summary(limit=5):
    rows = activity_rows(limit=limit)
    if not rows:
        return "No tool activity yet."
    return "\n".join(
        f"{row['display_time']} {row['tool']} "
        f"({'allowed' if row['approved'] else 'denied'})"
        for row in rows
    )
