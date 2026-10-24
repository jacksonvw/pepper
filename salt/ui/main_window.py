"""Salt main window — comic/image-set viewer with scrollable panel."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
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

from salt.core.config import AppConfig, load_config
from salt.ui.comic_view import ComicView
from viewer_core.core.blur import set_blur_behind

log = logging.getLogger(__name__)


_TRANSPARENT_STYLESHEET = """
    QMainWindow, QWidget#central
    { background: transparent; }

    QStatusBar
    { background: transparent; color: rgba(255, 255, 255, 200); }
    QStatusBar::item { border: none; }
    QLabel
    { background: transparent; color: rgba(255, 255, 255, 200); }

    QScrollBar:vertical, QScrollBar:horizontal
    { background: transparent; width: 10px; height: 10px; }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal
    { background: rgba(255, 255, 255, 80); border-radius: 4px;
      min-height: 24px; min-width: 24px; }
    QScrollBar::handle:hover
    { background: rgba(255, 255, 255, 130); }
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page
    { background: transparent; height: 0; width: 0; }

    QMenu
    { background: rgba(40, 40, 40, 230); color: rgba(255, 255, 255, 220);
      border: 1px solid rgba(255, 255, 255, 30); }
    QMenu::item:selected { background: rgba(255, 255, 255, 25); }
