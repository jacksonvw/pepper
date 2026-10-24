"""ImageView — QGraphicsView with zoom/pan/fit/100% primitives."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImageReader,
    QPainter,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)

from viewer_core.core.decoding import too_large

log = logging.getLogger(__name__)

MIN_SCALE = 0.05
MAX_SCALE = 50.0
ZOOM_IN_FACTOR = 1.25
ZOOM_OUT_FACTOR = 0.8


_VECTOR_FORMATS = (b"svg", b"svgz")


def _vector_scale(size: QSize) -> float:
    """How much larger than its nominal size to render a vector image.

    Rendered at its nominal size, a small SVG turned to mush the moment it
    was fitted to the window. Render it so its long side covers the
    largest screen instead (or less, for one nominally larger still, which
    also keeps a huge canvas under the decode limit).
    """
    if not size.isValid() or size.isEmpty():
        return 1.0
    target = max(
        (max(s.size().width(), s.size().height()) * s.devicePixelRatio()
         for s in QGuiApplication.screens()),
        default=2048,
    )
    return target / max(size.width(), size.height())


def _unrecognised_reason(path: str) -> str:
    """Explain a file QImageReader couldn't even identify.

    Qt reports a missing file, an unreadable one and a folder alike as
    "File not found", so ask the filesystem which it actually is.
    """
    p = Path(path)
    name = p.name or path
    if not p.exists():
        return "That file no longer exists"
    if p.is_file() and not os.access(p, os.R_OK):
        return f"Couldn't read {name} — permission denied"
    return f"{name} isn't an image Pepper can open"


class ImageView(QGraphicsView):
    """Single-image viewer. Owns wheel-zoom, fit, 1:1, and pan."""

    zoom_changed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)

        self.setRenderHints(
            QPainter.SmoothPixmapTransform | QPainter.Antialiasing
        )
        self.setBackgroundBrush(QColor(0, 0, 0))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)

        # Active fit policy:
        #   "fit"    → re-fit on resize (always scale to fill viewport)
        #   "shrink" → re-evaluate on resize (fit only if larger than view)
        #   None     → manual control (wheel zoom or actual_size); no resize action
        self._fit_mode: str | None = "fit"
        self._has_image: bool = False
        self._last_error: str | None = None
        self._pending_first_fit: bool = False
        self._last_fit_scale: float = 1.0
        # Track scroll-hand-drag state for the matching mouse release.
        self._panning_button = None

    # -- Public API ------------------------------------------------------

    def load(self, path: str) -> bool:
        self._last_error = None
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        if not reader.format():
            log.info("unsupported format: %s", path)
            self._last_error = _unrecognised_reason(path)
            return False
        size = reader.size()
        scale = 1.0
        if bytes(reader.format()) in _VECTOR_FORMATS:
            scale = _vector_scale(size)
            reader.setScaledSize(QSize(
                max(1, round(size.width() * scale)),
                max(1, round(size.height() * scale)),
            ))
        image = reader.read()
        if image.isNull():
            log.info("failed to read: %s (%s)", path, reader.errorString())
            name = Path(path).name or path
            decoded = reader.scaledSize() if scale != 1.0 else size
            if too_large(decoded):
                self._last_error = (
                    f"{name} is too large to open "
                    f"({size.width()}×{size.height()})"
                )
            else:
                self._last_error = f"Couldn't read {name} — {reader.errorString()}"
            return False
        pix = QPixmap.fromImage(image)
        # A vector image rendered large keeps its nominal size as its
        # logical one, so actual size and the zoom figure mean what they say.
        pix.setDevicePixelRatio(scale)
        self._pixmap_item.setPixmap(pix)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._has_image = True
        # Caller (MainWindow._open) decides which initial zoom mode to apply.
        self._pending_first_fit = True
        return True

    def fit_to_window(self) -> None:
        if not self._has_image:
            return
        self._fit_mode = "fit"
        if not self._viewport_sized():
            self._pending_first_fit = True
            return
        self._apply_fit()

    def shrink_to_fit(self) -> None:
        """Fit only if the image is larger than the viewport.

        Small images stay at 1:1 (no upscaling). Large images shrink to
        fit. Re-evaluates on every window resize.
        """
        if not self._has_image:
            return
        self._fit_mode = "shrink"
        if not self._viewport_sized():
            self._pending_first_fit = True
            return
        self._apply_shrink()

    def actual_size(self) -> None:
        if not self._has_image:
            return
        self._fit_mode = None
        self.setTransform(QTransform())
        self.centerOn(self._pixmap_item)
        self._last_fit_scale = 1.0
        self._pending_first_fit = False
        self.zoom_changed.emit(1.0)

    def zoom_in(self) -> None:
        self._zoom_by(ZOOM_IN_FACTOR)

    def zoom_out(self) -> None:
        self._zoom_by(ZOOM_OUT_FACTOR)

    def current_zoom_factor(self) -> float:
        return self.transform().m11()

    def image_size(self) -> tuple[int, int] | None:
        if not self._has_image:
            return None
        size = self._pixmap_item.pixmap().deviceIndependentSize()
        return (round(size.width()), round(size.height()))

    def last_error(self) -> str | None:
        """Why the most recent load() returned False, if it did."""
        return self._last_error

    # -- Internals -------------------------------------------------------

    def _viewport_sized(self) -> bool:
        return self.viewport().width() > 0 and self.viewport().height() > 0

    def _apply_fit(self) -> None:
        # Fit the image's whole rectangle. fitInView(item) fits the item's
        # shape, which for a pixmap with transparency is just its opaque
        # pixels (a padded logo was blown up past the window) and, for a
        # vector image rendered at a high pixel ratio, ignores the ratio.
        self.fitInView(self._pixmap_item.sceneBoundingRect(), Qt.KeepAspectRatio)
        self._last_fit_scale = self.transform().m11()
        self.zoom_changed.emit(self._last_fit_scale)

    def _apply_shrink(self) -> None:
        size = self._pixmap_item.pixmap().deviceIndependentSize()
        iw, ih = size.width(), size.height()
        vw = self.viewport().width()
        vh = self.viewport().height()
        if iw <= vw and ih <= vh:
            # Fits at 1:1 — show actual, but stay in shrink mode so a
            # later window shrink falls back to fit.
            self.setTransform(QTransform())
            self.centerOn(self._pixmap_item)
            self._last_fit_scale = 1.0
            self.zoom_changed.emit(1.0)
        else:
            self._apply_fit()

    def _zoom_by(self, factor: float) -> None:
        if not self._has_image:
            return
        new_scale = self.transform().m11() * factor
        if new_scale < MIN_SCALE or new_scale > MAX_SCALE:
            return
        self.scale(factor, factor)
        self._fit_mode = None
        self.zoom_changed.emit(self.transform().m11())

    def _is_zoomed_past_fit(self) -> bool:
        # 0.1% margin to absorb float jitter near the fit scale.
        return self.transform().m11() > self._last_fit_scale * 1.001

    # -- Events ----------------------------------------------------------

    def wheelEvent(self, ev) -> None:
        if not self._has_image:
            ev.ignore()
            return
        delta = ev.angleDelta().y()
        if delta == 0:
            ev.ignore()
            return
        factor = ZOOM_IN_FACTOR if delta > 0 else ZOOM_OUT_FACTOR
        new_scale = self.transform().m11() * factor
        if new_scale < MIN_SCALE or new_scale > MAX_SCALE:
            ev.accept()
            return
        self.scale(factor, factor)
        self._fit_mode = None
        self.zoom_changed.emit(self.transform().m11())
        ev.accept()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MiddleButton:
            self._panning_button = Qt.MiddleButton
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            from PySide6.QtGui import QMouseEvent
            fake = QMouseEvent(
                ev.type(),
                ev.position(),
                ev.globalPosition(),
                Qt.LeftButton,
                Qt.LeftButton,
                ev.modifiers(),
            )
            super().mousePressEvent(fake)
            ev.accept()
            return
        if (
            ev.button() == Qt.LeftButton
            and self._has_image
            and self._is_zoomed_past_fit()
        ):
            self._panning_button = Qt.LeftButton
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if self._panning_button is not None and ev.button() == self._panning_button:
            if self._panning_button == Qt.MiddleButton:
                from PySide6.QtGui import QMouseEvent
                fake = QMouseEvent(
                    ev.type(),
                    ev.position(),
                    ev.globalPosition(),
                    Qt.LeftButton,
                    Qt.LeftButton,
                    ev.modifiers(),
                )
                super().mouseReleaseEvent(fake)
            else:
                super().mouseReleaseEvent(ev)
            self.setDragMode(QGraphicsView.NoDrag)
            self._panning_button = None
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if not self._has_image or not self._viewport_sized():
            return
        if self._fit_mode == "fit":
            self._apply_fit()
        elif self._fit_mode == "shrink":
            self._apply_shrink()
        self._pending_first_fit = False

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._has_image and self._pending_first_fit and self._viewport_sized():
            if self._fit_mode == "fit":
                self._apply_fit()
            elif self._fit_mode == "shrink":
                self._apply_shrink()
            self._pending_first_fit = False
