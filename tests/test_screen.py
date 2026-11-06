from himari import screen


def test_ocr_uses_explicit_tesseract_path(tmp_path, monkeypatch):
    executable = tmp_path / "tesseract.exe"
    executable.touch()
    monkeypatch.setenv("TESSERACT_CMD", str(executable))
    monkeypatch.setattr(screen.pytesseract, "image_to_string", lambda image: "recognized text")
    assert screen.ocr(object()) == "recognized text"
    assert screen.pytesseract.pytesseract.tesseract_cmd == str(executable)
