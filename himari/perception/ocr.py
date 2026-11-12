"""Local Windows OCR built on the existing himari.screen winrt pipeline.

Only structured text leaves this module; images are closed by the underlying
pipeline and failures never produce invented content.
"""

from ..screen import ocr as _windows_ocr


class OcrError(RuntimeError):
    """Windows OCR failed; no screen content could be extracted."""


def extract_text(image):
    """Return the readable lines of an image.

    The underlying pipeline closes the image. Raises OcrError on failure.
    """
    try:
        text = _windows_ocr(image)
    except Exception as exc:
        raise OcrError(f"Windows screen text recognition failed: {exc}") from exc
    return [line.strip() for line in text.splitlines() if line.strip()]