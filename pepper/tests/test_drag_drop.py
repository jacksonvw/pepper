"""Tests for drag-drop handling on MainWindow.

Most of the drop logic is exercised via `_handle_dropped_paths`. Calling
a handler directly with a hand-built QDropEvent can segfault once it calls
`acceptProposedAction()`, so the one end-to-end test instead hands its
events to QApplication.sendEvent at the view's viewport, which is where
Qt's own drag machinery delivers them and which routes them on from there.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
)
from PySide6.QtWidgets import QApplication

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


def test_drop_all_invalid_says_why(window, sample_invalid):
    """In the overlay: a status-bar message vanished in minimal mode."""
    ok = window._handle_dropped_paths([str(sample_invalid)])
    assert ok is False
    assert window._image_view.image_size() is None
    assert not window._error_label.isHidden()
    assert "junk.png" in window._error_label.text()


def test_drop_of_no_local_files_says_why(window):
    ok = window._handle_dropped_paths([])
    assert ok is False
    assert window._error_label.text() == "Pepper can only open files on this computer"


def test_drag_enter_accepts_urls(window, sample_pixmap):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sample_pixmap))])
    ev = QDragEnterEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    window.dragEnterEvent(ev)
    assert ev.isAccepted()


def test_drop_onto_the_image_reaches_the_window(window, sample_pixmap):
    """Drag events sent where Qt sends them: to the view's viewport.

    The view used to claim the drag and then refuse every move, so a real
    drop onto the image never reached MainWindow.dropEvent.
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sample_pixmap))])
    vp = window._image_view.viewport()
    pos = QPoint(vp.width() // 2, vp.height() // 2)
    QApplication.sendEvent(
        vp, QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    )
    move = QDragMoveEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(vp, move)
    assert move.isAccepted()
    QApplication.sendEvent(
        vp, QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    )
    assert "red.png" in window.windowTitle()
