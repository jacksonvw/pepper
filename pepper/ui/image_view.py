"""ImageView — QGraphicsView with zoom/pan/fit/100% primitives."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
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

log = logging.getLogger(__name__)

MIN_SCALE = 0.05
MAX_SCALE = 50.0
ZOOM_IN_FACTOR = 1.25
ZOOM_OUT_FACTOR = 0.8


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
        self._pending_first_fit: bool = False
        self._last_fit_scale: float = 1.0
        # Track scroll-hand-drag state for the matching mouse release.
        self._panning_button = None

    # -- Public API ------------------------------------------------------

    def load(self, path: str) -> bool:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        if not reader.format():
            log.info("unsupported format: %s", path)
            return False
        image = reader.read()
        if image.isNull():
            log.info("failed to read: %s (%s)", path, reader.errorString())
            return False
        pix = QPixmap.fromImage(image)
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
        pix = self._pixmap_item.pixmap()
        return (pix.width(), pix.height())

    # -- Internals -------------------------------------------------------

    def _viewport_sized(self) -> bool:
        return self.viewport().width() > 0 and self.viewport().height() > 0

    def _apply_fit(self) -> None:
        self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
        self._last_fit_scale = self.transform().m11()
        self.zoom_changed.emit(self._last_fit_scale)

    def _apply_shrink(self) -> None:
        pix = self._pixmap_item.pixmap()
        iw, ih = pix.width(), pix.height()
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
