from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

MODEL_ID = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
MODEL_DIR = Path(__file__).resolve().parent / "models" / "large-v3-turbo"
MAX_MODEL_BYTES = 3_000_000_000
MODEL_FILES = (
    "config.json",
    "model.bin",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
)


def main():
    model_info = HfApi(token=False).model_info(MODEL_ID, files_metadata=True)
    sizes = {file.rfilename: file.size or 0 for file in model_info.siblings}
    total_size = sum(sizes.get(name, 0) for name in MODEL_FILES)
    if any(name not in sizes for name in MODEL_FILES):
        raise RuntimeError(f"The speech model repository is missing required files: {MODEL_ID}")
    if total_size > MAX_MODEL_BYTES:
        raise RuntimeError(
            f"The speech model is {total_size:,} bytes, above the 3 GB standalone limit."
        )

    snapshot_download(
        repo_id=MODEL_ID,
        local_dir=str(MODEL_DIR),
        allow_patterns=list(MODEL_FILES),
        token=False,
    )
    missing = [name for name in MODEL_FILES if not (MODEL_DIR / name).is_file()]
    if missing:
        raise RuntimeError(f"Downloaded speech model is incomplete: {', '.join(missing)}")
    print(f"Prepared bundled speech model: {total_size / 1_000_000_000:.2f} GB")


if __name__ == "__main__":
    main()
