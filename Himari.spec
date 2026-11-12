# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve()
datas = [
    (str(ROOT / "config.example.json"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.txt"), "."),
]

avatar_dir = ROOT / "himari" / "avatar_assets"
if avatar_dir.is_dir():
    datas.extend(
        (str(asset), "himari/avatar_assets")
        for asset in sorted(avatar_dir.glob("*.png"))
    )

web_assets_dir = ROOT / "himari" / "web_assets"
if web_assets_dir.is_dir():
    for asset in sorted(web_assets_dir.rglob("*")):
        if not asset.is_file():
            continue
        relative = asset.relative_to(web_assets_dir)
        target = "himari/web_assets"
        if relative.parent != Path("."):
            target = f"himari/web_assets/{relative.parent.as_posix()}"
        datas.append((str(asset), target))

models_dir = ROOT / "models"
if models_dir.is_dir():
    for model_dir in sorted(models_dir.iterdir()):
        if not model_dir.is_dir() or model_dir.name == "piper-voices":
            continue
        if not (model_dir / "model.bin").is_file() or not (model_dir / "config.json").is_file():
            raise FileNotFoundError(
                f"Incomplete Faster-Whisper model directory: {model_dir}"
            )
        datas.extend(
            (str(model_file), f"models/{model_dir.name}")
            for model_file in sorted(model_dir.rglob("*"))
            if model_file.is_file()
        )

voice_dir = models_dir / "piper-voices"
if voice_dir.is_dir():
    voice_models = sorted(voice_dir.glob("*.onnx"))
    if not voice_models:
        raise FileNotFoundError(
            f"No Piper .onnx voice models found in {voice_dir}"
        )
    for model in voice_models:
        metadata = model.with_suffix(model.suffix + ".json")
        if not metadata.is_file():
            raise FileNotFoundError(
                f"Missing Piper voice metadata file: {metadata}"
            )
        datas.append((str(model), "voices"))
        datas.append((str(metadata), "voices"))

binaries = []
hiddenimports = [
    "keyboard",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "markdown_it",
    "pypdf",
    "openpyxl",
    "httpx",
    "winrt.windows.foundation",
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.media.ocr",
    "winrt.windows.storage.streams",
]

datas += collect_data_files("_sounddevice_data")
for package in (
    "piper",
    "emoji",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "winrt",
    "playwright",
):
    collected_datas, collected_binaries, collected_imports = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_imports

a = Analysis(
    [str(ROOT / "himari_launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ONEFILE: binaries and datas go inside the EXE, and there is no COLLECT block.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Himari",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
