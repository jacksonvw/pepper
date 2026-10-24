"""Shared pytest fixtures.

`QT_QPA_PLATFORM=offscreen` is set before any Qt import so the test suite
can run without a display server. We don't use pytest-qt — a raw
QApplication fixture + QSignalSpy from PySide6 is enough.
"""

from __future__ import annotations

import os

# Must be set BEFORE importing PySide6.QtWidgets.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from viewer_core.core.decoding import raise_decode_limit


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    raise_decode_limit()  # as both apps' main() does
    yield app


@pytest.fixture(scope="session", autouse=True)
def isolated_settings(tmp_path_factory):
    """Point QSettings at a scratch dir for the whole run.

    MainWindow saves its geometry on close, so without this every test
    run overwrote the real ~/.config/pepper/pepper.conf.
    """
    QSettings.setPath(
        QSettings.NativeFormat, QSettings.UserScope,
        str(tmp_path_factory.mktemp("settings")),
    )


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch) -> Path:
    """Give each test a fresh config.toml instead of the user's own."""
    import pepper.core.config as cfgmod
    cfg_path = tmp_path / "isolated-config" / "config.toml"
    monkeypatch.setattr(cfgmod, "_default_path", lambda: cfg_path)
    return cfg_path


@pytest.fixture
def sample_pixmap(tmp_path: Path) -> Path:
    """Write a 100×60 red PNG and return its path."""
    img = QImage(100, 60, QImage.Format_RGB32)
    img.fill(QColor(220, 30, 30))
    out = tmp_path / "red.png"
    assert img.save(str(out), "PNG"), "QImage.save failed"
    return out


@pytest.fixture
def sample_invalid(tmp_path: Path) -> Path:
    """A file with a fake image extension but garbage contents."""
    p = tmp_path / "junk.png"
    p.write_bytes(b"this is not an image, and never was")
    return p


# Two 4×4 frames, orange then teal, 100 ms apart. Qt reads GIFs but can't
# write them, so the file is spelled out here.
_TWO_FRAME_GIF = (
    b"GIF89a\x04\x00\x04\x00\xf0\x00\x00\xe8U:\x00\x00\x00"
    b"!\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    b"!\xf9\x04\x00\x02\x00\x00\x00,\x00\x00\x00\x00\x04\x00\x04\x00\x00"
    b"\x02\x04\x84\x8f\t\x05\x00"
    b"!\xf9\x04\x00\x02\x00\x00\x00,\x00\x00\x00\x00\x04\x00\x04\x00"
    b"\x80/\x7f\x9a\x00\x00\x00"
    b"\x02\x04\x84\x8f\t\x05\x00;"
)


@pytest.fixture
def sample_animated_gif(tmp_path: Path) -> Path:
    p = tmp_path / "blink.gif"
    p.write_bytes(_TWO_FRAME_GIF)
    return p
