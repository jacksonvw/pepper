"""Smoke imports — every Salt module imports cleanly under offscreen Qt."""


def test_import_main():
    import salt.main  # noqa: F401


def test_import_config():
    from salt.core.config import AppConfig, load_config, save_config  # noqa: F401


def test_import_archive():
    from salt.core.archive import ImageEntry, open_source  # noqa: F401


def test_import_comic_view():
    from salt.ui.comic_view import ComicView  # noqa: F401


def test_import_main_window():
    from salt.ui.main_window import MainWindow  # noqa: F401


def test_import_preferences():
    from salt.ui.dialogs.preferences import PreferencesDialog  # noqa: F401
