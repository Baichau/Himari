import os
import time
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from himari import single_instance


def test_single_instance_lets_only_one_instance_listen(monkeypatch):
    app = QApplication.instance() or QApplication([])
    name = f"himari-test-{uuid.uuid4().hex}"
    monkeypatch.setattr(single_instance, "_server_name", lambda: name)

    first = single_instance.SingleInstance(app)
    assert first.acquire() is True
    seen = []
    first.activated.connect(lambda: seen.append(True))

    second = single_instance.SingleInstance(app)
    assert second.acquire() is False

    deadline = time.monotonic() + 2
    while not seen and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert seen
    if first._server is not None:
        first._server.close()