"""


def _archive_filter() -> str:
    return (
        "Comics / Archives (*.cbz *.cbr *.zip *.rar *.tar *.tar.gz *.tgz "
        "*.tar.bz2 *.tbz2 *.tar.xz *.txz);;Comics (*.cbz *.cbr);;"
        "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif "
        "*.tiff *.svg);;All Files (*)"
    )


class MainWindow(QMainWindow):
    """Salt main window. No menu bar — right-click for the full menu."""

    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        # See pepper/ui/main_window.py for why this is set early.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("Salt")
        self.setMinimumSize(480, 320)
        self.setAcceptDrops(True)

        self._config: AppConfig = load_config()
        self._minimal: bool = False

        # Appearance state.
        self._bg_alpha: int = 255
        self._bg_color: list[int] = [0, 0, 0]
        self._bg_tint_alpha: int = 178

        self._comic_view = ComicView(self)
        self.setCentralWidget(self._comic_view)

        # Overlay for open failures. Parented to the viewport so it sits
        # on top of the pages and survives minimal mode hiding the status
        # bar. Positioned by hand in resizeEvent — no layout to fight.
        self._error_label = QLabel(self._comic_view.viewport())
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

        # Apply config-driven comic settings before any source is loaded.
        self._comic_view.set_orientation(self._config.orientation)
        self._comic_view.set_fit_mode(self._config.fit_mode)
        self._comic_view.set_scroll_mode(self._config.scroll_mode)
        self._comic_view.set_page_gap(self._config.page_gap)

        self._build_status_bar()
        self._build_actions()
        self._comic_view.page_changed.connect(self._update_page_label)
        self._comic_view.source_loaded.connect(self._on_source_loaded)

        self._apply_appearance()
        self._restore_state()

        if initial_path is not None:
            self._open(initial_path, is_initial=True)

    # -- UI --------------------------------------------------------------

    def _build_status_bar(self) -> None:
        self._status_source = QLabel("")
        self._status_modes = QLabel("")
        self._status_page = QLabel("")
        sb = self.statusBar()
        sb.addWidget(self._status_source, 1)
        sb.addPermanentWidget(self._status_modes)
        sb.addPermanentWidget(self._status_page)
        self._update_modes_label()

    def _build_actions(self) -> None:
        self._act_open = self._mk_action("Open…", "Ctrl+O", self._on_open_dialog)
        self._act_open_dir = self._mk_action(
            "Open Folder…", "Ctrl+Shift+O", self._on_open_folder_dialog
        )
        self._act_next = self._mk_action(
            "Next Page", "PgDown", self._comic_view.next_page
        )
        self._act_prev = self._mk_action(
            "Previous Page", "PgUp", self._comic_view.prev_page
        )
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
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        self.addAction(act)
        return act

    # -- Open dialogs ----------------------------------------------------

    def _on_open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Comic / Archive", "", _archive_filter()
        )
        if path:
            self._open(path)

    def _on_open_folder_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Folder")
        if path:
            self._open(path)

    # -- Open / load -----------------------------------------------------

    def _open(self, path: str, *, is_initial: bool = False) -> None:
        ok = self._comic_view.load_source(path)
        if not ok:
            # Never close on a failed open. Salt used to exit 1.5s after a
            # bad initial path, which turned every unreadable file into an
            # app that "just closes" with the reason scrolling past in a
            # log nobody was watching. Stay up and say what went wrong.
            reason = self._comic_view.last_error() or "Unsupported source"
            log.warning("could not open %s: %s", path, reason)
            self.setWindowTitle("Salt")
            self._status_source.setText(f"Couldn't open {Path(path).name}")
            self._status_page.setText("")
            self._show_error(reason)
            return
        name = Path(path).name or path
        self.setWindowTitle(f"Salt — {name}")
        self._status_source.setText(name)
        self._clear_error()

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

    def _on_source_loaded(self, total: int, source: str) -> None:
        # Already shown by _open's title/source update; this is a hook
        # for future side-effects (e.g. play a chime, persist last name).
        log.info("loaded %d page(s) from %s", total, source)

    def _update_page_label(self, current: int, total: int) -> None:
        self._status_page.setText(f"{current}/{total}")

    def _update_modes_label(self) -> None:
        o = self._comic_view.orientation()
        s = self._comic_view.scroll_mode()
        f = self._comic_view.fit_mode()
        self._status_modes.setText(f"{o} · {s} · fit:{f}")

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
        for path in paths:
            if Path(path).exists():
                self._open(path)
                return True
        self.statusBar().showMessage("Unsupported source", 4000)
        return False

    # -- Right-click menu (orientation/fit/scroll all live here) ---------

    def contextMenuEvent(self, ev) -> None:
        menu = QMenu(self)
        menu.addAction(self._act_open)
        menu.addAction(self._act_open_dir)
        menu.addSeparator()
        menu.addAction(self._act_prev)
        menu.addAction(self._act_next)
        menu.addSeparator()

        # Orientation submenu
        orient_menu = menu.addMenu("Orientation")
        orient_group = QActionGroup(orient_menu)
        for key, label in [("vertical", "Vertical"), ("horizontal", "Horizontal")]:
            a = QAction(label, orient_menu)
            a.setCheckable(True)
            a.setChecked(self._comic_view.orientation() == key)
            a.triggered.connect(lambda _checked, k=key: self._set_orientation(k))
            orient_group.addAction(a)
            orient_menu.addAction(a)

        # Fit submenu
        fit_menu = menu.addMenu("Fit")
        fit_group = QActionGroup(fit_menu)
        for key, label in [
            ("horizontal", "Horizontal (width)"),
            ("vertical", "Vertical (height)"),
            ("both", "Both (inside viewport)"),
            ("none", "None (native size)"),
        ]:
            a = QAction(label, fit_menu)
            a.setCheckable(True)
            a.setChecked(self._comic_view.fit_mode() == key)
            a.triggered.connect(lambda _checked, k=key: self._set_fit_mode(k))
            fit_group.addAction(a)
            fit_menu.addAction(a)

        # Scroll mode submenu
        scroll_menu = menu.addMenu("Scroll mode")
        scroll_group = QActionGroup(scroll_menu)
        for key, label in [
            ("continuous", "Continuous"),
            ("page", "Page"),
        ]:
            a = QAction(label, scroll_menu)
            a.setCheckable(True)
            a.setChecked(self._comic_view.scroll_mode() == key)
            a.triggered.connect(lambda _checked, k=key: self._set_scroll_mode(k))
            scroll_group.addAction(a)
            scroll_menu.addAction(a)

        menu.addSeparator()
        menu.addAction(self._act_fullscreen)
        menu.addAction(self._act_minimal)
        menu.addSeparator()
        menu.addAction(self._act_prefs)
        menu.addSeparator()
        menu.addAction(self._act_quit)
        menu.exec(ev.globalPos())

    def _set_orientation(self, key: str) -> None:
        self._comic_view.set_orientation(key)
        self._config.orientation = key
        self._save_comic_setting_to_disk()
        self._update_modes_label()

    def _set_fit_mode(self, key: str) -> None:
        self._comic_view.set_fit_mode(key)
        self._config.fit_mode = key
        self._save_comic_setting_to_disk()
        self._update_modes_label()

    def _set_scroll_mode(self, key: str) -> None:
        self._comic_view.set_scroll_mode(key)
        self._config.scroll_mode = key
        self._save_comic_setting_to_disk()
        self._update_modes_label()

    def _save_comic_setting_to_disk(self) -> None:
        """Persist current comic settings without opening Preferences."""
        from salt.core.config import save_config
        try:
            save_config(self._config)
        except (ValueError, OSError) as e:
            log.warning("couldn't persist comic settings: %s", e)

    # -- Toggles ---------------------------------------------------------

    def _on_toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_toggle_minimal(self) -> None:
        self._minimal = not self._minimal
        self.statusBar().setVisible(not self._minimal)

    def _show_preferences(self) -> None:
        from salt.ui.dialogs.preferences import PreferencesDialog
        dlg = PreferencesDialog(parent=self)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self) -> None:
        # Pull fresh config, apply to comic view + appearance.
        self._config = load_config()
        self._comic_view.set_orientation(self._config.orientation)
        self._comic_view.set_fit_mode(self._config.fit_mode)
        self._comic_view.set_scroll_mode(self._config.scroll_mode)
        self._comic_view.set_page_gap(self._config.page_gap)
        self._update_modes_label()
        self._apply_appearance()

    # -- Error overlay placement -----------------------------------------

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._reposition_error_label()

    def _reposition_error_label(self) -> None:
        # isHidden(), not isVisible(): a child of a not-yet-shown window
        # is never "visible", and an initial-path failure happens during
        # __init__ — before the window is up. Testing visibility here
        # skipped the only layout pass the overlay ever got.
        if self._error_label.isHidden():
            return
        vp = self._comic_view.viewport()
        width = min(560, max(240, int(vp.width() * 0.8)))
        self._error_label.setFixedWidth(width)
        self._error_label.adjustSize()
        self._error_label.move(
            max(0, (vp.width() - self._error_label.width()) // 2),
            max(0, (vp.height() - self._error_label.height()) // 2),
        )

    # -- Esc-only-when-fullscreen ---------------------------------------

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            ev.accept()
            return
        super().keyPressEvent(ev)

    # -- Geometry persistence -------------------------------------------

    def _settings(self) -> QSettings:
        return QSettings("salt", "salt")

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

    # -- Appearance (mirror of Pepper) -----------------------------------

    def _apply_appearance(self) -> None:
        config = load_config()
        self._config = config
        appearance = config.appearance
        self._bg_alpha = int(appearance.window_opacity * 255)
        self._bg_color = list(appearance.bg_color)
        self._bg_tint_alpha = int(appearance.bg_tint_strength * 255 / 100)

        r, g, b = self._bg_color
        if appearance.window_opacity < 1.0:
            self.setStyleSheet(_TRANSPARENT_STYLESHEET)
            tint_alpha = int(self._bg_tint_alpha * self._bg_alpha / 255)
            self._comic_view.set_background_color(QColor(r, g, b, tint_alpha))
        else:
            self.setStyleSheet("")
            self._bg_alpha = 255
            self._comic_view.set_background_color(QColor(r, g, b))

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
        # The viewport only has real geometry now, so an overlay raised
        # during __init__ (a failed initial path) gets placed here.
        self._reposition_error_label()
