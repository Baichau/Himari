"""Keep one Himari instance per user and let a second launch raise the first."""

import hashlib
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .paths import user_data_dir

log = logging.getLogger("himari.single_instance")


def _server_name():
    identity = str(user_data_dir()).casefold()
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"himari-{digest}"


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = _server_name()
        self._server = None

    def acquire(self):
        """Return False when another instance was asked to show its window."""
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(400):
            probe.write(b"show")
            probe.flush()
            probe.waitForBytesWritten(400)
            probe.disconnectFromServer()
            probe.deleteLater()
            return False
        existing = QLocalServer(self)
        QLocalServer.removeServer(self._name)
        if not existing.listen(self._name):
            log.warning(
                "Could not create the single-instance server; continuing without it: %s",
                existing.errorString(),
            )
            existing.deleteLater()
            return True
        existing.newConnection.connect(self._accept)
        self._server = existing
        return True

    def _accept(self):
        while self._server is not None and self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            if connection is None:
                break
            connection.readAll()
            connection.disconnectFromServer()
            connection.deleteLater()
            self.activated.emit()
