"""Tests for drag-drop handling on MainWindow.

The drop logic is exercised via `_handle_dropped_paths` rather than a
synthetic QDropEvent — manually-constructed QDropEvents can segfault
when their `acceptProposedAction()` is called outside Qt's drag
machinery. The drag-enter test uses a real QDragEnterEvent which is
safe because we only inspect mime data.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QImage

from pepper.ui.main_window import MainWindow


@pytest.fixture
def window(qapp):
    w = MainWindow()
    w.resize(400, 300)
    yield w
    w.close()


def test_drop_valid_image_loads(window, sample_pixmap):
    ok = window._handle_dropped_paths([str(sample_pixmap)])
    assert ok is True
    assert window._image_view.image_size() == (100, 60)
    assert "red.png" in window.windowTitle()


def test_drop_first_valid_wins(window, sample_invalid, sample_pixmap, tmp_path):
    # Build a second valid image so we can confirm the *first valid* wins,
    # not just "the first URL in the list".
    second = tmp_path / "second.png"
    img = QImage(40, 20, QImage.Format_RGB32)
    img.fill(QColor(0, 200, 0))
    assert img.save(str(second), "PNG")

    ok = window._handle_dropped_paths(
        [str(sample_invalid), str(sample_pixmap), str(second)]
    )
    assert ok is True
    # red.png dimensions, not the green one — confirms first-valid-wins.
    assert window._image_view.image_size() == (100, 60)


def test_drop_all_invalid_shows_status(window, sample_invalid):
    ok = window._handle_dropped_paths([str(sample_invalid)])
    assert ok is False
    assert window._image_view.image_size() is None
    assert window.statusBar().currentMessage() == "Unsupported format"


def test_drop_empty_list_shows_status(window):
    ok = window._handle_dropped_paths([])
    assert ok is False
    assert window.statusBar().currentMessage() == "Unsupported format"


def test_drag_enter_accepts_urls(window, sample_pixmap):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sample_pixmap))])
    ev = QDragEnterEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    window.dragEnterEvent(ev)
    assert ev.isAccepted()
