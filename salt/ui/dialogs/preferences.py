"""Salt preferences — shared Window groupbox + Comic groupbox."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from viewer_core.ui.widgets.appearance_group import AppearanceGroup
from salt.core.config import (
    GAP_MAX,
    GAP_MIN,
    AppConfig,
    load_config,
    save_config,
)

_ORIENTATIONS = [("vertical", "Vertical"), ("horizontal", "Horizontal")]
_FITS = [
    ("horizontal", "Horizontal (width)"),
    ("vertical", "Vertical (height)"),
    ("both", "Both (inside viewport)"),
    ("none", "None (native size)"),
]
_SCROLL_MODES = [("continuous", "Continuous"), ("page", "Page")]


class PreferencesDialog(QDialog):
    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(420)

        self._config: AppConfig = load_config()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._appearance = AppearanceGroup(self._config.appearance)
        layout.addWidget(self._appearance)

        # -- Comic groupbox --
        comic = QGroupBox("Comic")
        form = QFormLayout(comic)

        self._orient_combo = self._combo(_ORIENTATIONS, self._config.orientation)
        form.addRow("Orientation:", self._orient_combo)

        self._fit_combo = self._combo(_FITS, self._config.fit_mode)
        form.addRow("Fit:", self._fit_combo)

        self._scroll_combo = self._combo(_SCROLL_MODES, self._config.scroll_mode)
        form.addRow("Scroll mode:", self._scroll_combo)

        self._gap_slider = QSlider(Qt.Horizontal)
        self._gap_slider.setRange(GAP_MIN, GAP_MAX)
        self._gap_slider.setValue(self._config.page_gap)
        self._gap_label = QLabel(f"{self._gap_slider.value()} px")
        self._gap_slider.valueChanged.connect(
            lambda v: self._gap_label.setText(f"{v} px")
        )
        row = QHBoxLayout()
        row.addWidget(self._gap_slider)
        row.addWidget(self._gap_label)
        form.addRow("Page gap:", row)

        layout.addWidget(comic)
        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        layout.addWidget(buttons)

    def _combo(self, options: list, current_key: str) -> QComboBox:
        combo = QComboBox()
        for _, label in options:
            combo.addItem(label)
        for i, (key, _) in enumerate(options):
            if key == current_key:
                combo.setCurrentIndex(i)
                break
        combo._options = options  # stash for read-back
        return combo

    def _apply_to_config(self) -> None:
        self._appearance.apply_to_config()
        self._config.orientation = self._orient_combo._options[
            self._orient_combo.currentIndex()
        ][0]
        self._config.fit_mode = self._fit_combo._options[
            self._fit_combo.currentIndex()
        ][0]
        self._config.scroll_mode = self._scroll_combo._options[
            self._scroll_combo.currentIndex()
        ][0]
        self._config.page_gap = self._gap_slider.value()

    def _on_apply(self) -> None:
        self._apply_to_config()
        save_config(self._config)
        self.settings_changed.emit()

    def _on_ok(self) -> None:
        self._on_apply()
        self.accept()
