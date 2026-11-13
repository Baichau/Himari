import logging
from logging.handlers import RotatingFileHandler

from .paths import user_data_dir


def log_file_path():
    return user_data_dir() / "logs" / "himari.log"


def configure_logging():
    log_path = log_file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers[:]:
        if getattr(handler, "_himari_file_handler", False):
            root.removeHandler(handler)
            handler.close()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    file_handler._himari_file_handler = True
    root.addHandler(file_handler)
    return log_path
