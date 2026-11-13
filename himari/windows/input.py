"""Low-level Windows input injection used by the gated screen-control tools.

Every public function is a single, bounded action. The module never runs a
loop, never watches the keyboard, and refuses the Windows key so an agent
cannot reach system-level shortcuts. All calls are Windows-only and fail with
a clear error elsewhere.
"""

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger("himari.windows.input")

MAX_TEXT = 4000
MAX_KEYS = 8

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

WHEEL_DELTA = 120

_KEY_NAMES = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "back": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "menu": 0x12,
    "capslock": 0x14,
    "printscreen": 0x2C,
    "prtsc": 0x2C,
    "pause": 0x13,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "semicolon": 0xBA,
    "plus": 0xBB,
    "comma": 0xBC,
    "minus": 0xBD,
    "period": 0xBE,
    "slash": 0xBF,
    "tilde": 0xC0,
    "lbracket": 0xDB,
    "backslash": 0xDC,
    "rbracket": 0xDD,
    "quote": 0xDE,
}
for _index in range(1, 25):
    _KEY_NAMES[f"f{_index}"] = 0x70 + _index - 1
for _char in "abcdefghijklmnopqrstuvwxyz0123456789":
    _KEY_NAMES[_char] = ord(_char.upper())

_BLOCKED_KEYS = {
    "win",
    "windows",
    "lwin",
    "rwin",
    "cmd",
    "command",
    "meta",
    "super",
}


class ScreenInputError(RuntimeError):
    """Raised when Windows input cannot be sent."""


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32 = None
_dpi_ready = False


def _api():
    if sys.platform != "win32":
        raise ScreenInputError("Screen control is only available on Windows.")
    global _user32
    if _user32 is None:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        )
        _user32.SendInput.restype = wintypes.UINT
        _user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
        _user32.GetSystemMetrics.restype = ctypes.c_int
    _ensure_dpi_aware(_user32)
    return _user32


def _ensure_dpi_aware(user32):
    global _dpi_ready
    if _dpi_ready:
        return
    _dpi_ready = True
    try:
        setter = user32.SetProcessDpiAwarenessContext
        # PER_MONITOR_AWARE_V2 keeps click coordinates in physical pixels.
        if setter(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        log.debug("DPI awareness could not be set; coordinates may be scaled.")


def _send(events):
    user32 = _api()
    if not events:
        return
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        error = ctypes.get_last_error()
        raise ScreenInputError(
            f"Windows rejected the input event (sent {sent} of {len(events)}, "
            f"error {error})."
        )


def _key_event(vk=0, scan=0, flags=0):
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0),
    )


def _mouse_event(dx=0, dy=0, data=0, flags=0):
    return INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=0),
    )


def _key_code(name):
    key = str(name or "").strip().casefold()
    if not key:
        raise ScreenInputError("A key name is required.")
    if key in _BLOCKED_KEYS:
        raise ScreenInputError("The Windows key is not available to screen control.")
    if key in _KEY_NAMES:
        return _KEY_NAMES[key]
    raise ScreenInputError(f"Unknown key name: {name}")


def parse_keys(combo):
    """Split 'ctrl+shift+s' into validated virtual-key codes."""
    parts = [part for part in str(combo or "").split("+")]
    if not parts or any(not part.strip() for part in parts):
        raise ScreenInputError("Use a key combination such as ctrl+s.")
    if len(parts) > MAX_KEYS:
        raise ScreenInputError(f"Use at most {MAX_KEYS} keys in one combination.")
    return [_key_code(part) for part in parts]


def type_text(text):
    """Type literal text with Unicode key events; newlines and tabs are keys."""
    if not isinstance(text, str):
        raise ScreenInputError("Text must be a string.")
    if not text:
        raise ScreenInputError("There is no text to type.")
    if len(text) > MAX_TEXT:
        raise ScreenInputError(f"Text is limited to {MAX_TEXT} characters per action.")
    if "\x00" in text:
        raise ScreenInputError("Text contains a null character.")
    events = []
    total = 0
    for char in text:
        if char == "\r":
            continue
        if char == "\n":
            events.append(_key_event(vk=0x0D))
            events.append(_key_event(vk=0x0D, flags=KEYEVENTF_KEYUP))
        elif char == "\t":
            events.append(_key_event(vk=0x09))
            events.append(_key_event(vk=0x09, flags=KEYEVENTF_KEYUP))
        else:
            code = ord(char)
            if code > 0xFFFF:
                raise ScreenInputError("Text contains a character outside the BMP.")
            events.append(_key_event(scan=code, flags=KEYEVENTF_UNICODE))
            events.append(
                _key_event(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
            )
        total += 1
        if total >= 200:
            _send(events)
            events = []
            total = 0
    _send(events)


def press_keys(combo):
    """Press and release a key combination such as 'ctrl+s' or 'enter'."""
    codes = parse_keys(combo)
    events = []
    for code in codes[:-1]:
        events.append(_key_event(vk=code))
    events.append(_key_event(vk=codes[-1]))
    events.append(_key_event(vk=codes[-1], flags=KEYEVENTF_KEYUP))
    for code in reversed(codes[:-1]):
        events.append(_key_event(vk=code, flags=KEYEVENTF_KEYUP))
    _send(events)


def _point(x, y):
    try:
        point = (int(x), int(y))
    except (TypeError, ValueError):
        raise ScreenInputError("Coordinates must be whole numbers.") from None
    user32 = _api()
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if width <= 0 or height <= 0:
        raise ScreenInputError("Windows did not report a usable screen size.")
    if not (left <= point[0] < left + width and top <= point[1] < top + height):
        raise ScreenInputError(
            f"Point ({point[0]}, {point[1]}) is outside the visible desktop."
        )
    return point


def _absolute_move(x, y):
    user32 = _api()
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1
    dx = round((x - left) * 65535 / width)
    dy = round((y - top) * 65535 / height)
    _send(
        [
            _mouse_event(
                dx=dx,
                dy=dy,
                flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            )
        ]
    )


def click_at(x, y, button="left", clicks=1):
    """Move the pointer to a desktop point and click it once or twice."""
    x, y = _point(x, y)
    if button not in ("left", "right", "middle"):
        raise ScreenInputError("Button must be left, right, or middle.")
    try:
        clicks = int(clicks)
    except (TypeError, ValueError):
        raise ScreenInputError("Clicks must be a whole number.") from None
    if clicks < 1 or clicks > 2:
        raise ScreenInputError("Clicks must be 1 or 2.")
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }[button]
    _absolute_move(x, y)
    events = []
    for _ in range(clicks):
        events.append(_mouse_event(flags=down))
        events.append(_mouse_event(flags=up))
    _send(events)


def scroll_screen(amount, x=None, y=None):
    """Scroll the wheel at the pointer, or at a given desktop point."""
    try:
        notches = int(amount)
    except (TypeError, ValueError):
        raise ScreenInputError("Scroll amount must be a whole number.") from None
    if notches == 0:
        raise ScreenInputError("Scroll amount cannot be zero.")
    if abs(notches) > 20:
        raise ScreenInputError("Scroll at most 20 notches per action.")
    if (x is None) != (y is None):
        raise ScreenInputError("Provide both x and y, or neither.")
    if x is not None:
        x, y = _point(x, y)
        _absolute_move(x, y)
    _send([_mouse_event(data=notches * WHEEL_DELTA, flags=MOUSEEVENTF_WHEEL)])
