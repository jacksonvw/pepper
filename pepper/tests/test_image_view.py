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


def test_last_error_names_an_image_over_the_decode_limit(view, tmp_path):
    from PySide6.QtGui import QColor, QImage, QImageReader
    img = QImage(1000, 1000, QImage.Format_RGB32)
    img.fill(QColor(9, 9, 9))
    big = tmp_path / "big.png"
    assert img.save(str(big), "PNG")
    saved = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(1)  # 1 MB; this image needs ~4 MB
    try:
        assert view.load(str(big)) is False
    finally:
        QImageReader.setAllocationLimit(saved)
    assert view.last_error() == "big.png is too large to open (1000×1000)"


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


def _need_svg():
    from PySide6.QtGui import QImageReader
    if b"svg" not in [bytes(f) for f in QImageReader.supportedImageFormats()]:
        pytest.skip("needs Qt's SVG image plugin (qt6-qtsvg)")


def _drawn_size(view):
    rect = view.mapFromScene(view._pixmap_item.sceneBoundingRect()).boundingRect()
    return rect.width(), rect.height()


def test_fit_shows_the_whole_image_not_just_its_opaque_part(view, tmp_path):
    """fitInView(item) fitted the opaque pixels, blowing up padded images."""
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.fillRect(75, 75, 50, 50, QColor(220, 30, 30))
    p.end()
    padded = tmp_path / "padded.png"
    assert img.save(str(padded), "PNG")
    assert view.load(str(padded))
    view.fit_to_window()
    w, h = _drawn_size(view)
    vp = view.viewport()
    assert w <= vp.width() and h <= vp.height()
    assert max(w / vp.width(), h / vp.height()) > 0.9


def test_svg_renders_sharp_but_keeps_its_size(view, tmp_path):
    """A 16-pixel icon used to be a 16-pixel bitmap stretched to fit."""
    _need_svg()
    icon = tmp_path / "icon.svg"
    icon.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
        'viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#e8553a"/></svg>'
    )
    assert view.load(str(icon))
    assert view.image_size() == (16, 16)
    assert view._pixmap_item.pixmap().width() >= 400
    view.fit_to_window()
    w, h = _drawn_size(view)
    assert max(w / view.viewport().width(), h / view.viewport().height()) > 0.9
    # Actual size is still 16 pixels across: 1:1 on a 16×16 logical item.
    view.actual_size()
    assert view.transform().m11() == pytest.approx(1.0)
    assert view._pixmap_item.boundingRect().size().toTuple() == (16.0, 16.0)


def test_a_huge_svg_canvas_opens(view, tmp_path):
    """Rendered at its nominal size it was far over the decode limit."""
    _need_svg()
    huge = tmp_path / "huge.svg"
    huge.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="60000" height="60000" '
        'viewBox="0 0 10 10"><rect width="10" height="10" fill="#246"/></svg>'
    )
    assert view.load(str(huge)), view.last_error()
    assert view.image_size() == (60000, 60000)


def test_animated_gif_plays(view, sample_animated_gif):
    """read() alone only ever showed the first frame."""
    from PySide6.QtTest import QTest
    assert view.load(str(sample_animated_gif))
    assert view.is_animated()
    first = view._pixmap_item.pixmap().toImage().pixelColor(1, 1)
    for _ in range(80):
        QTest.qWait(25)
        if view._movie.currentFrameNumber() == 1:
            break
    assert view._movie.currentFrameNumber() == 1
    assert view._pixmap_item.pixmap().toImage().pixelColor(1, 1) != first
    assert view.image_size() == (4, 4)


def test_a_still_image_stops_the_animation(view, sample_animated_gif, sample_pixmap):
    assert view.load(str(sample_animated_gif))
    assert view.is_animated()
    assert view.load(str(sample_pixmap))
    assert not view.is_animated()
    assert view.image_size() == (100, 60)


def test_zoom_in_works_from_a_fit_below_the_minimum(view, sample_pixmap):
    """A huge image fitted under MIN_SCALE couldn't be zoomed in at all."""
    from PySide6.QtGui import QTransform
    from pepper.ui.image_view import MIN_SCALE
    assert view.load(str(sample_pixmap))
    tiny = MIN_SCALE / 5
    view.setTransform(QTransform.fromScale(tiny, tiny))
    view.zoom_out()
    assert view.transform().m11() == pytest.approx(tiny)    # no further out
    view.zoom_in()
    assert view.transform().m11() == pytest.approx(tiny * ZOOM_IN_FACTOR)


def test_zoom_out_works_from_a_fit_above_the_maximum(view, sample_pixmap):
    """The same trap at the other end: a tiny image fitted past MAX_SCALE."""
    from PySide6.QtGui import QTransform
    assert view.load(str(sample_pixmap))
    big = MAX_SCALE * 2
    view.setTransform(QTransform.fromScale(big, big))
    view.zoom_in()
    assert view.transform().m11() == pytest.approx(big)     # no further in
    view.zoom_out()
    assert view.transform().m11() == pytest.approx(big * ZOOM_OUT_FACTOR)
