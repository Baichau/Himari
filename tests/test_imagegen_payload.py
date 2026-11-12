import zipfile

import pytest

from himari import imagegen_payload


def _packaged_executable(path, entries):
    prefix = b"PyInstaller archive" * 64
    payload = path.with_name("payload.zip")
    with zipfile.ZipFile(payload, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with path.open("wb") as handle:
        handle.write(prefix)
        handle.write(payload.read_bytes())
    length = payload.stat().st_size
    with path.open("ab") as handle:
        handle.write(
            imagegen_payload.FOOTER.pack(
                imagegen_payload.MAGIC, len(prefix), length
            )
        )
    payload.unlink()
    return path


def test_locate_returns_the_appended_payload(tmp_path):
    exe = _packaged_executable(
        tmp_path / "Himari.exe",
        {"server/sd-server.exe": b"bin", "models/model.gguf": b"weights"},
    )

    location = imagegen_payload.locate(exe)

    assert location is not None
    offset, length = location
    assert offset == len(b"PyInstaller archive" * 64)
    assert length > 0


def test_locate_rejects_a_missing_or_damaged_footer(tmp_path):
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"no payload here")

    assert imagegen_payload.locate(plain) is None

    exe = _packaged_executable(
        tmp_path / "Himari.exe", {"server/sd-server.exe": b"bin"}
    )
    data = exe.read_bytes()
    exe.write_bytes(data[:-1])

    assert imagegen_payload.locate(exe) is None


def test_names_report_the_embedded_assets(tmp_path):
    exe = _packaged_executable(
        tmp_path / "Himari.exe",
        {
            "server/sd-server.exe": b"bin",
            "server/stable-diffusion.dll": b"dll",
            "models/model.gguf": b"weights",
            "other/ignored.txt": b"nope",
        },
    )

    names = imagegen_payload.names(exe)

    assert "server/sd-server.exe" in names
    assert "server/stable-diffusion.dll" in names
    assert "models/model.gguf" in names
    assert "other/ignored.txt" not in names
    assert imagegen_payload.has_required_assets(exe)


def test_has_required_assets_needs_the_server_and_library(tmp_path):
    exe = _packaged_executable(
        tmp_path / "Himari.exe", {"server/sd-server.exe": b"bin"}
    )

    assert imagegen_payload.has_required_assets(exe) is False


def test_extract_unpacks_assets_and_skips_existing_files(tmp_path):
    exe = _packaged_executable(
        tmp_path / "Himari.exe",
        {
            "server/sd-server.exe": b"binary",
            "server/ggml.dll": b"library",
            "models/model.gguf": b"weights",
        },
    )
    target = tmp_path / "imagegen"

    written = imagegen_payload.extract(target, exe)

    assert len(written) == 3
    assert (target / "server" / "sd-server.exe").read_bytes() == b"binary"
    assert (target / "models" / "model.gguf").read_bytes() == b"weights"

    assert imagegen_payload.extract(target, exe) == []
    (target / "server" / "ggml.dll").write_bytes(b"short")
    assert len(imagegen_payload.extract(target, exe)) == 1
    assert (target / "server" / "ggml.dll").read_bytes() == b"library"


def test_extract_refuses_path_traversal(tmp_path):
    exe = _packaged_executable(
        tmp_path / "Himari.exe", {"server/../escape.dll": b"bad"}
    )

    with pytest.raises(imagegen_payload.PayloadError):
        imagegen_payload.extract(tmp_path / "imagegen", exe)
    assert not (tmp_path / "escape.dll").exists()


def test_extract_without_a_payload_returns_nothing(tmp_path):
    plain = tmp_path / "plain.exe"
    plain.write_bytes(b"nothing embedded")

    assert imagegen_payload.extract(tmp_path / "imagegen", plain) == []
