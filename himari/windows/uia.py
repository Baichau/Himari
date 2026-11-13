"""Semantic control of open windows through Windows UI Automation.

The module reads the real control tree with pywinauto and acts on controls by
their visible name, so the agent does not have to guess coordinates. It never
launches, closes, or kills anything, never types into password fields, and
never guesses between duplicate matches.
"""

import logging

log = logging.getLogger("himari.windows.uia")

MAX_CONTROLS = 120
MAX_CANDIDATES = 8
_ACTIVE_QUERIES = {"active", "foreground", "current", "current window"}


class ScreenControlError(RuntimeError):
    """Raised when a window or control cannot be resolved or acted on."""


def _desktop():
    try:
        from pywinauto import Desktop
    except Exception as exc:
        raise ScreenControlError(
            "Semantic screen control needs the pywinauto package. "
            "Install it with: pip install pywinauto"
        ) from exc
    return Desktop(backend="uia")


def _visible_windows(desktop):
    result = []
    for window in desktop.windows():
        try:
            if window.is_visible():
                result.append(window)
        except Exception as exc:
            log.debug("Skipping an unreadable window: %s", exc)
    return result


def _process_name(window):
    try:
        import psutil

        pid = int(window.element_info.process_id)
        return psutil.Process(pid).name().casefold()
    except Exception:
        return ""


def _window_title(window):
    try:
        return str(window.window_text() or "").strip()
    except Exception:
        return ""


def _foreground_hwnd():
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _foreground_window(desktop):
    hwnd = _foreground_hwnd()
    if not hwnd:
        raise ScreenControlError("There is no active window to control right now.")
    for window in _visible_windows(desktop):
        try:
            if int(window.handle) == hwnd:
                return window
        except Exception:
            continue
    raise ScreenControlError(
        "The active window is not available through UI Automation. "
        "Focus the window you mean and try again."
    )


def find_window(name):
    """Resolve one open window by title, process name, or 'active'."""
    query = str(name or "").strip()
    if not query:
        raise ScreenControlError("A window title or process name is required.")
    folded = query.casefold()
    desktop = _desktop()
    if folded in _ACTIVE_QUERIES:
        return _foreground_window(desktop)
    windows = _visible_windows(desktop)
    exact = [w for w in windows if _window_title(w).casefold() == folded]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ScreenControlError(
            _ambiguous_message(query, exact)
        )
    titled = [w for w in windows if folded in _window_title(w).casefold()]
    if len(titled) == 1:
        return titled[0]
    if len(titled) > 1:
        raise ScreenControlError(_ambiguous_message(query, titled))
    by_process = []
    for window in windows:
        process = _process_name(window)
        stem = process.removesuffix(".exe")
        if stem and (stem == folded or folded in stem):
            by_process.append(window)
    if len(by_process) == 1:
        return by_process[0]
    if len(by_process) > 1:
        raise ScreenControlError(_ambiguous_message(query, by_process))
    titles = ", ".join(sorted({_window_title(w) for w in windows if _window_title(w)})[:10])
    raise ScreenControlError(
        f"No open window matches '{query}'."
        + (f" Open windows: {titles}." if titles else "")
    )


def _ambiguous_message(query, windows):
    listed = ", ".join(
        f"'{_window_title(window)}'"
        for window in sorted(windows, key=_window_title)[:MAX_CANDIDATES]
    )
    return (
        f"{len(windows)} windows match '{query}': {listed}. "
        "Use a more specific title."
    )


def _focus(window, title):
    try:
        window.set_focus()
    except Exception as exc:
        raise ScreenControlError(
            f"Windows did not let Himari focus '{title}': {exc}"
        ) from exc


def focus_window(name):
    """Bring a resolved window to the foreground; report if Windows refused."""
    window = find_window(name)
    title = _window_title(window)
    _focus(window, title)
    return title


def _control_info(control):
    try:
        info = control.element_info
    except Exception:
        return None
    name = str(getattr(info, "name", "") or "").strip()
    if not name:
        return None
    return {
        "name": name,
        "control_type": str(getattr(info, "control_type", "") or "").strip(),
        "automation_id": str(getattr(info, "automation_id", "") or "").strip(),
    }


