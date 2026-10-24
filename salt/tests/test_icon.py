"""The app icon follows the colour scheme, as Breeze's monochrome icons do.

Plasma swaps in the current scheme's ColorScheme-Text colour, so the icon
is light on a dark title bar and dark on a light one. Anything that doesn't
know the convention, Qt's own SVG renderer included, draws the default.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ICON = Path(__file__).resolve().parents[1] / "resources" / "salt.svg"
NS = "{http://www.w3.org/2000/svg}"


def test_icon_paints_in_the_colour_scheme_text_colour():
    root = ET.parse(ICON).getroot()
    style = root.find(f"{NS}style")
    assert style is not None and style.get("id") == "current-color-scheme"
    assert ".ColorScheme-Text" in style.text
    shapes = [e for e in root if e.tag != f"{NS}style"]
    assert shapes
    for shape in shapes:
        assert shape.get("class") == "ColorScheme-Text"
        paints = {shape.get("fill"), shape.get("stroke")} - {None, "none"}
        assert paints == {"currentColor"}


def test_without_kde_the_icon_draws_breeze_text_grey(qapp):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    img = QImage(64, 64, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    QSvgRenderer(str(ICON)).render(painter, QRectF(0, 0, 64, 64))
    painter.end()
    assert img.pixelColor(20, 44).name() == "#232629"
