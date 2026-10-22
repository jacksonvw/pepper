"""Tests for MainWindow — initial-path load, surviving a bad initial path."""

from __future__ import annotations

import pytest

from pepper.ui.main_window import MainWindow


def test_initial_path_loads(qapp, sample_pixmap):
    window = MainWindow(initial_path=str(sample_pixmap))
    try:
        assert window._image_view.image_size() == (100, 60)
        assert "red.png" in window.windowTitle()
    finally:
        window.close()


def test_window_survives_a_bad_initial_path(qapp, sample_invalid):
    """The original bug: a bad initial path closed the app 1.5s later."""
    win = MainWindow(initial_path=str(sample_invalid))
    # isHidden(), not isVisible(): the window itself hasn't been shown yet,
    # which makes every child "not visible" regardless of its own state.
    assert not win._error_label.isHidden()
    assert "junk.png" in win._error_label.text()
    # And it is still a live window rather than a closed one.
    win.show()
    assert win.isVisible()
    assert not win._error_label.isHidden()
    assert win._error_label.width() > 0
    # No status-bar message drawn over the "Couldn't open" label.
    assert win._status_left.text() == "Couldn't open junk.png"
    assert win.statusBar().currentMessage() == ""
    win.close()


def test_error_overlay_clears_after_a_good_open(qapp, sample_invalid, sample_pixmap):
    win = MainWindow(initial_path=str(sample_invalid))
    assert not win._error_label.isHidden()
    win._open(str(sample_pixmap))
    assert win._error_label.isHidden()
    assert "red.png" in win.windowTitle()
    win.close()
