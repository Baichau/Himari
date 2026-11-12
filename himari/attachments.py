"""User-attached files and screenshots.

Files are read only after the user explicitly attaches them. Text is bounded;
images stay in memory for the local vision model; nothing is uploaded and
nothing is written to disk.
"""

from __future__ import annotations

import base64
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageOps

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 8
MAX_TEXT_CHARS = 60_000
MAX_TOTAL_TEXT_CHARS = 120_000
MAX_IMAGE_EDGE = 1600
MAX_PDF_PAGES = 60
MAX_SHEET_ROWS = 200
MAX_SHEET_COLUMNS = 30

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
}
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".lua",
    ".pl",
    ".r",
    ".m",
    ".sql",
    ".sh",
    ".bash",
    ".ps1",
    ".bat",
    ".cmd",
    ".dockerfile",
    ".gitignore",
    ".env.example",
}
_DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class AttachmentError(ValueError):
    pass


@dataclass
class Attachment:
    name: str
    kind: str
    size: int = 0
    path: str | None = None
    text: str = ""
    image_bytes: bytes | None = None
    mime: str = "image/png"
    thumbnail: str = ""
    error: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.error

    @property
    def is_image(self):
        return self.kind == "image" and bool(self.image_bytes)

    def vision_b64(self):
        if not self.image_bytes:
            return ""
        return base64.b64encode(self.image_bytes).decode("ascii")

    def label(self):
        size = _human_size(self.size)
        if self.kind == "image":
            description = "image"
        elif self.kind == "pdf":
            pages = self.meta.get("pages")
            description = f"PDF, {pages} pages" if pages else "PDF"
        elif self.kind == "docx":
            description = "Word document"
        elif self.kind == "sheet":
            description = "spreadsheet"
        else:
            description = "text"
        return f"{self.name} · {description} · {size}"


def _human_size(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024 or unit == "GB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{number:.1f} GB"


def _clean_text(text):
    return _CONTROL.sub("", str(text).replace("\r\n", "\n").replace("\r", "\n")).strip()


def _clip(text, limit=MAX_TEXT_CHARS):
    text = _clean_text(text)
    if len(text) > limit:
        return text[:limit] + f"\n…[truncated {len(text) - limit} characters]"
    return text


def _decode_bytes(data):
    if b"\x00" in data[:4096]:
        raise AttachmentError("This looks like a binary file, not text.")
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AttachmentError("The file is not readable as UTF-8 or Windows text.")


def _load_text(path):
    data = path.read_bytes()
    return _clip(_decode_bytes(data))


def _load_image(path):
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        if image.width > MAX_IMAGE_EDGE or image.height > MAX_IMAGE_EDGE:
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
        buffer = io.BytesIO()
        has_alpha = image.getextrema()[3][0] < 255
        if has_alpha:
            image.save(buffer, format="PNG", optimize=True)
            mime = "image/png"
        else:
            image.convert("RGB").save(buffer, format="JPEG", quality=88, optimize=True)
            mime = "image/jpeg"
        thumbnail = _thumbnail(image)
        return buffer.getvalue(), mime, thumbnail


def _thumbnail(image, edge=96):
    preview = image.copy()
    preview.thumbnail((edge, edge), Image.LANCZOS)
    buffer = io.BytesIO()
    preview.convert("RGBA").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _load_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise AttachmentError(
            "PDF reading is unavailable in this build. Convert the file to text."
        ) from exc
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise AttachmentError("The PDF is password protected; Himari cannot read it.")
    pages = []
    for index, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            pages.append(f"[Page {index}]\n{text.strip()}")
    if not pages:
        raise AttachmentError(
            "No selectable text was found in the PDF; it may be a scan. "
            "Attach a screenshot of the page instead."
        )
    return _clip("\n\n".join(pages)), {"pages": len(reader.pages)}


def _load_docx(path):
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise AttachmentError("The Word document is damaged or not a .docx file.") from exc
    root = ElementTree.fromstring(xml)
    paragraphs = []
    for paragraph in root.iter(f"{_DOCX_NS}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_DOCX_NS}t"))
        if text.strip():
            paragraphs.append(text.strip())
    if not paragraphs:
        raise AttachmentError("The Word document contains no readable text.")
    return _clip("\n".join(paragraphs))


