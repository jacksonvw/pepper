"""Shared fixtures for Salt tests — mirrors Pepper's conftest pattern."""

from __future__ import annotations

import os

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
def sample_image_bytes() -> bytes:
    img = QImage(40, 60, QImage.Format_RGB32)
    img.fill(QColor(80, 80, 80))
    from PySide6.QtCore import QBuffer, QByteArray
    buf = QBuffer()
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


@pytest.fixture
def comic_dir(tmp_path: Path, sample_image_bytes: bytes) -> Path:
    """A directory of 3 sample PNGs named so natural sort works."""
    d = tmp_path / "comic"
    d.mkdir()
    for i in (1, 2, 10):
        (d / f"page{i}.png").write_bytes(sample_image_bytes)
    # Decoy non-image file that should be filtered out.
    (d / "ignore.txt").write_text("hello", encoding="utf-8")
    return d


@pytest.fixture
def comic_zip(tmp_path: Path, sample_image_bytes: bytes) -> Path:
    import zipfile
    z = tmp_path / "comic.cbz"
    with zipfile.ZipFile(z, "w") as zf:
        for i in (1, 2, 10):
            zf.writestr(f"page{i}.png", sample_image_bytes)
        zf.writestr("readme.txt", "skip me")
    return z


@pytest.fixture
def misnamed_cbr(tmp_path: Path, sample_image_bytes: bytes) -> Path:
    """A zip wearing a .cbr extension — very common in the wild."""
    import zipfile
    z = tmp_path / "actually-a-zip.cbr"
    with zipfile.ZipFile(z, "w") as zf:
        for i in (1, 2, 10):
            zf.writestr(f"page{i}.png", sample_image_bytes)
    return z


@pytest.fixture
def sparse_archive(tmp_path: Path, sample_image_bytes: bytes) -> Path:
    """A part-downloaded file: real bytes up front, then a big hole."""
    p = tmp_path / "half-downloaded.cbr"
    with open(p, "wb") as fh:
        fh.write(b"Rar!\x1a\x07\x01\x00" + sample_image_bytes)
        fh.truncate(64 * 1024 * 1024)
    return p


@pytest.fixture
def comic_tar(tmp_path: Path, sample_image_bytes: bytes) -> Path:
    import io
    import tarfile
    t = tmp_path / "comic.tar"
    with tarfile.open(t, "w") as tf:
        for i in (1, 2, 10):
            data = sample_image_bytes
            info = tarfile.TarInfo(name=f"page{i}.png")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return t
