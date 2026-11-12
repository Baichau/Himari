import argparse
import ctypes
import logging
import os
import sys
import traceback

log = logging.getLogger("himari.bootstrap")


def _normalize_proxy_environment():
    # httpx (used by ollama at import time) cannot parse bracketed IPv6
    # NO_PROXY entries such as "[::1]" and treats them as an invalid port.
    names = ("NO_PROXY",) if os.name == "nt" else ("NO_PROXY", "no_proxy")
    for name in names:
        value = os.environ.get(name)
        if not value:
            continue
        entries = []
        rewritten = False
        for entry in value.split(","):
            entry = entry.strip()
            if len(entry) > 2 and entry[0] == "[" and entry[-1] == "]":
                entry = entry[1:-1]
                rewritten = True
            if entry:
                entries.append(entry)
        if rewritten:
            os.environ[name] = ",".join(entries)


def _show_error(message):
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                message,
                "Himari could not start",
                0x10,
            )
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="Himari")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="verify packaged dependencies and local runtime assets, then exit",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="with --self-test, open and close the main window once",
    )
    parser.add_argument(
        "--require-ollama",
        action="store_true",
        help="with --self-test, require Ollama and the configured model to be available",
    )
    options = parser.parse_args(argv)

    try:
        _normalize_proxy_environment()
        from .logging_setup import configure_logging

        log_path = configure_logging()
        log.info("Himari startup; log file: %s", log_path)
        if options.self_test:
            from .startup import self_test

            return self_test(
                open_gui=options.gui,
                require_ollama=options.require_ollama,
            )

        from .config import APP_DIR, DEFAULT_CONFIG_PATH

        APP_DIR.mkdir(parents=True, exist_ok=True)
        if not DEFAULT_CONFIG_PATH.is_file():
            raise RuntimeError(
                f"Packaged configuration template is missing: {DEFAULT_CONFIG_PATH}"
            )
        log.info("User data directory: %s", APP_DIR)
        from .ui import run

        run()
        return 0
    except Exception as exc:
        log.exception("Himari startup failed")
        _show_error(
            f"{exc}\n\nDetails were written to the Himari log file in "
            "your user data folder, if it was writable."
        )
        return 1
