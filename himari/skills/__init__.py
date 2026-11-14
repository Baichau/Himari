"""Opt-in capability skills kept out of the main tool module.

Each module exposes a ``TOOLS`` list in the same shape as ``himari.tools``.
``skill_tools()`` gathers them lazily so importing the package stays cheap.
"""


def skill_tools():
    """Return every skill tool entry, without duplicates by tool name."""
    from . import coach, continuity, doctor, media, pair, watch

    seen = set()
    tools = []
    for module in (watch, coach, doctor, pair, media, continuity):
        for entry in getattr(module, "TOOLS", ()):
            name = entry.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            tools.append(entry)
    return tools


__all__ = ["skill_tools"]
