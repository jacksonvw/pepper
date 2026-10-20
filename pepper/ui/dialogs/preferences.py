"""Pepper preferences — Window groupbox (shared with Salt) + Image groupbox."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from viewer_core.ui.widgets.appearance_group import AppearanceGroup
from pepper.core.config import AppConfig, load_config, save_config

_ZOOM_OPTIONS = [
    ("fit", "Fit to window"),
    ("shrink", "Shrink to fit (no upscaling)"),
    ("actual", "Actual size (100%)"),
]


class PreferencesDialog(QDialog):
    """Pepper preferences. Emits settings_changed after a successful Apply/OK."""

    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(380)

        self._config: AppConfig = load_config()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._appearance = AppearanceGroup(self._config.appearance)
        layout.addWidget(self._appearance)

        # -- Image groupbox (Pepper-specific) --
        img_group = QGroupBox("Image")
        img_form = QFormLayout(img_group)

        self._zoom_combo = QComboBox()
        for _, label in _ZOOM_OPTIONS:
            self._zoom_combo.addItem(label)
        for i, (key, _) in enumerate(_ZOOM_OPTIONS):
            if key == self._config.default_zoom:
                self._zoom_combo.setCurrentIndex(i)
                break
        img_form.addRow("Default zoom on load:", self._zoom_combo)

        self._resize_window_cb = QCheckBox("Resize window to image on load (VLC-style)")
        self._resize_window_cb.setChecked(self._config.resize_window_to_image)
        img_form.addRow(self._resize_window_cb)

        layout.addWidget(img_group)
        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        layout.addWidget(buttons)

    def _apply_to_config(self) -> None:
        self._appearance.apply_to_config()
        self._config.default_zoom = _ZOOM_OPTIONS[self._zoom_combo.currentIndex()][0]
        self._config.resize_window_to_image = self._resize_window_cb.isChecked()

    def _on_apply(self) -> None:
        self._apply_to_config()
        save_config(self._config)
        self.settings_changed.emit()

    def _on_ok(self) -> None:
        self._on_apply()
        self.accept()
