"""Append the local image engine to the packaged Himari executable.

Usage:
    python embed_imagegen_payload.py --exe release/Himari.exe
    python embed_imagegen_payload.py --exe release/Himari.exe --allow-missing

The assets come from the managed install folder
(%USERPROFILE%/.himari/imagegen by default): sd-server, its DLLs and a
Stable Diffusion GGUF checkpoint. They are written as a ZIP archive after the
PyInstaller archive plus a fixed footer, which the app reads and unpacks on
first use.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

from himari import imagegen_payload

ROOT = Path(__file__).resolve().parent
DEFAULT_ASSETS = Path.home() / ".himari" / "imagegen"
SERVER_DIR = "server"
MODEL_DIR = "models"
CHUNK = 4 * 1024 * 1024


def _preferred_model(models_dir):
    models = sorted(models_dir.glob("*.gguf"))
    if not models:
        return None
    for token in ("q8_0", "q8", "q6", "q5", "q4"):
        for model in models:
            if token in model.name.casefold():
                return model
    return models[0]


def collect(assets):
    server = assets / SERVER_DIR
    models = assets / MODEL_DIR
    required_exe = server / "sd-server.exe"
    required_lib = server / "stable-diffusion.dll"
    missing = [path for path in (required_exe, required_lib) if not path.is_file()]
    if missing:
        raise SystemExit(
            "The local image engine is not installed. Missing: "
            + ", ".join(str(path) for path in missing)
            + f"\nInstall sd-server into {server} or rerun with --allow-missing."
        )
    model = _preferred_model(models)
    if model is None:
        raise SystemExit(
            f"No Stable Diffusion .gguf checkpoint found in {models}. "
            "Install one or rerun with --allow-missing."
        )
    server_files = [
        (path, path.relative_to(server).as_posix())
        for path in sorted(server.rglob("*"))
        if path.is_file()
    ]
    return server_files, model


def build_archive(destination, server_files, model):
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path, name in server_files:
            archive.write(path, f"{SERVER_DIR}/{name}")
        archive.write(
            model,
            f"{MODEL_DIR}/{model.name}",
            compress_type=zipfile.ZIP_STORED,
        )


def append(exe, archive_path):
    offset = exe.stat().st_size
    length = archive_path.stat().st_size
    with archive_path.open("rb") as source, exe.open("ab") as target:
        shutil.copyfileobj(source, target, CHUNK)
    with exe.open("ab") as target:
        target.write(imagegen_payload.FOOTER.pack(imagegen_payload.MAGIC, offset, length))
    return offset, length


def verify(exe, expected_size):
    location = imagegen_payload.locate(exe)
    if location is None:
        raise SystemExit("Embedded image engine footer is missing or corrupt.")
    with zipfile.ZipFile(exe) as archive:
        names = set(archive.namelist())
        for required in imagegen_payload.REQUIRED_SERVER:
            if f"{SERVER_DIR}/{required}" not in names:
                raise SystemExit(f"Embedded payload is missing {required}.")
        if not any(name.startswith(f"{MODEL_DIR}/") and name.endswith(".gguf") for name in names):
            raise SystemExit("Embedded payload is missing the checkpoint.")
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"Embedded payload is corrupt at {bad}.")
    if exe.stat().st_size < expected_size:
        raise SystemExit("Embedded executable is smaller than expected.")
    return location


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=ROOT / "release" / "Himari.exe")
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="leave the executable unchanged when the local image engine is absent",
    )
    options = parser.parse_args(argv)

    exe = options.exe.resolve()
    if not exe.is_file():
        raise SystemExit(f"Packaged executable not found: {exe}")
    if imagegen_payload.locate(exe) is not None:
        raise SystemExit(f"{exe} already contains an image engine payload.")

    try:
        server_files, model = collect(options.assets)
    except SystemExit:
        if options.allow_missing:
            print("Image engine assets are missing; built a chat-only executable.")
            return 0
        raise

    archive_path = exe.with_name(exe.name + ".imagegen-payload.zip")
    try:
        build_archive(archive_path, server_files, model)
        offset, length = append(exe, archive_path)
    finally:
        archive_path.unlink(missing_ok=True)

    verify(exe, offset + length + imagegen_payload.FOOTER.size)
    print(f"Bundled image engine: {len(server_files)} server file(s) + {model.name}")
    print(f"Payload offset {offset:,} bytes, length {length:,} bytes")
    print(f"Executable size: {exe.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
