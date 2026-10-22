"""Tests for ImageView — load, zoom math, fit, signals."""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QSize
from PySide6.QtTest import QSignalSpy

from pepper.ui.image_view import (
    MAX_SCALE,
    ZOOM_IN_FACTOR,
    ZOOM_OUT_FACTOR,
    ImageView,
)


@pytest.fixture
def view(qapp):
    v = ImageView()
    v.resize(400, 300)
    return v


def test_construction(view):
    assert view._has_image is False
    assert view._fit_mode == "fit"
    assert view.image_size() is None


def test_load_valid_image(view, sample_pixmap):
    assert view.load(str(sample_pixmap)) is True
    assert view._has_image is True
    assert view.image_size() == (100, 60)


def test_load_invalid_returns_false(view, sample_invalid):
    assert view.load(str(sample_invalid)) is False
    assert view._has_image is False


def test_load_nonexistent_returns_false(view, tmp_path):
    assert view.load(str(tmp_path / "nope.png")) is False
    assert view._has_image is False


def test_last_error_set_for_unsupported(view, sample_invalid):
    assert view.load(str(sample_invalid)) is False
    assert "junk.png" in view.last_error()


def test_last_error_says_when_the_file_is_gone(view, tmp_path):
    assert view.load(str(tmp_path / "nope.png")) is False
    assert view.last_error() == "That file no longer exists"


def test_last_error_cleared_on_success(view, sample_invalid, sample_pixmap):
    view.load(str(sample_invalid))
    assert view.last_error()
    assert view.load(str(sample_pixmap)) is True
    assert view.last_error() is None


def test_actual_size_sets_identity(view, sample_pixmap):
    assert view.load(str(sample_pixmap))
    view.actual_size()
    assert view.transform().m11() == pytest.approx(1.0, abs=1e-6)
    assert view.transform().m22() == pytest.approx(1.0, abs=1e-6)
    assert view._fit_mode is None


def test_zoom_in_scales_by_125(view, sample_pixmap):
    assert view.load(str(sample_pixmap))
    view.actual_size()
    view.zoom_in()
    assert view.transform().m11() == pytest.approx(ZOOM_IN_FACTOR, abs=1e-6)
    assert view._fit_mode is None


def test_zoom_out_scales_by_08(view, sample_pixmap):
    assert view.load(str(sample_pixmap))
    view.actual_size()
    view.zoom_out()
    assert view.transform().m11() == pytest.approx(ZOOM_OUT_FACTOR, abs=1e-6)
    assert view._fit_mode is None


def test_zoom_clamp_max(view, sample_pixmap):
    assert view.load(str(sample_pixmap))
    view.actual_size()
    for _ in range(50):
        view.zoom_in()
    assert view.transform().m11() <= MAX_SCALE


def test_zoom_changed_signal_emits(view, sample_pixmap):
    assert view.load(str(sample_pixmap))
    view.actual_size()
    spy = QSignalSpy(view.zoom_changed)
    view.zoom_in()
    assert spy.count() >= 1


def test_fit_marks_auto_fit_true(view, sample_pixmap):
    assert view.load(str(sample_pixmap))
    view.actual_size()
    assert view._fit_mode is None
    view.fit_to_window()
    assert view._fit_mode == "fit"


def test_zoom_marks_auto_fit_false(view, sample_pixmap):
    assert view.load(str(sample_pixmap))
    view.fit_to_window()
    assert view._fit_mode == "fit"
    view.zoom_in()
    assert view._fit_mode is None


def test_shrink_keeps_small_image_at_1to1(view, qapp, tmp_path):
    """A 50×30 image inside a 400×300 viewport should stay at 1:1."""
    from PySide6.QtGui import QColor, QImage
    img = QImage(50, 30, QImage.Format_RGB32)
    img.fill(QColor(0, 100, 200))
    small = tmp_path / "small.png"
    assert img.save(str(small), "PNG")
    assert view.load(str(small))
    view.shrink_to_fit()
    assert view.transform().m11() == pytest.approx(1.0, abs=1e-6)
    assert view._fit_mode == "shrink"


def test_shrink_fits_oversized_image(view, qapp, tmp_path):
    """A 1000×800 image inside a 400×300 viewport should be fit-scaled."""
    from PySide6.QtGui import QColor, QImage
    img = QImage(1000, 800, QImage.Format_RGB32)
    img.fill(QColor(50, 50, 50))
    big = tmp_path / "big.png"
    assert img.save(str(big), "PNG")
    assert view.load(str(big))
    view.shrink_to_fit()
    # Scaled down — transform should be < 1.0
    assert view.transform().m11() < 1.0
    assert view._fit_mode == "shrink"
