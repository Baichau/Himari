"""Turn unhandled exceptions and Qt warnings into log entries."""

import logging
import sys
import threading

log = logging.getLogger("himari.crash")

_reported = False


def install(app=None):
    """Install Python, thread, and Qt message hooks. Safe to call more than once."""
    previous = sys.excepthook

    def handle(exc_type, exc_value, exc_tb):
        if exc_type is KeyboardInterrupt:
            previous(exc_type, exc_value, exc_tb)
            return
        log.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        _report(app, exc_value)

    sys.excepthook = handle
    threading.excepthook = _thread_hook

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception as exc:
        log.debug("Qt message handler unavailable: %s", exc)
        return
    qInstallMessageHandler(lambda mode, context, message: _qt_handler(mode, message, QtMsgType))


def _thread_hook(args):
    log.critical(
        "Unhandled exception in thread %s",
        getattr(args.thread, "name", "unknown"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def _report(app, error):
    global _reported
    if _reported:
        return
    _reported = True
    from .paths import user_data_dir

    message = (
        f"Something went wrong: {error}\n\nDetails were written to:\n"
        f"{user_data_dir() / 'logs' / 'himari.log'}"
    )
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        application = app or QApplication.instance()
        if application is None:
            print(message, file=sys.stderr)
            return
        QMessageBox.critical(None, "Himari hit a problem", message)
    except Exception:
        print(message, file=sys.stderr)


def _qt_handler(mode, message, message_type):
    level = {
        message_type.QtDebugMsg: logging.DEBUG,
        message_type.QtInfoMsg: logging.INFO,
        message_type.QtWarningMsg: logging.WARNING,
        message_type.QtCriticalMsg: logging.ERROR,
        message_type.QtFatalMsg: logging.CRITICAL,
    }.get(mode, logging.INFO)
    log.log(level, "Qt: %s", message)
