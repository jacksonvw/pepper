"""Pepper main window — actions, status bar, drag-drop, fullscreen, minimal mode.

Appearance / transparency:
- No setWindowOpacity (which would also dim the image).
- WA_TranslucentBackground when opacity < 100%, else off.
- paintEvent fills the window with the configured bg color, alpha modulated
  by window_opacity * bg_tint_strength.
- KWin blur-behind via viewer_core.core.blur (KWindowEffects), which works
  on both Wayland and X11.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QImageReader,
    QKeySequence,
    QPainter,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
)

from pepper.core.config import AppConfig, load_config
from pepper.ui.image_view import ImageView
from viewer_core.core.blur import set_blur_behind

log = logging.getLogger(__name__)


def _supported_filter() -> str:
    """Build a QFileDialog filter from QImageReader.supportedImageFormats()."""
    formats = sorted({bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()})
    if not formats:
        return "All Files (*)"
    patterns = " ".join(f"*.{ext}" for ext in formats)
    return f"Images ({patterns});;All Files (*)"


# Stylesheet used when the window is in transparent mode, so chrome
# elements stay visible against arbitrary desktops behind the blur.
_TRANSPARENT_STYLESHEET = """
    QMainWindow, QWidget#central
    { background: transparent; }

    QStatusBar
    { background: transparent; color: rgba(255, 255, 255, 200); }
    QStatusBar::item { border: none; }
    QLabel
    { background: transparent; color: rgba(255, 255, 255, 200); }

    QPushButton
    { background: rgba(255, 255, 255, 12); color: rgba(255, 255, 255, 200);
      border: 1px solid rgba(255, 255, 255, 20); padding: 4px 8px;
      border-radius: 3px; }
    QPushButton:hover   { background: rgba(255, 255, 255, 25); }
    QPushButton:pressed { background: rgba(255, 255, 255, 8); }

    QSlider::groove:horizontal
    { background: rgba(255, 255, 255, 25); height: 4px; border-radius: 2px; }
    QSlider::handle:horizontal
    { background: rgba(255, 255, 255, 180); width: 12px; height: 12px;
      margin: -4px 0; border-radius: 6px; }
    QSlider::sub-page:horizontal
    { background: palette(highlight); border-radius: 2px; }

    QMenu
    { background: rgba(40, 40, 40, 230); color: rgba(255, 255, 255, 220);
      border: 1px solid rgba(255, 255, 255, 30); }
    QMenu::item:selected { background: rgba(255, 255, 255, 25); }
