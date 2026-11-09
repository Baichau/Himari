import os
from pathlib import Path
import shutil
import sys

from himari.paths import user_data_dir

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"
WHISPER_MODEL_PREFERENCE = (
    "large-v3-turbo",
    "large-v3",
    "distil-large-v3",
    "large",
    "medium",
    "small",
    "base",
    "base.en",
    "tiny",
    "tiny.en",
)
VOICE_PREFERENCE = ("en_US-amy-medium", "en_US-lessac-medium")


def _is_whisper_model(path):
    return (path / "config.json").is_file() and (path / "model.bin").is_file()


def _cached_model_snapshots(model_name):
    cache = Path(
        os.environ.get(
            "HF_HUB_CACHE",
            Path.home() / ".cache" / "huggingface" / "hub",
        )
    )
    repositories = ["Systran"]
    if model_name == "large-v3-turbo":
        repositories.insert(0, "mobiuslabsgmbh")
    for owner in repositories:
        snapshots = (
            cache
            / f"models--{owner}--faster-whisper-{model_name}"
            / "snapshots"
        )
        if snapshots.is_dir():
            for snapshot in sorted(snapshots.iterdir(), reverse=True):
                if snapshot.is_dir() and _is_whisper_model(snapshot):
                    yield snapshot


def stage_whisper_model():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for model_name in WHISPER_MODEL_PREFERENCE:
        destination = MODELS_DIR / model_name
        if destination.exists():
            if not _is_whisper_model(destination):
                raise RuntimeError(
                    f"Existing local speech model is incomplete: {destination}"
                )
            print(f"Using already-staged Faster-Whisper model: {destination}")
            return model_name

    for model_name in WHISPER_MODEL_PREFERENCE:
        for snapshot in _cached_model_snapshots(model_name):
            destination = MODELS_DIR / model_name
            shutil.copytree(snapshot, destination)
            if not _is_whisper_model(destination):
                raise RuntimeError(f"Could not stage a usable model from {snapshot}")
            print(f"Staged local Faster-Whisper model: {destination}")
            return model_name

    print(
        "WARNING: no complete local Faster-Whisper model was found. "
        "The packaged app will report speech recognition unavailable."
    )
    return None


def _voice_sources():
    yield MODELS_DIR / "piper-voices"
    yield user_data_dir() / "voices"


def stage_piper_voice():
    destination_dir = MODELS_DIR / "piper-voices"
    destination_dir.mkdir(parents=True, exist_ok=True)

    def available_names(directory):
        return {
            model.stem
            for model in directory.glob("*.onnx")
            if model.with_suffix(model.suffix + ".json").is_file()
        }

    present = available_names(destination_dir)
    if present:
        print(f"Using already-staged Piper voice(s): {', '.join(sorted(present))}")
        return sorted(present)

    for source_dir in _voice_sources():
        if not source_dir.is_dir():
            continue
        names = available_names(source_dir)
        if not names:
            continue
        voice_name = next(
            (name for name in VOICE_PREFERENCE if name in names),
            sorted(names)[0],
        )
        for suffix in (".onnx", ".onnx.json"):
            source = source_dir / f"{voice_name}{suffix}"
            shutil.copy2(source, destination_dir / source.name)
        print(f"Staged local Piper voice: {destination_dir / (voice_name + '.onnx')}")
        return [voice_name]

    print(
        "WARNING: no complete local Piper voice was found. "
        "The packaged app will report TTS unavailable."
    )
    return []


def main():
    model = stage_whisper_model()
    voices = stage_piper_voice()
    if model is None or not voices:
        print("Speech assets are optional for a chat-only build.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Could not prepare release assets: {exc}", file=sys.stderr)
        raise SystemExit(1)
