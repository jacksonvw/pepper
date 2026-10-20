"""Tests for MainWindow — initial-path load, unsupported-initial close."""

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


def test_unsupported_initial_path_schedules_close(qapp, sample_invalid, monkeypatch):
    """An unsupported CLI-arg image should arrange a graceful close."""
    closed = []
    # Capture the singleShot timer setup without waiting 1.5s in tests.
    from PySide6.QtCore import QTimer
    real_singleshot = QTimer.singleShot

    def capture_singleshot(ms, slot):
        closed.append((ms, slot))
        # Don't actually start a timer.
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(capture_singleshot))

    window = MainWindow(initial_path=str(sample_invalid))
    try:
        # No image was loaded.
        assert window._image_view.image_size() is None
        # And a close was scheduled.
        assert closed, "expected QTimer.singleShot to schedule close"
        ms, slot = closed[0]
        assert ms == 1500
        assert slot == window.close
    finally:
        # Restore so cleanup doesn't break.
        monkeypatch.setattr(QTimer, "singleShot", staticmethod(real_singleshot))
        window.close()