def list_controls(window, name_filter=None, limit=MAX_CONTROLS):
    """List named controls of an open window, optionally filtered by text."""
    try:
        limit = max(1, min(int(limit), MAX_CONTROLS))
    except (TypeError, ValueError):
        limit = MAX_CONTROLS
    target = find_window(window)
    title = _window_title(target)
    needle = str(name_filter or "").strip().casefold()
    found = []
    try:
        controls = target.descendants()
    except Exception as exc:
        raise ScreenControlError(
            f"Could not read the controls of '{title}': {exc}"
        ) from exc
    for control in controls:
        info = _control_info(control)
        if info is None:
            continue
        if needle and needle not in info["name"].casefold() and needle not in info[
            "control_type"
        ].casefold():
            continue
        try:
            info["enabled"] = bool(control.is_enabled())
            info["visible"] = bool(control.is_visible())
        except Exception:
            info["enabled"] = None
            info["visible"] = None
        found.append(info)
        if len(found) >= limit:
            break
    return {"window": title, "count": len(found), "controls": found}


def _control_type(control):
    info = _control_info(control)
    return (info or {}).get("control_type", "")


def _match_control(window, name, control_type=None):
    query = str(name or "").strip()
    if not query:
        raise ScreenControlError("A control name is required; run list_controls first.")
    wanted_type = str(control_type or "").strip().casefold()
    try:
        controls = window.descendants()
    except Exception as exc:
        raise ScreenControlError(
            f"Could not read the controls of '{_window_title(window)}': {exc}"
        ) from exc
    candidates = []
    for control in controls:
        info = _control_info(control)
        if info is None:
            continue
        if wanted_type and info["control_type"].casefold() != wanted_type:
            continue
        candidates.append((control, info))
    folded = query.casefold()
    exact = [item for item in candidates if item[1]["name"].casefold() == folded]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ScreenControlError(_control_ambiguity(query, exact))
    partial = [item for item in candidates if folded in item[1]["name"].casefold()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise ScreenControlError(_control_ambiguity(query, partial))
    raise ScreenControlError(
        f"No control named '{query}' is visible in '{_window_title(window)}'. "
        "Run list_controls to see the exact names."
    )


def _control_ambiguity(query, matches):
    listed = ", ".join(
        f"'{info['name']}' ({info['control_type'] or 'unknown type'})"
        for _, info in matches[:MAX_CANDIDATES]
    )
    return (
        f"{len(matches)} controls match '{query}': {listed}. "
        "Pass control_type or a more specific name."
    )


def _looks_password(control):
    try:
        info = control.element_info
        element = getattr(info, "element", None)
        if element is not None:
            return bool(element.CurrentIsPassword)
    except Exception:
        pass
    try:
        flag = getattr(control, "is_password")
        return bool(flag() if callable(flag) else flag)
    except Exception:
        return False


def click_control(window, name, control_type=None):
    """Click one named control in an open window."""
    target = find_window(window)
    title = _window_title(target)
    _focus(target, title)
    control, info = _match_control(target, name, control_type)
    label = f"{info['name']} ({info['control_type'] or 'control'})"
    try:
        control.click_input()
    except Exception as exc:
        try:
            control.invoke()
        except Exception:
            raise ScreenControlError(
                f"Windows did not accept a click on {label} in '{title}': {exc}"
            ) from exc
        return f"Activated {label} in '{title}' through UI Automation."
    return f"Clicked {label} in '{title}'."


def set_control_text(window, name, text, control_type=None):
    """Replace the text of one named edit control; password fields are refused."""
    if not isinstance(text, str):
        raise ScreenControlError("Text must be a string.")
    target = find_window(window)
    title = _window_title(target)
    _focus(target, title)
    control, info = _match_control(target, name, control_type or "Edit")
    if _looks_password(control):
        raise ScreenControlError(
            "That control is a password field, so Himari will not type into it."
        )
    label = f"{info['name']} ({info['control_type'] or 'control'})"
    try:
        control.set_edit_text(text)
    except Exception as exc:
        try:
            control.click_input()
            from .input import press_keys, type_text

            press_keys("ctrl+a")
            type_text(text)
        except Exception as fallback:
            raise ScreenControlError(
                f"Windows did not accept text in {label} in '{title}': "
                f"{exc}; fallback failed: {fallback}"
            ) from fallback
        return f"Typed into {label} in '{title}'."
    return f"Set the text of {label} in '{title}'."
