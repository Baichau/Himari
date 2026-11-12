import io
import sys
import zipfile
from types import SimpleNamespace

from PIL import Image

from himari import attachments


def test_text_attachment_is_read_and_cleaned(tmp_path):
    path = tmp_path / "notes.md"
    path.write_bytes("line one\r\nline two\x01".encode("utf-8"))

    attachment = attachments.load_attachment(path)

    assert attachment.ok
    assert attachment.kind == "text"
    assert "line one\nline two" in attachment.text
    assert "\x01" not in attachment.text
    assert "text" in attachment.label()


def test_missing_and_empty_files_report_an_error_instead_of_raising(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")

    missing = attachments.load_attachment(tmp_path / "nope.txt")
    blank = attachments.load_attachment(empty)

    assert not missing.ok and "no longer exists" in missing.error
    assert not blank.ok and "empty" in blank.error.lower()


def test_oversized_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_FILE_BYTES", 16)
    path = tmp_path / "big.txt"
    path.write_text("x" * 32, encoding="utf-8")

    attachment = attachments.load_attachment(path)

    assert not attachment.ok
    assert "limit" in attachment.error


def test_binary_data_with_a_text_extension_is_rejected(tmp_path):
    path = tmp_path / "fake.txt"
    path.write_bytes(b"abc\x00\x01def")

    attachment = attachments.load_attachment(path)

    assert not attachment.ok
    assert "binary" in attachment.error.lower()


def test_image_attachment_is_in_memory_and_downscaled(tmp_path):
    path = tmp_path / "wide.png"
    Image.new("RGB", (2400, 1200), (200, 30, 90)).save(path)

    attachment = attachments.load_attachment(path)

    assert attachment.ok and attachment.is_image
    with Image.open(io.BytesIO(attachment.image_bytes)) as image:
        assert max(image.size) <= attachments.MAX_IMAGE_EDGE
    assert attachment.thumbnail.startswith("data:image/png;base64,")
    assert attachment.path == str(path)


def test_screenshot_attachment_stays_in_memory():
    image = Image.new("RGB", (800, 600), (10, 20, 30))

    attachment = attachments.image_attachment(
        image, name="screen-1.png", meta={"source": "screen"}
    )

    assert attachment.ok and attachment.is_image
    assert attachment.meta["source"] == "screen"
    assert attachment.vision_b64()


def test_docx_text_is_extracted(tmp_path):
    path = tmp_path / "report.docx"
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Quarterly '
        "report</w:t></w:r></w:p><w:p><w:r><w:t>Revenue up 12%</w:t></w:r>"
        "</w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)

    attachment = attachments.load_attachment(path)

    assert attachment.ok
    assert attachment.kind == "docx"
    assert "Quarterly report" in attachment.text
    assert "Revenue up 12%" in attachment.text


def test_docx_that_is_not_a_zip_reports_an_error(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")

    attachment = attachments.load_attachment(path)

    assert not attachment.ok
    assert "damaged" in attachment.error


def test_spreadsheet_cells_are_extracted(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "budget.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Plan"
    sheet.append(["Item", "Cost"])
    sheet.append(["Rent", 900])
    workbook.save(path)

    attachment = attachments.load_attachment(path)

    assert attachment.ok and attachment.kind == "sheet"
    assert "[Sheet: Plan]" in attachment.text
    assert "Rent\t900" in attachment.text


def test_pdf_pages_are_extracted(monkeypatch, tmp_path):
    class Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class Reader:
        def __init__(self, _path):
            self.is_encrypted = False
            self.pages = [Page("first page"), Page("second page")]

    monkeypatch.setitem(
        sys.modules, "pypdf", SimpleNamespace(PdfReader=Reader)
    )
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4 fake")

    attachment = attachments.load_attachment(path)

    assert attachment.ok and attachment.kind == "pdf"
    assert attachment.meta["pages"] == 2
    assert "[Page 1]\nfirst page" in attachment.text


def test_scanned_pdf_without_text_asks_for_a_screenshot(monkeypatch, tmp_path):
    class Reader:
        def __init__(self, _path):
            self.is_encrypted = False
            self.pages = []

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=Reader))
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 fake")

    attachment = attachments.load_attachment(path)

    assert not attachment.ok
    assert "screenshot" in attachment.error.lower()


def test_attachment_text_block_is_labelled_and_bounded(tmp_path):
    first = attachments.load_attachment(
        _write(tmp_path / "a.txt", "alpha")
    )
    second = attachments.load_attachment(
        _write(tmp_path / "b.txt", "beta")
    )

    block = attachments.attachment_text_block([first, second])

    assert "--- BEGIN ATTACHMENT: a.txt" in block
    assert "--- END ATTACHMENT: b.txt ---" in block
    assert "alpha" in block and "beta" in block


def test_attachment_text_block_obeys_the_total_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_TOTAL_TEXT_CHARS", 8)
    first = attachments.load_attachment(_write(tmp_path / "a.txt", "x" * 8))
    second = attachments.load_attachment(_write(tmp_path / "b.txt", "y" * 8))

    block = attachments.attachment_text_block([first, second])

    assert "y" * 8 not in block
    assert "remaining attachments omitted" in block


def test_failed_attachment_is_reported_in_the_prompt_block():
    failed = attachments.Attachment(name="secret.bin", kind="binary", error="denied")

    block = attachments.attachment_text_block([failed])

    assert "secret.bin: could not be read (denied)" in block


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path