"""


class MainWindow(QMainWindow):
    """QMainWindow with no menu bar — right-click menu only."""

    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        # WA_TranslucentBackground must be set early so the native X11 window
        # gets a 32-bit RGBA visual from the start. If we toggle it later
        # (e.g. only when opacity < 1.0), KWin keeps the original opaque
        # visual and the alpha channel from paintEvent is just discarded —
        # which is exactly the "tint shows but no real transparency" symptom.
        # When opacity == 1.0 the paintEvent below paints with full alpha,
        # so the visual result is identical to an opaque window.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("Pepper")
        self.setMinimumSize(480, 320)
        self.setAcceptDrops(True)

        self._config: AppConfig = load_config()
        self._minimal: bool = False

        # Appearance state (set by _apply_appearance).
        self._bg_alpha: int = 255
        self._bg_color: list[int] = [0, 0, 0]
        self._bg_tint_alpha: int = 178  # 70% by default

        self._image_view = ImageView(self)
        self.setCentralWidget(self._image_view)
        # The QGraphicsView's viewport has autoFillBackground=True by
        # default, which fills the central area with the palette base
        # color BEFORE drawBackground runs — that's an opaque layer
        # behind our translucent bg brush, so alpha never reaches the
        # compositor. Disable it once, here, so paintEvent + drawBackground
        # are the only background painters.
        self._image_view.viewport().setAutoFillBackground(False)
        self._image_view.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        # Drops belong to the window. QGraphicsView accepts drops on itself
        # and its viewport, and its scene then refuses every drag move (no
        # item takes drops), so a file dragged onto the image was turned
        # away before dropEvent ever saw it.
        self._image_view.setAcceptDrops(False)
        self._image_view.viewport().setAcceptDrops(False)

        # Overlay for open failures. It sits on top of the image and
        # survives minimal mode hiding the status bar. Parented to the view,
        # not its viewport as in Salt: QGraphicsView scrolls by calling
        # viewport()->scroll(), which drags the viewport's children along,
        # so the overlay would wander off as soon as the image underneath
        # was panned. Positioned by hand in resizeEvent — no layout to fight.
        self._error_label = QLabel(self._image_view)
        self._error_label.setAlignment(Qt.AlignCenter)
        self._error_label.setWordWrap(True)
        self._error_label.setObjectName("errorOverlay")
        self._error_label.setStyleSheet(
            "QLabel#errorOverlay {"
            " background: rgba(20, 20, 20, 220);"
            " color: rgba(255, 255, 255, 230);"
            " border: 1px solid rgba(255, 255, 255, 40);"
            " border-radius: 6px; padding: 14px 18px; }"
        )
        self._error_label.hide()

        self._build_status_bar()
        self._build_actions()
        self._image_view.zoom_changed.connect(self._update_zoom_label)

        self._apply_appearance()
        self._restore_state()

        if initial_path is not None:
            self._open(initial_path)

    # -- UI construction -------------------------------------------------

    def _build_status_bar(self) -> None:
        self._status_left = QLabel("")
        self._status_right = QLabel("")
        sb = self.statusBar()
        sb.addWidget(self._status_left, 1)
        sb.addPermanentWidget(self._status_right)

    def _build_actions(self) -> None:
        self._act_open = self._mk_action("Open File…", "Ctrl+O", self._on_open_dialog)
        # Ctrl+0 → actual size (1:1); fit-to-window has no hotkey by design.
        self._act_actual = self._mk_action(
            "Actual Size (1:1)", "Ctrl+0", self._image_view.actual_size
        )
        self._act_fit = self._mk_action(
            "Fit to Window", None, self._image_view.fit_to_window
        )
        self._act_zoom_in = self._mk_action(
            "Zoom In", ["Ctrl+=", "Ctrl++"], self._image_view.zoom_in
        )
        self._act_zoom_out = self._mk_action("Zoom Out", "Ctrl+-", self._image_view.zoom_out)
        self._act_fullscreen = self._mk_action(
            "Toggle Fullscreen", "F11", self._on_toggle_fullscreen
        )
        self._act_minimal = self._mk_action(
            "Toggle Minimal", "Ctrl+H", self._on_toggle_minimal
        )
        self._act_prefs = self._mk_action("Preferences…", None, self._show_preferences)
        self._act_quit = self._mk_action("Exit", "Ctrl+Q", self.close)

    def _mk_action(self, label: str, shortcut, slot) -> QAction:
        act = QAction(label, self)
        if shortcut is not None:
            if isinstance(shortcut, list):
                act.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        self.addAction(act)
        return act

    # -- Actions ---------------------------------------------------------

    def _on_open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "", _supported_filter()
        )
        if path:
            self._open(path)

    def _on_toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_toggle_minimal(self) -> None:
        self._minimal = not self._minimal
        self.statusBar().setVisible(not self._minimal)

    def _show_preferences(self) -> None:
        from pepper.ui.dialogs.preferences import PreferencesDialog
        dlg = PreferencesDialog(parent=self)
        dlg.settings_changed.connect(self._apply_appearance)
        dlg.exec()

    # -- Open flow -------------------------------------------------------

    def _open(self, path: str) -> None:
        ok = self._image_view.load(path)
        if not ok:
            # Never close on a failed open: a bad initial path used to
            # close the window 1.5s later, with the reason only in the log.
            # Stay up and say what went wrong, the way Salt does.
            reason = self._image_view.last_error() or "Unsupported format"
            log.warning("could not open %s: %s", path, reason)
            self.setWindowTitle("Pepper")
            self._status_left.setText(f"Couldn't open {Path(path).name}")
            self._status_right.setText("")
            self._show_error(reason)
            return

        size = self._image_view.image_size()
        size_text = f"{size[0]}×{size[1]}" if size else ""
        name = Path(path).name
        self.setWindowTitle(f"Pepper — {name}")
        self._status_left.setText(f"{name}  ({size_text})" if size_text else name)
        self._clear_error()

        # Optionally resize the window to match the image (VLC-style).
        # Do this BEFORE applying the zoom mode so fit/shrink see the new
        # viewport dimensions.
        if self._config.resize_window_to_image and size is not None:
            self._resize_to_image(size[0], size[1])

        # Apply the configured initial zoom mode.
        mode = self._config.default_zoom
        if mode == "actual":
            self._image_view.actual_size()
        elif mode == "shrink":
            self._image_view.shrink_to_fit()
        else:
            self._image_view.fit_to_window()

        self._update_zoom_label(self._image_view.current_zoom_factor())

    def _show_error(self, message: str) -> None:
        """Put a failure reason where it can actually be read.

        The status bar is hidden in minimal mode, so the message goes to
        the centre of the view — otherwise Ctrl+H would swallow the only
        explanation the user gets. It deliberately skips
        statusBar().showMessage(): QStatusBar only hides its own labels
        for a message if they are visible at that moment, so a message
        posted before the first show, or in minimal mode, ends up drawn
        over "Couldn't open …".
        """
        self._error_label.setText(message)
        self._error_label.show()
        self._reposition_error_label()

    def _clear_error(self) -> None:
        self._error_label.hide()

    def _resize_to_image(self, image_w: int, image_h: int) -> None:
        """Resize the window so the image area matches the image's pixel size,
        capped at 90% of the available screen geometry, and never below the
        window's minimum size.
        """
        sb_h = self.statusBar().height() if self.statusBar().isVisible() else 0
        target_w = image_w
        target_h = image_h + sb_h

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_w = min(target_w, int(avail.width() * 0.9))
            target_h = min(target_h, int(avail.height() * 0.9))

        target_w = max(target_w, self.minimumWidth())
        target_h = max(target_h, self.minimumHeight())
        self.resize(target_w, target_h)

    def _update_zoom_label(self, factor: float) -> None:
        pct = int(round(factor * 100))
        self._status_right.setText(f"Zoom: {pct}%")

    # -- Drag-drop -------------------------------------------------------

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        paths = [
            url.toLocalFile() for url in ev.mimeData().urls() if url.toLocalFile()
        ]
        if self._handle_dropped_paths(paths):
            ev.acceptProposedAction()

    def _handle_dropped_paths(self, paths: list[str]) -> bool:
        """Open the first path Qt can read; return True if anything was opened.

        Factored out so tests can drive the logic without synthesizing a
        QDropEvent (manual QDropEvent.acceptProposedAction can segfault).
        """
        for path in paths:
            if QImageReader.imageFormat(path):
                self._open(path)
                return True
        self.statusBar().showMessage("Unsupported format", 4000)
        return False

    # -- Context menu ----------------------------------------------------

    def contextMenuEvent(self, ev) -> None:
        menu = QMenu(self)
        menu.addAction(self._act_open)
        menu.addSeparator()
        menu.addAction(self._act_fit)
        menu.addAction(self._act_actual)
        menu.addAction(self._act_zoom_in)
        menu.addAction(self._act_zoom_out)
        menu.addSeparator()
        menu.addAction(self._act_fullscreen)
        menu.addAction(self._act_minimal)
        menu.addSeparator()
        menu.addAction(self._act_prefs)
        menu.addSeparator()
        menu.addAction(self._act_quit)
        menu.exec(ev.globalPos())

    # -- Error overlay placement -----------------------------------------

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._reposition_error_label()

    def _reposition_error_label(self) -> None:
        # isHidden(), not isVisible(): a child of a not-yet-shown window
        # is never "visible", and an initial-path failure happens during
        # __init__ — before the window is up.
        if self._error_label.isHidden():
            return
        view = self._image_view
        width = min(560, max(240, int(view.width() * 0.8)))
        self._error_label.setFixedWidth(width)
        self._error_label.adjustSize()
        self._error_label.move(
            max(0, (view.width() - self._error_label.width()) // 2),
            max(0, (view.height() - self._error_label.height()) // 2),
        )

    # -- Esc-only-when-fullscreen ---------------------------------------

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            ev.accept()
            return
        super().keyPressEvent(ev)

    # -- Geometry / state persistence -----------------------------------

    def _settings(self) -> QSettings:
        return QSettings("pepper", "pepper")

    def _restore_state(self) -> None:
        s = self._settings()
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        ws = s.value("windowState")
        if ws:
            self.restoreState(ws)
        minimal = s.value("minimal_mode")
        if minimal is not None:
            want_minimal = (
                minimal if isinstance(minimal, bool) else str(minimal).lower() == "true"
            )
            if want_minimal:
                self._minimal = True
                self.statusBar().setVisible(False)

    def _save_state(self) -> None:
        s = self._settings()
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        s.setValue("minimal_mode", self._minimal)

    def closeEvent(self, ev) -> None:
        self._save_state()
        super().closeEvent(ev)

    # -- Appearance -----------------------------------------------------

    def _apply_appearance(self) -> None:
        """Apply transparency / bg color / blur settings from config.

        Note: WA_TranslucentBackground is set unconditionally in __init__,
        so we only need to toggle the stylesheet, the bg color, and the
        KWin blur here. paintEvent reads `_bg_alpha` and modulates
        the fill alpha — at opacity=1.0 it paints with alpha=255 and the
        window is visually opaque.
        """
        config = load_config()
        self._config = config
        appearance = config.appearance
        self._bg_alpha = int(appearance.window_opacity * 255)
        self._bg_color = list(appearance.bg_color)
        self._bg_tint_alpha = int(appearance.bg_tint_strength * 255 / 100)

        r, g, b = self._bg_color
        if appearance.window_opacity < 1.0:
            self.setStyleSheet(_TRANSPARENT_STYLESHEET)
            # The image pixmap itself is opaque (RGB → no alpha channel),
            # so the QGraphicsView's scene background can be translucent:
            # the letterbox area picks up the bg color + KWin blur,
            # while the image stays solid because the pixmap paints
            # opaquely on top of drawBackground.
            tint_alpha = int(self._bg_tint_alpha * self._bg_alpha / 255)
            self._image_view.setBackgroundBrush(QColor(r, g, b, tint_alpha))
        else:
            self.setStyleSheet("")
            self._bg_alpha = 255
            self._image_view.setBackgroundBrush(QColor(r, g, b))

        self._apply_blur()

        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        r, g, b = self._bg_color
        if self._bg_alpha < 255:
            tint_alpha = int(self._bg_tint_alpha * self._bg_alpha / 255)
            painter.fillRect(self.rect(), QColor(r, g, b, tint_alpha))
        else:
            painter.fillRect(self.rect(), QColor(r, g, b))
        painter.end()

    def _apply_blur(self) -> None:
        """Push the current blur setting to KWin.

        No-ops harmlessly before the window is first shown (there is no
        native window to blur yet); showEvent re-applies it.
        """
        appearance = self._config.appearance
        want = appearance.blur_behind and appearance.window_opacity < 1.0
        set_blur_behind(self, want)

    def showEvent(self, ev) -> None:
        # windowHandle() is None until now, so this is the first point at
        # which blur can actually be applied. Qt may also recreate the
        # native window (fullscreen transitions), which lands here again.
        super().showEvent(ev)
        self._apply_blur()
        # The view only has real geometry now, so an overlay raised
        # during __init__ (a failed initial path) gets placed here.
        self._reposition_error_label()
