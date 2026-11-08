# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

try:
    import emoji
except ImportError as exc:
    raise RuntimeError(
        "The required 'emoji' package is missing. Run setup_windows.bat before building."
    ) from exc

datas = [('config.example.json', '.'), ('THIRD_PARTY_NOTICES.txt', '.')]
speech_model = Path(SPECPATH) / 'models' / 'large-v3-turbo'
if (speech_model / 'model.bin').is_file():
    required_model_files = [
        'config.json', 'model.bin', 'preprocessor_config.json',
        'tokenizer.json', 'vocabulary.json',
    ]
    missing_model_files = [name for name in required_model_files if not (speech_model / name).is_file()]
    if missing_model_files:
        raise FileNotFoundError(f"Incomplete bundled speech model: {', '.join(missing_model_files)}")
    datas += [
        (str(speech_model / name), 'models/large-v3-turbo')
        for name in required_model_files
    ]
piper_voice = Path(SPECPATH) / 'models' / 'piper-voices'
required_voice_files = ['en_US-amy-medium.onnx', 'en_US-amy-medium.onnx.json']
missing_voice_files = [name for name in required_voice_files if not (piper_voice / name).is_file()]
if missing_voice_files:
    raise FileNotFoundError(f"Incomplete bundled English voice: {', '.join(missing_voice_files)}")
datas += [
    (str(piper_voice / name), 'voices')
    for name in required_voice_files
]
binaries = []
hiddenimports = [
    'PySide6.QtSvg',
    'keyboard',
    'winrt.windows.foundation',
    'winrt.windows.globalization',
    'winrt.windows.graphics.imaging',
    'winrt.windows.media.ocr',
    'winrt.windows.storage.streams',
]
datas += collect_data_files('_sounddevice_data')
tmp_ret = collect_all('piper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('emoji')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('av')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['himari_launcher.py'],
    pathex=[],
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Himari',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Himari',
)
