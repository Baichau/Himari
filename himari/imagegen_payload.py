"""Local image engine assets embedded in the packaged executable.

The release build appends a ZIP archive with ``sd-server`` and the Stable
Diffusion checkpoint after the PyInstaller archive, then a small footer.
Keeping the gigabytes outside the bootloader archive means launching Himari
stays fast: the assets are unpacked once, the first time image generation is
used, into the persistent user data folder.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath

log = logging.getLogger("himari.imagegen.payload")

MAGIC = b"HMRPAY01"
FOOTER = struct.Struct("<8sQQ")
ALLOWED_ROOTS = ("server", "models")
REQUIRED_SERVER = ("sd-server.exe", "stable-diffusion.dll")


class PayloadError(RuntimeError):
    pass


def executable_path():
    return Path(sys.executable)


def locate(exe_path=None):
    """Return the (offset, length) of the embedded payload, or None."""
    path = Path(exe_path) if exe_path else executable_path()
    try:
        size = path.stat().st_size
        if size <= FOOTER.size:
            return None
        with path.open("rb") as handle:
            handle.seek(size - FOOTER.size)
            raw = handle.read(FOOTER.size)
    except OSError:
        return None
    if len(raw) != FOOTER.size:
        return None
    magic, offset, length = FOOTER.unpack(raw)
    if magic != MAGIC or offset <= 0 or length <= 0:
        return None
    if offset + length + FOOTER.size != size:
        return None
    return offset, length


def read_footer(exe_path=None):
    """Return the parsed footer without validating the payload itself."""
    path = Path(exe_path) if exe_path else executable_path()
    try:
        size = path.stat().st_size
        if size <= FOOTER.size:
            return None
        with path.open("rb") as handle:
            handle.seek(size - FOOTER.size)
            raw = handle.read(FOOTER.size)
    except OSError:
        return None
    if len(raw) != FOOTER.size:
        return None
    magic, offset, length = FOOTER.unpack(raw)
    if magic != MAGIC:
        return None
    return offset, length


def _entries(archive):
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = PurePosixPath(info.filename.replace("\\", "/")).parts
        if not parts or parts[0] not in ALLOWED_ROOTS:
            continue
        if any(part in ("", ".", "..") for part in parts) or ":" in parts[0]:
            raise PayloadError(f"Unsafe path in the image engine payload: {info.filename}")
        yield info, parts


def names(exe_path=None):
    """List the asset names in the embedded payload without unpacking."""
    location = locate(exe_path)
    if location is None:
        return []
    exe = Path(exe_path) if exe_path else executable_path()
    with zipfile.ZipFile(exe) as archive:
        return ["/".join(parts) for _, parts in _entries(archive)]


def has_required_assets(exe_path=None):
    found = set(names(exe_path))
    return bool(found) and all(
        any(name == f"server/{required}" for name in found)
        for required in REQUIRED_SERVER
    )


def extract(target_root, exe_path=None):
    """Unpack the embedded image engine into ``target_root``.

    Existing files with the expected size are left untouched, so a retry
    after a partial failure only rewrites what is missing.
    """
    location = locate(exe_path)
    if location is None:
        return []
    exe = Path(exe_path) if exe_path else executable_path()
    root = Path(target_root)
    written = []
    with zipfile.ZipFile(exe) as archive:
        for info, parts in _entries(archive):
            destination = root.joinpath(*parts)
            if (
                destination.is_file()
                and destination.stat().st_size == info.file_size
            ):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            part = destination.with_name(destination.name + ".part")
            try:
                with archive.open(info) as source, part.open("wb") as output:
                    while True:
                        chunk = source.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                os.replace(part, destination)
            except OSError as exc:
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    pass
                raise PayloadError(
                    f"Could not unpack {destination}: {exc}"
                ) from exc
            written.append(destination)
    return written