def _load_sheet(path):
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise AttachmentError(
            "Spreadsheet reading is unavailable in this build. Export the sheet as CSV."
        ) from exc
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise AttachmentError(f"Could not open the spreadsheet: {exc}") from exc
    sections = []
    try:
        for sheet in workbook.worksheets[:5]:
            sections.append(f"[Sheet: {sheet.title}]")
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= MAX_SHEET_ROWS:
                    sections.append("…[more rows truncated]")
                    break
                values = [
                    "" if value is None else str(value)
                    for value in row[:MAX_SHEET_COLUMNS]
                ]
                if any(value.strip() for value in values):
                    sections.append("\t".join(values).rstrip())
    finally:
        workbook.close()
    if len(sections) <= 1:
        raise AttachmentError("The spreadsheet contains no readable cells.")
    return _clip("\n".join(sections))


def load_attachment(path):
    """Read one user-selected file. Failures are returned, never raised."""
    try:
        resolved = Path(path).expanduser()
        if not resolved.is_file():
            raise AttachmentError("The file no longer exists.")
        size = resolved.stat().st_size
        if size <= 0:
            raise AttachmentError("The file is empty.")
        if size > MAX_FILE_BYTES:
            raise AttachmentError(
                f"The file is {_human_size(size)}; the limit is "
                f"{_human_size(MAX_FILE_BYTES)} per attachment."
            )
        suffix = resolved.suffix.casefold()
        attachment = Attachment(
            name=resolved.name,
            kind="binary",
            size=size,
            path=str(resolved),
        )
        if suffix in IMAGE_EXTENSIONS:
            image_bytes, mime, thumbnail = _load_image(resolved)
            attachment.kind = "image"
            attachment.image_bytes = image_bytes
            attachment.mime = mime
            attachment.thumbnail = thumbnail
        elif suffix == ".pdf":
            attachment.kind = "pdf"
            attachment.text, attachment.meta = _load_pdf(resolved)
        elif suffix == ".docx":
            attachment.kind = "docx"
            attachment.text = _load_docx(resolved)
        elif suffix in {".xlsx", ".xlsm"}:
            attachment.kind = "sheet"
            attachment.text = _load_sheet(resolved)
        else:
            attachment.kind = "text"
            attachment.text = _load_text(resolved)
        return attachment
    except AttachmentError as exc:
        return Attachment(
            name=Path(str(path)).name or "attachment",
            kind="binary",
            error=str(exc),
        )
    except OSError as exc:
        return Attachment(
            name=Path(str(path)).name or "attachment",
            kind="binary",
            error=f"Could not read the file: {exc}",
        )
    except Exception as exc:
        return Attachment(
            name=Path(str(path)).name or "attachment",
            kind="binary",
            error=f"Could not use this file: {exc}",
        )


def image_attachment(image, name="screen.png", meta=None):
    """Build an in-memory image attachment (used for one-shot screenshots)."""
    image = ImageOps.exif_transpose(image).convert("RGBA")
    if image.width > MAX_IMAGE_EDGE or image.height > MAX_IMAGE_EDGE:
        image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    attachment = Attachment(
        name=name,
        kind="image",
        size=len(buffer.getvalue()),
        image_bytes=buffer.getvalue(),
        mime="image/png",
        thumbnail=_thumbnail(image),
        meta=dict(meta or {}),
    )
    return attachment


def attachment_text_block(attachments):
    """Build bounded, clearly-labelled text for non-image attachments."""
    blocks = []
    total = 0
    for attachment in attachments or []:
        if not isinstance(attachment, Attachment) or attachment.is_image:
            continue
        if not attachment.ok:
            blocks.append(
                f"--- {attachment.name}: could not be read ({attachment.error}) ---"
            )
            continue
        remaining = MAX_TOTAL_TEXT_CHARS - total
        if remaining <= 0:
            blocks.append("…[remaining attachments omitted: context limit reached]")
            break
        text = attachment.text[:remaining]
        total += len(text)
        blocks.append(
            f"--- BEGIN ATTACHMENT: {attachment.name} ({attachment.label()}) ---\n"
            f"{text}\n--- END ATTACHMENT: {attachment.name} ---"
        )
    return "\n\n".join(blocks)


def attachment_summary(attachments):
    parts = []
    for attachment in attachments or []:
        if not isinstance(attachment, Attachment):
            continue
        parts.append(attachment.name if attachment.ok else f"{attachment.name} (error)")
    return ", ".join(parts)


def attachment_chips_html(attachments):
    chips = []
    for attachment in attachments or []:
        name = str(getattr(attachment, "name", "") or "")
        if not name:
            continue
        preview = ""
        thumbnail = getattr(attachment, "thumbnail", "")
        if thumbnail:
            preview = (
                f'<img class="chip-thumb" src="{html.escape(thumbnail, quote=True)}" '
                'alt="">'
            )
        chips.append(
            f'<span class="chip">{preview}{html.escape(name)}</span>'
        )
    if not chips:
        return ""
    return '<div class="chips">' + "".join(chips) + "</div>"
