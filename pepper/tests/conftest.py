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
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch):
    """Redirect pepper.core.config._CONFIG_PATH at the target tmp dir."""
    cfg_path = tmp_path / "config.toml"
    import pepper.core.config as cfgmod
    monkeypatch.setattr(cfgmod, "_CONFIG_PATH", cfg_path)
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
