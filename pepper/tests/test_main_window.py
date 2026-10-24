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


def test_tests_keep_out_of_the_real_config(qapp, tmp_path_factory):
    """Saved geometry and config.toml land in scratch dirs, not ~/.config."""
    from pepper.core import config
    scratch = str(tmp_path_factory.getbasetemp())
    win = MainWindow()
    assert win._settings().fileName().startswith(scratch)
    assert str(config._default_path()).startswith(scratch)
    win.close()


def test_overlay_stays_centred_when_minimal_mode_hides_the_status_bar(
    qapp, sample_invalid
):
    """Hiding the status bar resizes the view but not the window."""
    win = MainWindow(initial_path=str(sample_invalid))
    win.resize(600, 400)
    win.show()
    qapp.processEvents()
    view, label = win._image_view, win._error_label
    before = view.height()
    win._on_toggle_minimal()
    qapp.processEvents()
    try:
        assert view.height() != before
        assert abs(label.geometry().center().y() - view.height() / 2) <= 1
    finally:
        win._on_toggle_minimal()  # the saved setting is shared by later tests
        win.close()


def _forget_window_state():
    """The saved settings are shared by later tests; don't leave them
    starting maximized."""
    from PySide6.QtCore import QSettings
    QSettings("pepper", "pepper").clear()


def test_leaving_fullscreen_restores_maximized(qapp):
    """showNormal() used to drop a maximized window to its normal size."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win = MainWindow()
    win.show()
    win.showMaximized()
    try:
        win._on_toggle_fullscreen()
        assert win.isFullScreen()
        win._on_toggle_fullscreen()
        assert win.isMaximized() and not win.isFullScreen()
        win._on_toggle_fullscreen()
        QTest.keyClick(win, Qt.Key_Escape)
        assert win.isMaximized() and not win.isFullScreen()
    finally:
        win.close()
        _forget_window_state()


def test_quitting_from_fullscreen_doesnt_reopen_fullscreen(qapp):
    win = MainWindow()
    win.show()
    win.showMaximized()
    win._on_toggle_fullscreen()
    win.close()
    try:
        again = MainWindow()
        assert not again.isFullScreen()
        assert again.isMaximized()
        again.close()
    finally:
        _forget_window_state()
