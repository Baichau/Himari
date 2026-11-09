import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from himari.avatar import AvatarWidget, FloatingAvatarWindow


def _app():
    return QApplication.instance() or QApplication([])


def test_avatar_without_art_displays_an_explicit_placeholder(tmp_path):
    _app()
    avatar = AvatarWidget(asset_dirs=[tmp_path])

    assert avatar.state == "idle"
    assert "Avatar art not installed" in avatar.text()
    assert "AVATAR_GUIDE.md" in avatar.text()

    avatar.set_state("speaking")
    assert avatar.state == "speaking"
    assert "Avatar art not installed" in avatar.text()


def test_avatar_uses_state_sprites_and_animated_speaking_frames(tmp_path):
    _app()
    from PySide6.QtGui import QPixmap

    for name in ("idle.png", "speaking_01.png", "speaking_02.png"):
        pixmap = QPixmap(16, 16)
        pixmap.fill()
        assert pixmap.save(str(tmp_path / name))

    avatar = AvatarWidget(asset_dirs=[tmp_path])
    assert avatar.pixmap() is not None
    avatar.set_state("speaking")

    assert avatar.state == "speaking"
    assert len(avatar._frames) == 2
    assert avatar._animation.isActive()

    avatar.set_state("idle")
    assert not avatar._animation.isActive()
    avatar._blink.stop()


def test_floating_avatar_window_can_be_resized(tmp_path):
    _app()
    window = FloatingAvatarWindow(asset_dirs=[tmp_path])
    window.set_avatar_size(320, 360)

    assert window.size().width() == 320
    assert window.size().height() == 360
    window.close()
