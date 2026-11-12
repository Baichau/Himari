"""Errors raised by the Windows environment module."""


class WindowsEnvironmentError(RuntimeError):
    """Base error for Windows environment operations."""


class AppNotFoundError(WindowsEnvironmentError):
    """No installed application or open window matches the request."""


class AmbiguousAppError(WindowsEnvironmentError):
    """Several applications match; the caller must choose explicitly."""

    def __init__(self, requested, candidates):
        self.requested = requested
        self.candidates = list(candidates)
        listing = "; ".join(self.candidates[:8])
        super().__init__(
            f"More than one application matches '{requested}': {listing}. "
            "Specify the exact name; Himari will not guess."
        )