"""Salt — minimal-UI comic / image-set viewer for Linux."""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from viewer_core.core.decoding import raise_decode_limit

log = logging.getLogger("salt")


def _excepthook(et, ev, tb) -> None:
    traceback.print_exception(et, ev, tb)
    log.error("uncaught exception", exc_info=(et, ev, tb))


def main() -> None:
    faulthandler.enable()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.excepthook = _excepthook

    log.info("starting; argv=%r; cwd=%s", sys.argv, os.getcwd())

    app = QApplication(sys.argv)
    app.setApplicationName("Salt")
    app.setOrganizationName("salt")
    # The Wayland app_id; it has to match the installed salt.desktop.
    app.setDesktopFileName("salt")
    raise_decode_limit()

    # By theme name, so KWin draws the icon itself from the copy that
    # desktop/install.sh puts in hicolor. An icon from a file reaches it
    # as pixels with the alpha misread, which fringes every anti-aliased
    # edge black. The bundled file is the fallback when not installed.
    icon_path = Path(__file__).parent / "resources" / "salt.svg"
    app.setWindowIcon(QIcon.fromTheme("salt", QIcon(str(icon_path))))

    from salt.ui.main_window import MainWindow

    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    initial_path = files[0] if files else None

    window = MainWindow(initial_path=initial_path)
    window.show()

    ret = app.exec()
    os._exit(ret)


if __name__ == "__main__":
    main()
