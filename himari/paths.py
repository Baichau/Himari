import os
from pathlib import Path
import sys


def user_data_dir():
    override = os.environ.get("HIMARI_HOME")
    if override and override.strip():
        return Path(override).expanduser().resolve()
    return Path.home() / ".himari"


def resource_dir():
    frozen_dir = getattr(sys, "_MEIPASS", None)
    if frozen_dir:
        return Path(frozen_dir)
    return Path(__file__).resolve().parent.parent
