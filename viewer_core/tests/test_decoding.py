"""Tests for the shared image decoding limit."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImageReader

from viewer_core.core.decoding import DECODE_LIMIT_MB, raise_decode_limit, too_large


@pytest.fixture
def restore_limit():
    saved = QImageReader.allocationLimit()
    yield
    QImageReader.setAllocationLimit(saved)


def test_raise_lifts_qts_256_mb_default(restore_limit):
    raise_decode_limit()
    assert QImageReader.allocationLimit() == DECODE_LIMIT_MB > 256


def test_large_photos_fit_but_bombs_do_not(restore_limit):
    raise_decode_limit()
    assert not too_large(QSize(9000, 9000))      # ~324 MB: refused by Qt's default
    assert too_large(QSize(60000, 60000))


def test_no_limit_means_nothing_is_too_large(restore_limit):
    QImageReader.setAllocationLimit(0)
    assert not too_large(QSize(100000, 100000))


def test_unknown_size_is_not_too_large(restore_limit):
    raise_decode_limit()
    assert not too_large(QSize())


def test_too_large_counts_the_decoded_depth(restore_limit):
    """A 16-bit PNG decodes to eight bytes a pixel, not four."""
    from PySide6.QtGui import QImage
    QImageReader.setAllocationLimit(4)     # MB; 900×900 is ~3.1 MB at 4 bytes
    assert not too_large(QSize(900, 900), QImage.Format_ARGB32)
    assert too_large(QSize(900, 900), QImage.Format_RGBA64)
